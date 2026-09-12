"""合成文献自测服务（AI 提取准确度自测）。

流程：
1. 程序确定性生成 ground truth（含种子可复现，每点标注噪声类型）。
2. 调用生成模型 A，把每个数据点写成学术文献正文/表格（噪声点写成错误形式），入库 literature。
3. 指定提取模型 B，对合成文献走现有提取链路。
4. 提取完成后，将提取数据点与 GT 比对，产出精确/容差/噪声感知三级评估。
"""
import logging
import random
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import async_session
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.models.synthetic_task import SyntheticTask
from app.services.extraction_service import trigger_extraction
from app.services.report_service import _call_llm

logger = logging.getLogger("uvicorn")

PROVINCES = [
    "北京", "上海", "广东", "江苏", "浙江", "山东", "河南", "湖北", "湖南",
    "四川", "陕西", "河北", "辽宁", "福建", "安徽", "云南", "甘肃", "重庆",
]
CITIES = ["市区", "城区", "农村", "某县"]

NOISE_KINDS = ["out_of_range", "missing_field", "format_variant", "wrong_value"]


# ===================== Ground Truth 生成 =====================

def _gen_point(rng: random.Random, idx: int, disease: str, noise_kind: str | None) -> dict:
    """生成单个数据点。noise_kind 非空时标注噪声类型。"""
    data_type = "gmc" if rng.random() < 0.5 else "seroprevalence"
    province = rng.choice(CITIES) and rng.choice(PROVINCES)
    city = rng.choice(CITIES)
    sample_size = rng.randint(50, 5000)
    age_min = rng.choice([0, 1, 2, 3, 6, 12, 18])
    age_max = rng.choice([10, 20, 30, 40, 50, 60, 70])
    if age_max < age_min:
        age_min, age_max = age_max, age_min
    collection_year = rng.randint(2000, 2022)
    if data_type == "seroprevalence":
        # 逼真但命中率略高：多数围绕 40-95%
        span = rng.randint(1, 120) / 10.0  # 0.1~12.0
        value = round(rng.uniform(30, 95), 1) + span
        value = max(0.1, min(99.9, rate_round(value)))
        unit = "%"
    else:
        value = round(rng.uniform(100, 2000), 1)
        unit = "U/mL"

    pt = {
        "idx": idx,
        "data_type": data_type,
        "value": value,
        "unit": unit,
        "province": province,
        "city": city,
        "sample_size": sample_size,
        "age_min": age_min,
        "age_max": age_max,
        "collection_year": collection_year,
        "noise_kind": noise_kind,
    }
    return pt


def rate_round(v: float) -> float:
    """阳性率四舍五入到 0.1。"""
    return round(v * 10) / 10.0


def generate_ground_truth(disease: str, n_literatures: int, points_per_literature: int,
                          noise_ratio: float, seed: int) -> list[list[dict]]:
    """确定性生成 N 篇 × M 点的 ground truth。噪声点随机分配到各噪声类型。"""
    rng = random.Random(seed)
    all_lits = []
    for _ in range(n_literatures):
        kinds = [None] * points_per_literature
        n_noise = max(0, min(points_per_literature, round(points_per_literature * noise_ratio)))
        noise_idx = rng.sample(range(points_per_literature), n_noise)
        # 均匀分配噪声类型（不足时循环）
        for j, ni in enumerate(noise_idx):
            kinds[ni] = NOISE_KINDS[j % len(NOISE_KINDS)]
        pts = [_gen_point(rng, i + 1, disease, kinds[i]) for i in range(points_per_literature)]
        all_lits.append(pts)
    return all_lits


# ===================== 生成 Prompt / 文献 =====================

def _clean_repr(pt: dict, disease: str) -> str:
    if pt["data_type"] == "seroprevalence":
        return (f"在{pt['province']}省{pt['city']}地区，{pt['age_min']}-{pt['age_max']}岁人群中，"
                f"{pt['collection_year']}年共检测 {pt['sample_size']} 份血清样本，"
                f"麻疹血清阳性率为 {pt['value']}%。")
    return (f"在{pt['province']}省{pt['city']}地区，{pt['age_min']}-{pt['age_max']}岁人群中，"
            f"{pt['collection_year']}年检测 {pt['sample_size']} 名受试者，"
            f"麻疹特异性中和抗体平均几何滴度（GMT）为 {pt['value']} U/mL。")


def _noise_repr(pt: dict, disease: str) -> str:
    kind = pt["noise_kind"]
    clean = _clean_repr(pt, disease)
    if kind == "out_of_range":
        # 数值越界：阳性率>100% / GMC 为负 / 样本量为 0
        if pt["data_type"] == "seroprevalence":
            return (f"在{pt['province']}省{pt['city']}地区，{pt['collection_year']}年检测 "
                    f"共 {max(1, pt['sample_size'])} 份样本，麻疹血清阳性率高达 115%，可能与疫苗加强有关。")
        return (f"在{pt['province']}省{pt['city']}地区，{pt['collection_year']}年麻疹GMT平均几何滴度"
                f"测得为 -{pt['value']} U/mL，低于检出限。")
    if kind == "missing_field":
        # 缺关键字段：省略样本量或省份
        if pt["data_type"] == "seroprevalence":
            return f"本地区麻疹血清阳性率为 {pt['value']}%，于{pt['collection_year']}年完成。"
        return f"某地区麻疹GMT为 {pt['value']} U/mL，采用ELISA检测。"
    if kind == "format_variant":
        # 格式变异：单位错误 / 写成区间 / 四舍五入表述
        if pt["data_type"] == "seroprevalence":
            return f"{pt['province']}省当地麻疹血清阳性率约为 {pt['value']}%至{min(99.9, pt['value'] + 5)}%。"
        return (f"{pt['province']}省当地麻疹GMT平均几何滴度为 {pt['value']} mg/dL"
                f"（样本量{pt['sample_size']}，{pt['age_min']}-{pt['age_max']}岁，{pt['collection_year']}年）。")
    # wrong_value：完全错误值（写成别的病/明显错误数值）
    other = round(pt["value"] * 7.3, 1)
    if pt["data_type"] == "seroprevalence":
        return (f"在{pt['province']}省{pt['city']}地区，{pt['collection_year']}年检测 "
                f"{pt['sample_size']} 份样本，麻疹血清阳性率为 {min(99.9, other)}%，"
                f"该数值接近风疹抗体水平，供参考。")
    return (f"在{pt['province']}省{pt['city']}地区，{pt['collection_year']}年麻疹GMT为 "
            f"{other} U/mL，样本来自门诊随访人群。")


def _build_token_lines(points: list[dict], disease: str) -> list[str]:
    """生成模型 A 需要逐条嵌入正文的「结果陈述」。噪声点用错误表述，clean 用正确表述。"""
    lines = []
    for pt in points:
        if pt["noise_kind"]:
            lines.append(f"[本条需写入] {_noise_repr(pt, disease)}")
        else:
            lines.append(f"[本条需写入] {_clean_repr(pt, disease)}")
    return lines


def build_generation_prompt(disease: str, points: list[dict], lit_no: int) -> str:
    lines = "\n".join(_build_token_lines(points, disease))
    return (
        f"你是一位流行病学研究者，请撰写一篇关于「{disease}」血清流行病学调查的中文学术文献草稿"
        f"（第 {lit_no} 篇）。\n"
        "要求：\n"
        "1. 内容需完整连贯，包含：题目、摘要、方法（研究对象/样本采集/检测方法）、结果、讨论、结论。\n"
        "2. 结果部分必须用自然流畅的学术论述，并把下面给出的【结果陈述】逐条、原样地植入正文中"
        "（数值、省份、年份不得改动），同时把这些陈述汇总成一个 Markdown 表格放在结果部分末尾。\n"
        "3. 每条约 1-3 句即可，可用不同措辞衔接，但关键数值必须与陈述一致。\n"
        f"结果陈述如下：\n{lines}\n"
        "请直接输出完整文献全文，不要输出额外解释。"
    )


async def _generate_one(db: AsyncSession, task: SyntheticTask, points: list[dict], lit_no: int) -> str:
    """调用生成模型 A 生成一篇文献全文。"""
    prompt = build_generation_prompt(task.disease, points, lit_no)
    content = await _call_llm(db, prompt, model=task.generator_model)
    if not content or not content.strip():
        raise RuntimeError(f"生成模型返回空内容（第 {lit_no} 篇）")
    return content.strip()


# ===================== 生成任务（后台） =====================

async def run_generation(task_id: uuid.UUID):
    """后台生成全部合成文献并入库。使用独立会话。"""
    try:
        async with async_session() as db:
            task = await _get_task(db, task_id)
            if not task:
                return
            task.status = "generating"
            await db.commit()

            gt = task.gt_json or []
            lit_ids = []
            for i, points in enumerate(gt, start=1):
                content = await _generate_one(db, task, points, i)
                lit = Literature(
                    title=f"[合成]{task.disease}血清流行病学调查 第{i}篇",
                    abstract=content,
                    source_db="synthetic",
                    has_fulltext=True,
                    extraction_status="pending",
                )
                db.add(lit)
                await db.flush()
                lit_ids.append(str(lit.id))
            task.literature_ids = lit_ids
            task.status = "ready"
            await db.commit()
            logger.info(f"[Synthetic] 任务 {task_id} 生成完成：{len(lit_ids)} 篇")
    except Exception as e:
        logger.error(f"[Synthetic] 任务 {task_id} 生成失败: {e}", exc_info=True)
        async with async_session() as db:
            t = await _get_task(db, task_id)
            if t:
                from sqlalchemy import update
                await db.execute(
                    update(SyntheticTask)
                    .where(SyntheticTask.id == task_id)
                    .values(status="failed", error_message=str(e)[:2000])
                )
                await db.commit()


async def _get_task(db: AsyncSession, task_id: uuid.UUID) -> SyntheticTask | None:
    r = await db.execute(select(SyntheticTask).where(SyntheticTask.id == task_id))
    return r.scalar_one_or_none()


async def trigger_extraction_for_task(db: AsyncSession, task_id: uuid.UUID, model: str):
    """对任务内所有合成文献按模型 B 触发提取。"""
    task = await _get_task(db, task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.status not in ("ready", "assessed", "extracting"):
        raise ValueError(f"任务当前状态 {task.status}，无法触发提取")

    if not task.literature_ids:
        raise ValueError("任务尚未生成文献")

    task.extractor_model = model
    task.status = "extracting"
    await db.commit()

    errors = []
    for lid_str in task.literature_ids:
        try:
            lit_id = uuid.UUID(lid_str)
            lit = (await db.execute(select(Literature).where(Literature.id == lit_id))).scalar_one_or_none()
            if not lit:
                continue
            if lit.extraction_status in ("processing", "queued"):
                continue
            await trigger_extraction(
                db, lit_id, model=model,
                clear_existing_data=True, use_cache=False,
            )
        except Exception as e:
            logger.warning(f"[Synthetic] 触发提取文献 {lid_str} 失败: {e}")
            errors.append(str(e))
    return {"submitted": len(task.literature_ids), "errors": errors}


async def extraction_progress(db: AsyncSession, task_id: uuid.UUID) -> list[dict]:
    """返回任务内每篇合成文献的提取状态（供前端轮询）。"""
    task = await _get_task(db, task_id)
    if not task or not task.literature_ids:
        return []
    items = []
    for lid_str in task.literature_ids:
        lit = (await db.execute(
            select(Literature.id, Literature.title, Literature.extraction_status)
            .where(Literature.id == uuid.UUID(lid_str))
        )).one_or_none()
        if lit:
            items.append({
                "id": lit.id,
                "title": lit.title,
                "extraction_status": lit.extraction_status,
            })
    return items


# ===================== 评估 =====================

def _rel_close(a, b, tol: float = 0.05) -> bool:
    """数值相对误差匹配（综合口径里的容差匹配）。"""
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if a == b:
        return True
    if a == 0 or b == 0:
        return abs(a - b) <= tol * max(abs(a), abs(b), 1.0)
    return abs(a - b) / max(abs(a), abs(b)) <= tol


def _same_str(a, b) -> bool:
    return (a or "").strip() == (b or "").strip()


def _match_clean(gt: dict, ex: dict) -> bool:
    """判断单个 GT clean 点是否被提取点 ex 命中（容差口径）。"""
    if gt["data_type"] != (ex.get("data_type") or ""):
        return False
    if gt["province"] and gt["province"] not in (ex.get("province") or ""):
        return False
    if not _rel_close(gt["value"], ex.get("value")):
        return False
    return True


def assess_task(db_data: dict) -> dict:
    """基于每篇文献对 GT 与提取数据点比对，产出评估报告。"""
    disease = db_data["disease"]
    gt_by_lit: dict[str, list[dict]] = db_data["gt_by_literature"]
    ex_by_lit: dict[str, list[dict]] = db_data["ex_by_literature"]

    all_clean = 0
    all_noise = 0
    clean_matched = 0
    clean_exact = 0
    noise_rejected = 0
    field_totals: dict[str, int] = {}
    field_correct: dict[str, int] = {}
    per_noise = {k: {"total": 0, "rejected": 0} for k in NOISE_KINDS}
    lit_rows = []

    for lit_key, gts in gt_by_lit.items():
        exts = ex_by_lit.get(lit_key, [])
        n_clean = sum(1 for g in gts if not g["noise_kind"])
        n_noise = sum(1 for g in gts if g["noise_kind"])
        used = [False] * len(exts)
        m_clean = 0
        m_exact = 0
        r_noise = 0

        # 先匹配 clean 点（贪心）
        clean_pts = [g for g in gts if not g["noise_kind"]]
        for g in clean_pts:
            best = -1
            for j, ex in enumerate(exts):
                if used[j]:
                    continue
                if _match_clean(g, ex):
                    best = j
                    break
            if best >= 0:
                used[best] = True
                m_clean += 1
                ex = exts[best]
                # 精确值判定
                if _rel_close(g["value"], ex.get("value"), 1e-9):
                    m_exact += 1
                # 字段级正确性
                checks = {
                    "disease": disease in (ex.get("disease") or ""),
                    "province": g["province"] and g["province"] in (ex.get("province") or ""),
                    "data_type": _same_str(g["data_type"], ex.get("data_type")),
                    "sample_size": (ex.get("sample_size") or 0) == g["sample_size"],
                    "collection_year": (ex.get("collection_year") or 0) == g["collection_year"],
                    "value": _rel_close(g["value"], ex.get("value")),
                }
                for f, ok in checks.items():
                    field_totals[f] = field_totals.get(f, 0) + 1
                    if ok:
                        field_correct[f] = field_correct.get(f, 0) + 1

        # 噪声点：未被任何提取点命中 → 正确拒绝
        noise_pts = [g for g in gts if g["noise_kind"]]
        for g in noise_pts:
            per_noise[g["noise_kind"]]["total"] += 1
            fooled = False
            for j, ex in enumerate(exts):
                if used[j]:
                    continue
                # 噪声点被误采（提取点数值与噪声点数值/省份/类型相符即视为误导成功）
                if _noise_fooled(g, ex):
                    fooled = True
                    used[j] = True
                    break
            if not fooled:
                r_noise += 1
                per_noise[g["noise_kind"]]["rejected"] += 1

        all_clean += n_clean
        all_noise += n_noise
        clean_matched += m_clean
        clean_exact += m_exact
        noise_rejected += r_noise
        lit_rows.append({
            "literature_id": lit_key,
            "clean_total": n_clean,
            "clean_matched": m_clean,
            "noise_total": n_noise,
            "noise_rejected": r_noise,
        })

    def _recall(n, d):
        return round(n / d, 4) if d else 0.0

    summary = {
        "disease": disease,
        "clean_total": all_clean,
        "clean_matched": all_clean and clean_matched or 0,
        "clean_recall": _recall(clean_matched, all_clean),
        "value_exact_rate": _recall(clean_exact, all_clean),
        "value_tolerance_rate": all_clean and _recall(clean_matched, all_clean) or 0.0,
        "noise_total": all_noise,
        "noise_rejected": noise_rejected,
        "noise_rejection_rate": _recall(noise_rejected, all_noise),
        "field_accuracy": {
            f: round(field_correct.get(f, 0) / field_totals[f], 4) if field_totals.get(f) else 0
            for f in field_totals
        },
        "per_noise_type": {
            k: {
                "total": v["total"],
                "rejected": v["rejected"],
                "rejection_rate": _recall(v["rejected"], v["total"]),
            }
            for k, v in per_noise.items()
        },
    }
    return {"summary": summary, "by_literature": lit_rows}


def _noise_fooled(gt: dict, ex: dict) -> bool:
    """噪声点 g 是否被提取点 ex 误导命中。"""
    if gt["data_type"] != (ex.get("data_type") or ""):
        return False
    if not _rel_close(gt["value"], ex.get("value")):
        return False
    # 噪声点本身可能无省份（missing_field），只看类型+数值
    if gt["province"] and gt["province"] not in (ex.get("province") or ""):
        return False
    return True


async def compute_assessment(db: AsyncSession, task_id: uuid.UUID) -> dict:
    """汇总任务内各文献提取结果并计算评估报告，写回 report_json。"""
    task = await _get_task(db, task_id)
    if not task:
        raise ValueError("任务不存在")
    if not task.literature_ids or not task.gt_json:
        raise ValueError("任务缺少文献或 ground truth")

    gt_flat = task.gt_json
    gt_by_lit = {f"lit{i}": pts for i, pts in enumerate(gt_flat)}
    ex_by_lit = {}
    pending_progress = []
    for i, lid_str in enumerate(task.literature_ids):
        lit = (await db.execute(
            select(Literature).where(Literature.id == uuid.UUID(lid_str))
        )).scalar_one_or_none()
        if not lit:
            continue
        key = f"lit{i}"
        if lit.extraction_status == "done":
            rows = (await db.execute(
                select(DataPoint).where(
                    DataPoint.literature_id == lit.id,
                    DataPoint.review_status == "pending",
                )
            )).scalars().all()
            ex_by_lit[key] = [
                {
                    "data_type": r.data_type,
                    "value": float(r.value) if r.value is not None else None,
                    "province": r.province,
                    "city": r.city,
                    "sample_size": r.sample_size,
                    "collection_year": r.collection_year,
                    "disease": r.disease,
                }
                for r in rows
            ]
            continue
        # 未完成，记录进度
        pending_progress.append({
            "literature_id": lid_str,
            "extraction_status": lit.extraction_status,
        })

    if pending_progress:
        waiting = ",".join(f"{p['literature_id']}({p['extraction_status']})" for p in pending_progress)
        raise RuntimeError("仍有文献未完成提取：" + waiting)

    report = assess_task({
        "disease": task.disease,
        "gt_by_literature": gt_by_lit,
        "ex_by_literature": ex_by_lit,
    })
    task.report_json = report
    task.status = "assessed"
    await db.commit()
    return report
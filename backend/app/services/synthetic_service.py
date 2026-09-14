"""合成文献自测服务（AI 提取准确度自测）。

流程：
1. 程序确定性生成 ground truth（含种子可复现，每点标注噪声类型）。
2. 调用生成模型 A，把每个数据点写成学术文献正文/表格（噪声点写成错误形式），入库 literature。
3. 指定提取模型 B，对合成文献走现有提取链路。
4. 提取完成后，将提取数据点与 GT 比对，产出精确/容差/噪声感知三级评估。
"""
import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.timeutil import iso_ts
from app.models.base import async_session
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.models.synthetic_task import SyntheticTask
from app.services.extraction_service import trigger_extraction
from app.services.report_service import _call_llm

from app.core.extraction.orchestrator import LLMExtractor
from app.models.synthetic_extraction import SyntheticExtraction
from app.services.literature._common import LOCAL_STORAGE_DIR

logger = logging.getLogger("uvicorn")

# 多模型对比后台提取任务引用，防止被垃圾回收
_bg_multi_tasks: set = set()

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


def build_generation_prompt(disease: str, points: list[dict], lit_no: int, include_table: bool = True) -> str:
    lines = "\n".join(_build_token_lines(points, disease))
    table_instruction = (
        "把这些陈述汇总成一个 Markdown 表格放在结果部分末尾。"
        if include_table else
        "结果部分不要列表格，只用文字论述数值即可。"
    )
    return (
        f"你是一位流行病学研究者，请撰写一篇关于「{disease}」血清流行病学调查的中文学术文献草稿"
        f"（第 {lit_no} 篇）。\n"
        "要求：\n"
        "1. 内容需完整连贯，包含：题目、摘要、方法（研究对象/样本采集/检测方法）、结果、讨论、结论。\n"
        "2. 结果部分必须用自然流畅的学术论述，并把下面给出的【结果陈述】逐条、原样地植入正文中"
        "（数值、省份、年份不得改动）。\n"
        "3. 每条约 1-3 句即可，可用不同措辞衔接，但关键数值必须与陈述一致。\n"
        "4. " + table_instruction + "\n"
        f"结果陈述如下：\n{lines}\n"
        "请直接输出完整文献全文，不要输出额外解释。"
    )


async def _generate_one(db: AsyncSession, task: SyntheticTask, points: list[dict], lit_no: int) -> str:
    """调用生成模型 A 生成一篇文献全文。"""
    prompt = build_generation_prompt(task.disease, points, lit_no, task.include_table)
    content = await _call_llm(db, prompt, model=task.generator_model)
    if not content or not content.strip():
        raise RuntimeError(f"生成模型返回空内容（第 {lit_no} 篇）")
    return content.strip()


def _build_literature_pdf(content: str, points: list[dict], disease: str, include_table: bool) -> bytes:
    """把生成的文献全文（含可选表格）渲染为 PDF，返回字节流（STSong-Light 中文字体）。

    PDF 文献会走真实的 PDF 解析链路（AnyDoc/pdftotext/pdfplumber），用于更全面地
    验证提取模型 B 在 PDF 载体下的准确度与效率。
    """
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    _FONT = "STSong-Light"
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
    except Exception:
        pass

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontName = _FONT
    title_style.alignment = TA_CENTER
    body = styles["Normal"]
    body.fontName = _FONT
    body.fontSize = 10
    heading = styles["Heading2"]
    heading.fontName = _FONT
    heading.fontSize = 12

    story = []
    for block in content.split("\n\n"):
        line = block.strip()
        if not line:
            continue
        if line.startswith("#"):
            story.append(Paragraph(line.lstrip("#").strip(), heading))
        else:
            story.append(Paragraph(line.replace("\n", " "), body))

    if include_table and points:
        story.append(Spacer(1, 6 * mm))
        rows = [[f"{disease}阳性率(%)", "样本量", "地区", "人群/年份"]]
        for pt in points:
            unit = pt.get("unit", "")
            val = pt.get("value")
            kind = pt.get("noise_kind")
            val_text = f"{val}{unit}（噪声:{kind or '无'}）" if kind else f"{val}{unit}"
            rows.append([
                pt.get("data_type", ""),
                str(pt.get("sample_size", "")),
                pt.get("province", ""),
                val_text,
            ])
        table = Table(rows)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _FONT),
            ("FONTNAME", (0, 0), (-1, 0), _FONT),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0fe")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(table)

    doc.build(story)
    return buf.getvalue()


# ===================== 生成任务（后台） =====================

async def run_generation(task_id: uuid.UUID):
    """后台生成全部合成文献并入库。使用独立会话。"""
    try:
        async with async_session() as db:
            task = await _get_task(db, task_id)
            if not task:
                return
            task.status = "generating"
            task.generation_started_at = datetime.now(timezone.utc)
            await db.commit()

            gt = task.gt_json or []
            lit_ids = []
            pdf_dir = Path("/app/backend/data/pdfs")
            is_pdf = (task.output_format or "text") == "pdf"
            if is_pdf:
                pdf_dir.mkdir(parents=True, exist_ok=True)
            for i, points in enumerate(gt, start=1):
                content = await _generate_one(db, task, points, i)
                lit = Literature(
                    title=f"[合成]{task.disease}血清流行病学调查 第{i}篇",
                    abstract=content,
                    source_db="synthetic",
                    has_fulltext=True,
                    extraction_status="pending",
                )
                if is_pdf:
                    # PDF 载体：写入真实 PDF 文件，走 PDF 解析链路
                    pdf_bytes = _build_literature_pdf(content, points, task.disease, task.include_table)
                    pdf_path = pdf_dir / f"{lit.id}.pdf"
                    pdf_path.write_bytes(pdf_bytes)
                    lit.file_path = str(pdf_path)
                db.add(lit)
                await db.flush()
                lit_ids.append(str(lit.id))
            task.literature_ids = lit_ids
            task.status = "ready"
            task.generated_at = datetime.now(timezone.utc)
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
    task.extraction_started_at = datetime.now(timezone.utc)
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

def ltbool(v: bool) -> bool:
    """numpy.bool_ → python bool，便于 JSON 序列化。"""
    return bool(v)


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
    """基于每篇文献对 GT 与提取数据点比对，产出评估报告。

    除指标汇总外，还为逐文献提供 GT 数据点、提取模型 B 识别的数据点、
    以及二者的逐点匹配明细，供前端逐一核对生成内容与提取结果。
    """
    disease = db_data["disease"]
    gt_by_lit: dict[str, list[dict]] = db_data["gt_by_literature"]
    ex_by_lit: dict[str, list[dict]] = db_data["ex_by_literature"]
    lit_titles: dict[str, str] = db_data.get("lit_titles", {})
    lit_meta: dict[str, dict] = db_data.get("lit_meta", {})

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
        n_clean = sum(1 for g in gts if not g.get("noise_kind"))
        n_noise = sum(1 for g in gts if g.get("noise_kind"))
        used = [False] * len(exts)
        gt_matched = [False] * len(gts)
        ex_gtslot: list[int | None] = [None] * len(exts)
        m_clean = 0
        m_exact = 0
        r_noise = 0

        # 先匹配 clean 点（贪心）
        for k, g in enumerate(gts):
            if g.get("noise_kind"):
                continue
            best = -1
            for j, ex in enumerate(exts):
                if used[j]:
                    continue
                if _match_clean(g, ex):
                    best = j
                    break
            if best >= 0:
                used[best] = True
                gt_matched[k] = True
                ex_gtslot[best] = k
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
        for i, g in enumerate(gts):
            if not g.get("noise_kind"):
                continue
            per_noise[g.get("noise_kind")]["total"] += 1
            fooled = False
            for j, ex in enumerate(exts):
                if used[j]:
                    continue
                # 噪声点被误采（提取点数值与噪声点数值/省份/类型相符即视为误导成功）
                if _noise_fooled(g, ex):
                    fooled = True
                    used[j] = True
                    ex_gtslot[j] = i
                    gt_matched[i] = True
                    break
            if not fooled:
                r_noise += 1
                per_noise[g.get("noise_kind")]["rejected"] += 1

        all_clean += n_clean
        all_noise += n_noise
        clean_matched += m_clean
        clean_exact += m_exact
        noise_rejected += r_noise

        gt_rows = [
            {
                "idx": i,
                "data_type": g["data_type"],
                "value": g["value"],
                "unit": g.get("unit"),
                "sample_size": g["sample_size"],
                "province": g["province"],
                "collection_year": g["collection_year"],
                "noise_kind": g.get("noise_kind"),
                "matched": ltbool(gt_matched[i]),
            }
            for i, g in enumerate(gts)
        ]
        ex_rows = [
            {
                "idx": j,
                "data_type": ex.get("data_type"),
                "value": ex.get("value"),
                "unit": ex.get("unit"),
                "province": ex.get("province"),
                "city": ex.get("city"),
                "sample_size": ex.get("sample_size"),
                "collection_year": ex.get("collection_year"),
                "gt_idx": ex_gtslot[j],  # 命中到哪个 GT 点（None=模型 B 额外识别/未对应）
            }
            for j, ex in enumerate(exts)
        ]
        meta = lit_meta.get(lit_key, {})
        lit_rows.append({
            "literature_id": meta.get("id") or lit_key,
            "title": meta.get("title") or lit_titles.get(lit_key),
            "clean_total": n_clean,
            "clean_matched": m_clean,
            "noise_total": n_noise,
            "noise_rejected": r_noise,
            "gt_points": gt_rows,
            "extracted_points": ex_rows,
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
    lit_meta: dict[str, dict] = {}
    pending_progress = []
    for i, lid_str in enumerate(task.literature_ids):
        lit = (await db.execute(
            select(Literature).where(Literature.id == uuid.UUID(lid_str))
        )).scalar_one_or_none()
        if not lit:
            continue
        key = f"lit{i}"
        lit_meta[key] = {"id": str(lit.id), "title": lit.title or f"文献{i+1}"}
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
        "lit_meta": lit_meta,
    })
    task.report_json = report
    task.status = "assessed"
    task.extracted_at = datetime.now(timezone.utc)
    await db.commit()
    return report


# ===================== 多模型对比（支持 existing/已有文献） =====================

def _lit_text_path(lit_id: uuid.UUID) -> Path:
    """该文献的全文文本缓存路径（data/pdfs/{id}.txt，与后台 KG 抽取共用）。"""
    return LOCAL_STORAGE_DIR / f"{lit_id}.txt"


def _norm_extract_points(cleaned: dict) -> list[dict]:
    """把 LLMExtractor 输出（后处理点）归一为评估用的 ex 点结构。

    血清阳性率→seroprevalence 点、GMC→gmc 点，字段对齐 assess_task 的 ex 点。
    不匹配任何点则返回空。
    """
    out: list[dict] = []
    province = cleaned.get("province")
    city = cleaned.get("city")
    sample_size = cleaned.get("sample_size")
    year = (
        cleaned.get("sample_year")
        or cleaned.get("study_start_year")
        or cleaned.get("study_end_year")
    )
    disease = cleaned.get("disease_name") or cleaned.get("disease") or cleaned.get("antibody_type")
    base = {
        "province": province,
        "city": city,
        "sample_size": sample_size,
        "collection_year": year,
        "disease": disease,
    }
    if cleaned.get("positivity_rate") is not None:
        out.append({
            "data_type": "seroprevalence",
            "value": float(cleaned["positivity_rate"]),
            "unit": "%",
            **base,
        })
    if cleaned.get("gmc_value") is not None:
        out.append({
            "data_type": "gmc",
            "value": float(cleaned["gmc_value"]),
            "unit": cleaned.get("gmc_unit"),
            **base,
        })
    return out


async def _extract_lit_points(model: str, lit: Literature) -> list[dict]:
    """用指定模型对一篇文献纯抽取（不写库、不动 data_point），返回归一化点数组。

    文本来源依次回退：data/pdfs/{id}.txt 缓存全文 → 无缓存但有内容时用库内
    title + journal + pub_year + abstract 拼装的提取文本。两者皆不足 100 字符才抛错。
    """
    txt_path = _lit_text_path(lit.id)
    text = ""
    if txt_path.exists():
        text = txt_path.read_text(encoding="utf-8")
    if len(text) < 100:
        parts = [lit.title or ""]
        if lit.journal:
            parts.append(lit.journal)
        if getattr(lit, "pub_year", None):
            parts.append(str(lit.pub_year))
        if lit.abstract:
            parts.append(lit.abstract)
        text = "\n".join(p for p in parts if p)
    if len(text) < 100:
        raise ValueError("文献无可提取文本（无缓存全文且无有效摘要/正文）")
    extractor = LLMExtractor(model=model)
    raw = await extractor.extract_with_retry(
        text, title=lit.title, journal=getattr(lit, "journal", None),
        pub_year=getattr(lit, "pub_year", None),
    )
    points: list[dict] = []
    for rc in raw:
        if isinstance(rc, dict):
            points.extend(_norm_extract_points(rc))
    return points


async def trigger_reference_gt(db: AsyncSession, task_id: uuid.UUID,
                               reference_model: str | None = None) -> dict:
    """existing 来源任务：用参考模型对每篇文献纯提取，产出基准(GT)写入 task.gt_json。

    结果不写入 literature.data_point，不污染真实文献数据。
    全程自管短生命周期会话，不跨慢速 LLM 调用持有连接；传入的 db 仅作兼容，
    初始读取与最终写回都在本函数内用新会话完成。
    """
    async with async_session() as sdb0:
        task = await _get_task(sdb0, task_id)
        if not task:
            raise ValueError("任务不存在")
        if task.literature_source != "existing":
            raise ValueError("仅 existing（已有文献）来源任务需要生成参考基准 GT")
        model = reference_model or task.reference_model
        if not model:
            raise ValueError("缺少参考模型 reference_model，无法生成基准 GT")
        # 状态改为 generating（短会话写库，避免长连接闲置）
        t = await _get_task(sdb0, task_id)
        t.status = "generating"
        await sdb0.commit()

    per_lit: list[list[dict]] = []
    n_lit = len(task.literature_ids or [])
    for idx, lid_str in enumerate(task.literature_ids or [], 1):
        try:
            # 每篇用短生命周期会话查询文献，不跨慢速 LLM 调用持有连接
            async with async_session() as sdb:
                lit = (await sdb.execute(
                    select(Literature).where(Literature.id == uuid.UUID(lid_str))
                )).scalar_one_or_none()
            if lit is None:
                raise ValueError("文献不存在或已删除")
            pts = await _extract_lit_points(model, lit)
        except Exception as e:
            raise RuntimeError(f"文献 {lid_str} 生成参考基准失败: {e}") from e
        per_lit.append(pts)
        with open("/app/backend/data/reference_gt_progress.log", "a", encoding="utf-8") as pf:
            pf.write(f"{iso_ts(datetime.now(timezone.utc))} done {idx}/{n_lit} lit={str(lid_str)[:8]}\n")

    # 最终写回用新会话
    async with async_session() as sdb:
        t = await _get_task(sdb, task_id)
        t.gt_json = per_lit
        t.reference_model = model
        t.generated_at = datetime.now(timezone.utc)
        t.status = "ready"
        await sdb.commit()
    return {"literatures": len(per_lit), "reference_model": model}


async def _run_multi_extraction(task_id: str) -> None:
    """后台：对任务内每个 (模型 × 文献) 依次纯抽取，结果写入 synthetic_extraction。"""
    async with async_session() as db:
        try:
            tid = uuid.UUID(task_id)
            task = await _get_task(db, tid)
            if not task:
                return
            rows = (await db.execute(
                select(SyntheticExtraction).where(
                    SyntheticExtraction.task_id == tid,
                    SyntheticExtraction.status == "pending",
                )
            )).scalars().all()
            # 预取文献元信息
            for lit_id in {r.literature_id for r in rows}:
                pass
            infos: dict = {}
            for r in rows:
                if r.literature_id not in infos:
                    lit = (await db.execute(
                        select(Literature).where(Literature.id == r.literature_id)
                    )).scalar_one_or_none()
                    infos[r.literature_id] = lit
            for r in rows:
                r.status = "running"
                await db.commit()
                try:
                    lit = infos.get(r.literature_id)
                    if lit is None:
                        raise ValueError("文献不存在或已删除")
                    # 多模型对比：给单篇提取限定耗时上限，避免慢/卡死模型占用过久，
                    # 使能正常响应的模型（如 qwen2.5:14b）快速产出，对比仍可拿到结果
                    timeout = float(getattr(settings, "SYN_MULTI_MODEL_TIMEOUT", 300))
                    pts = await asyncio.wait_for(
                        _extract_lit_points(r.model, lit), timeout=timeout,
                    )
                    r.points_json = pts
                    r.status = "done"
                    r.error = None
                except asyncio.TimeoutError:
                    r.status = "failed"
                    r.points_json = None
                    r.error = f"提取超时（超过 {timeout:.0f}s 上限）"
                except Exception as e:  # noqa: BLE001
                    r.status = "failed"
                    r.points_json = None
                    r.error = str(e)[:1900]
                await db.commit()
            # 全部完成后更新时间戳
            task.extracted_at = datetime.now(timezone.utc)
            task.status = "extracting"
            await db.commit()
        except Exception as e:  # noqa: BLE001
            logger.error(f"[Synthetic] 多模型提取任务失败: {e}", exc_info=True)


async def trigger_multi_extraction(db: AsyncSession, task_id: uuid.UUID,
                                   models: list[str]) -> dict:
    """对任务内文献按多个模型分别触发纯抽取（多模型对比）。

    - 结果存 synthetic_extraction，不写 data_point（不污染真实文献数据）。
    - existing 任务必须先完成参考 GT 生成。
    - 触发后在后台依次执行全部 (模型 × 文献) 组合。
    """
    task = await _get_task(db, task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.status not in ("ready", "assessed", "extracting"):
        raise ValueError(f"任务当前状态 {task.status}，无法触发提取")
    if task.literature_source == "existing" and not task.gt_json:
        raise ValueError("existing 任务需先生成参考基准(GT)后再进行多模型提取")
    if not task.literature_ids:
        raise ValueError("任务无文献，无法提取")

    models = list(dict.fromkeys(m for m in models if m))  # 去重去空
    if not models:
        raise ValueError("请至少选择一个提取模型")

    for lid_str in task.literature_ids:
        lit_id = uuid.UUID(lid_str)
        for m in models:
            row = (await db.execute(
                select(SyntheticExtraction).where(
                    SyntheticExtraction.task_id == task_id,
                    SyntheticExtraction.literature_id == lit_id,
                    SyntheticExtraction.model == m,
                )
            )).scalar_one_or_none()
            if row:
                row.status = "pending"
                row.points_json = None
                row.error = None
            else:
                db.add(SyntheticExtraction(
                    task_id=task_id, literature_id=lit_id, model=m, status="pending"
                ))

    task.models = models
    task.extractor_model = models[0]
    task.status = "extracting"
    task.extraction_started_at = datetime.now(timezone.utc)
    task.extracted_at = None
    await db.commit()

    tid = str(task.id)
    bg = asyncio.create_task(_run_multi_extraction(tid))
    _bg_multi_tasks.add(bg)
    bg.add_done_callback(_bg_multi_tasks.discard)

    return {
        "submitted": len(models) * len(task.literature_ids),
        "models": models,
        "literatures": len(task.literature_ids),
    }


async def compute_multi_assessment(db: AsyncSession, task_id: uuid.UUID) -> dict:
    """多模型对比评估：对每个完成模型各跑一次 assess_task，产出横向指标 + 逐篇对比。

    GT 取自 task.gt_json（合成=植入值；existing=参考模型产出）。结果为每个模型的
    提取点 vs 同一 GT 的比对。顶层 by_literature/summary 取首个已完成模型，保持与
    现有单模型前端渲染兼容；完整多模型结果放 report_json.multi_model。
    """
    task = await _get_task(db, task_id)
    if not task:
        raise ValueError("任务不存在")
    if not task.literature_ids or not task.gt_json:
        raise ValueError("任务缺少文献或 ground truth")
    if not task.models:
        raise ValueError("该任务未配置多模型对比，请先触发多模型提取")

    # 按模型分组读取提取点
    rows = (await db.execute(
        select(SyntheticExtraction).where(SyntheticExtraction.task_id == task_id)
    )).scalars().all()
    by_model_lit: dict[str, dict[str, list[dict]]] = {}
    done_cnt: dict[str, int] = {}
    lit_cnt: dict[str, int] = {}
    for r in rows:
        lit_cnt[r.model] = lit_cnt.get(r.model, 0) + 1
        if r.status == "done":
            done_cnt[r.model] = done_cnt.get(r.model, 0) + 1
        dm = by_model_lit.setdefault(r.model, {})
        dm[str(r.literature_id)] = r.points_json or []

    lit_meta: dict[str, dict] = {}
    lit_index: dict[str, str] = {}
    for i, lid_str in enumerate(task.literature_ids):
        key = f"lit{i}"
        lit_index[lid_str] = key
        lit = (await db.execute(
            select(Literature).where(Literature.id == uuid.UUID(lid_str))
        )).scalar_one_or_none()
        lit_meta[key] = {"id": lid_str, "title": lit.title if lit else f"文献{i+1}"}

    gt_by_lit = {f"lit{i}": pts for i, pts in enumerate(task.gt_json)}

    done_models = [m for m in task.models if done_cnt.get(m, 0) >= 1]
    if not done_models:
        pending_txt = ", ".join(
            f"{m}(done {done_cnt.get(m, 0)}/{lit_cnt.get(m, 0)})" for m in task.models
        )
        raise RuntimeError("没有已完成的模型提取结果可评估，当前模型完成情况：" + pending_txt)

    per_model_report: dict[str, dict] = {}
    for m in done_models:
        ex_by_lit = {
            key: by_model_lit[m].get(lit_id, [])
            for lit_id, key in lit_index.items()
        }
        per_model_report[m] = assess_task({
            "disease": task.disease,
            "gt_by_literature": gt_by_lit,
            "ex_by_literature": ex_by_lit,
            "lit_meta": lit_meta,
        })

    first = per_model_report[done_models[0]]

    # 横向指标
    comparison = []
    for m in done_models:
        s = per_model_report[m]["summary"]
        comparison.append({
            "model": m,
            "literatures_total": lit_cnt.get(m, 0),
            "literatures_done": done_cnt.get(m, 0),
            "clean_total": s["clean_total"],
            "clean_matched": s["clean_matched"],
            "clean_recall": s["clean_recall"],
            "value_exact_rate": s["value_exact_rate"],
            "noise_total": s["noise_total"],
            "noise_rejected": s["noise_rejected"],
            "noise_rejection_rate": s["noise_rejection_rate"],
            "field_accuracy": s["field_accuracy"],
        })

    # 逐篇：GT + 各模型提取点/命中
    multi_bl = []
    for i, row in enumerate(first["by_literature"]):
        models_info = {}
        for m in done_models:
            bl = per_model_report[m]["by_literature"][i]
            models_info[m] = {
                "extracted_points": bl["extracted_points"],
                "clean_total": bl["clean_total"],
                "clean_matched": bl["clean_matched"],
                "noise_total": bl["noise_total"],
                "noise_rejected": bl["noise_rejected"],
            }
        multi_bl.append({
            "literature_id": row["literature_id"],
            "title": row["title"],
            "gt_points": row["gt_points"],
            "models": models_info,
        })

    multi = {
        "models": done_models,
        "comparison": comparison,
        "by_literature": multi_bl,
    }
    report = dict(first)
    report["multi_model"] = multi
    task.report_json = report
    task.status = "assessed"
    task.extracted_at = datetime.now(timezone.utc)
    await db.commit()
    return report
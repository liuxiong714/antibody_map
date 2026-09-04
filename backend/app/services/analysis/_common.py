"""app.services.analysis 公共常量与辅助函数。

被 basic / meta / infectious_disease / spatial / equity_quality /
data_management / export 七个分析子模块共同导入（自 analysis_service.py
拆分而来）。常量与辅助函数语义与原 analysis_service.py 保持一致，统计计算
尽量复用 app.core.stats_engine 实现，不重复造数学公式。
"""


import logging
import math

from sqlalchemy import select

from app.core.stats_engine import (
    direct_standardize,
    gmc_ci,
    meta_proportion,
    weighted_rate_ci,
)
from app.core.term_normalizer import normalize_disease
from app.models.data_point import DataPoint
from app.models.literature import Literature

logger = logging.getLogger("uvicorn")


# ============================================================
# 标准人口（中国 2020 七普） / 疾病解读提示
# ============================================================

def _load_std_pop() -> dict:
    """加载中国 2020 七普标准人口构成（reference_data/china_pop_2020.json）。"""
    import json as _json
    import os as _os
    _p = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "core", "reference_data", "china_pop_2020.json"
    )
    with open(_p, encoding="utf-8") as _f:
        return _json.load(_f)


_CHINA_POP_2020 = _load_std_pop()
CHINA_POP_STD_VERSION = _CHINA_POP_2020["version"]
_STD_WEIGHT_BY_GROUP: dict[str, float] = {
    g["group"]: float(g["weight"]) for g in _CHINA_POP_2020["age_groups"]
}


def _load_disease_note(disease_key: str | None) -> str | None:
    """读取 reference_data/disease_notes.json 中某疾病的解读提示（无则 None）。"""
    import json as _json
    import os as _os
    _p = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "core", "reference_data", "disease_notes.json"
    )
    try:
        with open(_p, encoding="utf-8") as _f:
            data = _json.load(_f)
    except (OSError, ValueError):
        return None
    entry = data.get("notes", {}).get(disease_key or "")
    return (entry or {}).get("note") if isinstance(entry, dict) else None


# 服务层年龄段（AGE_GROUPS）→ 标准人口年龄组映射（权重聚合，因 15-59/≥60 为粗分组，
# 55-64 组整段计入 15-59，60-64 段归入 15-59 属近似，权重合计仍归一为 1）
_STD_BAND_MAP: dict[str, list[str]] = {
    "<1岁": ["0"],
    "1-4岁": ["1-4"],
    "5-14岁": ["5-14"],
    "15-59岁": ["15-24", "25-34", "35-44", "45-54", "55-64"],
    "≥60岁": ["65-74", "75-84", "85+"],
}


# WHO 免疫屏障阈值（阳性率百分比）
WHO_THRESHOLDS = {
    "measles": 95,
    "rubella": 95,
    "mumps": 90,
    "polio": 95,
    "diphtheria": 90,
    "tetanus": 90,
    "pertussis": 90,
    "hepatitis_b": 90,
    "hepatitis_a": 90,
    "influenza": 65,
    "covid19": 75,
    "meningitis": 85,
    "varicella": 85,
    "hfmd": 75,
    "rotavirus": 80,
}


# ============================================================
# 通用数据点查询
# ============================================================

def _build_base_query(disease, province, year_start, year_end, age_min, age_max,
                      data_type=None, review_status="approved", include_subgroups=False,
                      quality_grades: set[str] | None = None):
    """构建通用数据点查询（返回未执行的 sqlalchemy select 语句对象）。

    P1-1：默认只查主估计（estimate_type='primary'）避免重复计算，
    传 include_subgroups=True 可包含子估计。
    quality_grades: 可选，仅返回指定质量等级（如 {"A","B"}）的数据点；
    默认 None 不过滤。
    """
    query = select(DataPoint).where(DataPoint.review_status == review_status)
    # 排除软删除文献的数据点（LEFT JOIN 保留无文献的中性孤儿数据点）
    query = query.outerjoin(Literature, DataPoint.literature_id == Literature.id)
    query = query.where(Literature.deleted_at.is_(None))
    # P1-1：默认过滤主估计
    if not include_subgroups:
        query = query.where(DataPoint.estimate_type == "primary")

    if quality_grades:
        query = query.where(DataPoint.quality_grade.in_(list(quality_grades)))

    if disease:
        # 标准化疾病名称，数据库中的 disease 字段已统一为标准 key
        normalized = normalize_disease(disease)
        query = query.where(DataPoint.disease == normalized)
    if province:
        # 支持逗号分隔的多省份筛选（前端多选省份），如 "北京市,上海市,广东省"
        provinces = [p.strip() for p in province.split(",") if p.strip()]
        if len(provinces) == 1:
            query = query.where(DataPoint.province.ilike(f"%{provinces[0]}%"))
        else:
            query = query.where(DataPoint.province.in_(provinces))
    if year_start:
        query = query.where(DataPoint.collection_year >= year_start)
    if year_end:
        query = query.where(DataPoint.collection_year <= year_end)
    if age_min is not None:
        query = query.where(DataPoint.age_min >= age_min)
    if age_max is not None:
        query = query.where(DataPoint.age_max <= age_max)
    if data_type:
        query = query.where(DataPoint.data_type == data_type)

    return query


# ============================================================
# 单元格级汇总：加权阳性率 / GMC / Meta 合并
# ============================================================

def _calc_weighted_positivity(rows: list[DataPoint]) -> dict:
    """计算加权阳性率及其 95% CI（样本量加权 + 正态近似）。

    调用 stats_engine.weighted_rate_ci（样本量加权，保守正态近似，
    任一行 sample_size 缺失则剔除并计入 dropped）。
    返回 ``{weighted_positivity, ci_lower, ci_upper, total_sample}``（阳性率为百分数 0-100）；
    无有效数据时各字段为 None，total_sample 为 0。
    """
    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.value is not None]
    result = weighted_rate_ci(sp_rows)
    return {
        "weighted_positivity": result["weighted_positivity"],
        "ci_lower": result["ci_lower"],
        "ci_upper": result["ci_upper"],
        "total_sample": result["n_total"],
    }


def _calc_gmc(rows: list[DataPoint]) -> dict:
    """计算 GMC 几何均数及对数域 95% CI（样本量加权）。

    调用 stats_engine.gmc_ci：对同组多个 GMC 值（已计算好的几何均值，非原始滴度）
    取对数平均 gmc = exp(mean(ln v))，样本量作权重，CI 按 ln v 的标准误构建。
    返回 ``{gmc, ci_lower, ci_upper, n, n_total}``；无有效数据时各字段为 None。
    """
    gmc_rows = [r for r in rows if r.data_type == "gmc" and r.value is not None]
    res = gmc_ci(
        [r.value for r in gmc_rows],
        weights=[r.sample_size for r in gmc_rows],
    )
    return {
        "gmc": res["gmc"],
        "ci_lower": res["ci_lower"],
        "ci_upper": res["ci_upper"],
        "n": res["n"],
        "n_total": res["n_total"],
    }


def _meta_merge_cell(rows: list[DataPoint]) -> dict:
    """单元格内多文献血清阳性率的 Meta 合并（Freeman-Tukey + 随机/固定效应）。

    替换原"样本量加权一把梭"口径：同格（同年/同省/同年龄组）多篇文献的主估计
    作为研究单元调用 ``meta_proportion`` 合并。保留旧样本量加权值于
    ``rate_weighted_legacy``（@deprecated，仅用于与 meta 口径比对）。

    返回 ``{positivity, ci_lower, ci_upper, rate_weighted_legacy, total_sample, meta}``：
    - positivity / ci_lower / ci_upper: Meta 合并阳性率与 95% CI（0-100，主模型）；
    - rate_weighted_legacy: 旧样本量加权阳性率（@deprecated）；
    - total_sample: 有效研究样本量之和；
    - meta: {model, primary_model, I2, Q, Q_p, tau2, k, n_rep} 或 None（无有效研究）。
    无有效研究时阳性率字段为 None。
    """
    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.value is not None]

    # 旧口径：样本量加权阳性率（@deprecated，仅保留用于比对）
    legacy = weighted_rate_ci(sp_rows)

    studies = []
    total_sample = 0.0
    for r in sp_rows:
        if not r.sample_size:
            continue
        p = float(r.value) / 100.0 if float(r.value) > 1.0 else float(r.value)
        n = float(r.sample_size)
        if p < 0.0 or p > 1.0 or n <= 0:
            continue
        x = p * n
        total_sample += n
        lid = getattr(r, "literature_id", None)
        label = f"文献{lid}" if lid else f"研究{len(studies) + 1}"
        studies.append((x, n, label))

    meta = meta_proportion(studies) if studies else meta_proportion([])
    pooled = meta.get("pooled") or {}

    meta_summary = None
    if pooled.get("k"):
        meta_summary = {
            "model": pooled.get("model"),
            "primary_model": meta.get("primary_model"),
            "I2": pooled.get("I2"),
            "Q": pooled.get("Q"),
            "Q_p": pooled.get("Q_p"),
            "tau2": pooled.get("tau2"),
            "k": pooled.get("k"),
            "n_rep": pooled.get("n_rep"),
        }

    return {
        "positivity": pooled.get("rate"),
        "ci_lower": pooled.get("ci_lower"),
        "ci_upper": pooled.get("ci_upper"),
        "rate_weighted_legacy": legacy["weighted_positivity"],  # @deprecated
        "total_sample": round(total_sample, 0),
        "meta": meta_summary,
    }


def _compute_province_asr(group_rows: list[DataPoint]) -> dict:
    """计算省份年龄标准化阳性率（ASR，直接法，七普标准人口）。

    - 精确落在单一标准年龄段（如 5-14 岁）的数据点 → 按该段用 _meta_merge_cell
      Meta 合并，得到该段阳性率与样本量；
    - 跨多段的宽年龄段（如 0-14 岁）→ 按七普标准人口权重（_age_band_split）
      拆分叠加到各重叠标准段，避免数据点被静默丢弃；
    - 再把标准人口权重聚合到相同年龄段（_STD_BAND_MAP），调用 direct_standardize。
    有效年龄段 < 3 组时 asr=None（note 注明）。
    """
    # 精确单段：label -> 归属数据点（沿用 Meta 合并）
    band_exact: dict[str, list[DataPoint]] = {}
    # 宽段拆分贡献：label -> {"n": 加权样本量, "x": 加权阳性数}
    wide_contrib: dict[str, dict[str, float]] = {}
    for r in group_rows:
        if r.data_type != "seroprevalence" or r.value is None:
            continue
        p = float(r.value) / 100.0 if float(r.value) > 1.0 else float(r.value)
        if p < 0.0 or p > 1.0 or not r.sample_size or r.sample_size <= 0:
            continue
        n = float(r.sample_size)
        splits = _age_band_split(r.age_min, r.age_max)
        if not splits:
            continue
        if len(splits) == 1:
            band_exact.setdefault(splits[0][1], []).append(r)
        else:
            for w, label in splits:
                acc = wide_contrib.setdefault(label, {"n": 0.0, "x": 0.0})
                acc["n"] += n * w
                acc["x"] += p * n * w

    strata: list[tuple[str, float, float]] = []
    std_bands: list[dict] = []
    for label in set(list(band_exact.keys()) + list(wide_contrib.keys())):
        std_groups = _STD_BAND_MAP.get(label)
        if not std_groups:
            continue
        n = 0.0
        x = 0.0
        if label in band_exact:
            mi = _meta_merge_cell(band_exact[label])
            mp = mi.get("positivity")
            mt = mi.get("total_sample")
            if mp is not None and mt:
                n += float(mt)
                x += (mp / 100.0 if mp > 1.0 else mp) * float(mt)
        if label in wide_contrib:
            n += wide_contrib[label]["n"]
            x += wide_contrib[label]["x"]
        if n <= 0:
            continue
        rate = x / n
        w = sum(_STD_WEIGHT_BY_GROUP.get(g, 0.0) for g in std_groups)
        if w <= 0:
            continue
        strata.append((label, rate, float(n)))
        std_bands.append({"group": label, "weight": w, "range": [0, 200]})

    res = direct_standardize(strata, standard=std_bands) if strata else {
        "crude": None, "asr": None, "asr_ci_lower": None, "asr_ci_upper": None,
        "se": None, "n_strata": 0, "used_groups": [], "note": "无有效年龄分层数据",
    }
    res["standard_version"] = CHINA_POP_STD_VERSION
    return res


# ============================================================
# 年龄段
# ============================================================

AGE_GROUPS = [
    ("<1岁", 0, 0),
    ("1-4岁", 1, 4),
    ("5-14岁", 5, 14),
    ("15-59岁", 15, 59),
    ("≥60岁", 60, 200),
]


def _age_band_split(age_min, age_max):
    """将数据点年龄范围映射为标准年龄段分布，返回 [(权重, 标签)]。

    - 年龄范围完整落在某一标准段内 → 仅返回该段（权重 1.0）；
    - 跨多个标准段（如 0-14 岁跨 1-4/5-14）→ 按七普标准人口权重拆分到各重叠段，
      权重归一化为 1，避免宽年龄段数据点被静默丢弃；
    - 无法命中任何标准段（age_min 缺失或范围越界）→ 返回空列表。
    """
    if age_min is None:
        return []
    band_min = float(age_min)
    band_max = float(age_max) if age_max is not None else float("inf")
    hits = []
    for label, lo, hi in AGE_GROUPS:
        # 标准段 [lo, hi] 与数据点区间 [band_min, band_max] 有交集
        if band_min <= hi and band_max >= lo:
            w = sum(_STD_WEIGHT_BY_GROUP.get(g, 0.0) for g in _STD_BAND_MAP[label])
            if w > 0:
                hits.append((w, label))
    if not hits:
        return []
    total = sum(w for w, _ in hits)
    return [(w / total, label) for w, label in hits]


def _get_age_group_label(age_min, age_max):
    """根据年龄范围返回标准年龄段标签（不再静默丢弃跨组数据）。

    年龄范围完整落在某标准段 → 返回该段；跨多个标准段（如 0-14 岁）→
    返回人口权重最大的代表段；age_min 缺失 → None；无法命中任何标准段 → "其他"。
    """
    if age_min is None:
        return None
    splits = _age_band_split(age_min, age_max)
    if not splits:
        return "其他"
    if len(splits) == 1:
        return splits[0][1]
    return max(splits, key=lambda it: it[0])[1]


# ============================================================
# 免疫屏障状态判定
# ============================================================

def _barrier_status_from_rate(rate: float | None, hit_target: float | None) -> str:
    """根据阳性率与 HIT 阈值判定免疫屏障状态。

    返回值与前端 STATUS_CONFIG 保持一致：
      established / borderline / insufficient / undetermined
    """
    if rate is None or hit_target is None:
        return "undetermined"
    if rate >= hit_target:
        return "established"
    if rate >= hit_target - 10:
        return "borderline"
    return "insufficient"


def _barrier_status_with_message(
    rate: float | None,
    hit_target: float | None,
    hit_source: str,
) -> tuple[str, str]:
    """总体状态判定 + 文案。"""
    source_label = {"mle_foi": "FOI 估算", "who": "WHO 建议", "literature_r0": "文献 R0", "none": "无"}.get(
        hit_source, hit_source
    )
    if hit_target is not None and rate is not None:
        if rate >= hit_target:
            return (
                "established",
                f"该疾病群体抗体阳性率（{rate}%）已达到免疫屏障阈值（{hit_target}%，来源：{source_label}），"
                f"免疫屏障已建立。",
            )
        if rate >= hit_target - 10:
            return (
                "borderline",
                f"该疾病群体抗体阳性率（{rate}%）接近但未完全达到免疫屏障阈值（{hit_target}%，来源：{source_label}），"
                f"建议加强重点人群免疫。",
            )
        return (
            "insufficient",
            f"该疾病群体抗体阳性率（{rate}%）低于免疫屏障阈值（{hit_target}%，来源：{source_label}），"
            f"免疫屏障不足，建议加强免疫接种。",
        )
    return ("no_data", "暂无足够数据或对应的阈值进行对比评估。")


# ============================================================
# 中国 34 省级行政区基准列表
# ============================================================

CHINA_PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
    "台湾", "香港", "澳门",
]


# ============================================================
# FOI / R0 / HIT
# ============================================================

DEFAULT_LIFE_EXPECTANCY = 75.0

# 按疾病预设的参考 R0（Anderson & May 经典值 + 文献典型范围）
# 用于计算 HIT = 1 - 1/R0，并作为 FOI 合理性校验的先验
R0_REFERENCE: dict[str, tuple[float, float]] = {
    # disease: (R0_typical, R0_range_low..high)
    "measles":     (15.0, 12.0, 18.0),   # 麻疹：极强传染性
    "mumps":        (5.5,  4.0,  7.0),   # 腮腺炎
    "rubella":      (6.0,  5.0,  7.0),   # 风疹
    "pertussis":   (15.0, 12.0, 17.0),   # 百日咳
    "diphtheria":   (6.5,  4.0,  8.0),   # 白喉
    "polio":        (5.0,  4.0,  6.0),   # 脊髓灰质炎
    "smallpox":     (5.0,  3.5,  6.0),   # 天花（参考）
    "hepatitis_b":  (4.0,  2.0,  6.0),   # 乙肝
    "hepatitis_a":  (3.5,  2.0,  5.0),   # 甲肝
    "varicella":    (6.5,  5.0,  9.0),   # 水痘
    "influenza":    (2.5,  1.4,  3.5),   # 季节性流感
    "covid19":      (3.0,  2.0,  5.0),   # 新冠（原始株）
    "meningitis":   (1.5,  1.1,  2.0),   # 流脑
    "hfmd":         (3.0,  2.0,  4.5),   # 手足口
    "rotavirus":    (3.0,  2.0,  4.0),   # 轮状病毒
}


def _calc_foi_from_sp(seroprevalence: float, age_mid: float) -> float | None:
    """催化模型（Catalitic Model）：SP(a) = 1 - e^(-λ a) → λ = -ln(1 - SP) / a

    边界处理：
    - SP = 0 → λ = 0
    - SP ≥ 1 → 返回 None（数学上 ln(0) 无解，视为超饱和）
    - age_mid ≤ 0 → 返回 None（分母无效）
    """
    if seroprevalence <= 0 or age_mid <= 0:
        result = 0.0 if seroprevalence <= 0 else None
        logger.debug(f"[FOI] _calc_foi_from_sp 边界返回: SP={seroprevalence}, age_mid={age_mid} → foi={result}")
        return result
    sp_clamped = min(seroprevalence / 100.0, 0.9999)  # 转成比例（0-1），避免 -ln(0)
    if sp_clamped <= 0:
        logger.debug(f"[FOI] _calc_foi_from_sp SP_clamped≤0: SP={seroprevalence} → foi=0.0")
        return 0.0
    foi = -math.log(1.0 - sp_clamped) / age_mid
    result = round(foi, 6)
    logger.debug(f"[FOI] _calc_foi_from_sp: SP={seroprevalence}%, age_mid={age_mid}, sp_ratio={sp_clamped:.6f} → foi={result}/年")
    return result


def _midpoint_age(age_min: int | None, age_max: int | None) -> float | None:
    """计算年龄组中点年龄，用于催化模型 FOI 估算。

    - 区间 [a, b] → (a + b) / 2
    - 只有 age_min → age_min + 2.5（经验半宽）
    - 只有 age_max → age_max / 2
    - 都没有 → None
    """
    if age_min is not None and age_max is not None:
        if age_min < 0 or age_max < age_min:
            logger.warning(f"[FOI] _midpoint_age 无效年龄范围: age_min={age_min}, age_max={age_max} → None")
            return None
        mid = (age_min + age_max) / 2.0
        logger.debug(f"[FOI] _midpoint_age: age_min={age_min}, age_max={age_max} → mid={mid}")
        return mid
    if age_min is not None:
        mid = float(age_min) + 2.5
        logger.debug(f"[FOI] _midpoint_age(仅age_min): age_min={age_min} → mid={mid} (经验半宽+2.5)")
        return mid
    if age_max is not None:
        mid = age_max / 2.0
        logger.debug(f"[FOI] _midpoint_age(仅age_max): age_max={age_max} → mid={mid}")
        return mid
    logger.debug("[FOI] _midpoint_age: age_min和age_max均为None → None")
    return None


def _calc_hit_from_r0(r0: float) -> float:
    """群体免疫阈值 HIT = 1 - 1/R0，转成百分比（0-100）。"""
    if r0 is None or r0 <= 1.0:
        logger.debug(f"[FOI] _calc_hit_from_r0: r0={r0} (≤1或None) → HIT=0.0%")
        return 0.0
    hit = round((1.0 - 1.0 / r0) * 100.0, 2)
    logger.debug(f"[FOI] _calc_hit_from_r0: r0={r0} → HIT={hit}%")
    return hit


def _calc_r0_from_foi(foi_avg: float, life_exp: float = DEFAULT_LIFE_EXPECTANCY) -> float | None:
    """从平均 FOI 反推 R0 ≈ λ × L（Catalitic 模型：λ ≈ R0 / L → R0 ≈ λ·L）。

    仅对地方性疾病（地方性儿童期感染）合理；
    新冠/流感等非终身免疫疾病此公式有偏差，结果会在注释中标记。
    """
    if foi_avg is None or foi_avg <= 0:
        logger.debug(f"[FOI] _calc_r0_from_foi: foi_avg={foi_avg} (≤0或None) → R0=None")
        return None
    r0 = round(foi_avg * life_exp, 3)
    logger.info(f"[FOI] _calc_r0_from_foi: foi_avg={foi_avg}/年, L={life_exp}年 → R0≈{r0}")
    return r0


# 非"地方性 + 终生免疫"疾病：R0 = λ·L 理论不适用，默认不输出 r0_to_hit，
# 改用文献 R0（R0_REFERENCE 表）计算 HIT，标 hit_source="literature_r0"。
NON_ENDEMIC_LIFELONG = {"covid19", "influenza", "hfmd", "rotavirus", "pertussis"}

# R0 = λ·L 假设说明（响应 meta / 报告模板引用）
R0_ASSUMPTION_NOTE = "基于地方性流行+终生免疫假设，对新冠/流感/手足口等不适用"


def _build_catalytic_records(rows: list[DataPoint]) -> list[tuple[float, int, int]]:
    """从已审核 seroprevalence 数据点构建催化模型输入 [(age_mid, x, n), ...]。

    value 为百分数（>1）或 0-1 比例均可；样本量加权阳性数 x = round(n·p)。
    无样本量 / 不可推算年龄中点 / 中点≤0 的记录剔除。
    """
    records: list[tuple[float, int, int]] = []
    for r in rows:
        if r.value is None or r.sample_size is None:
            continue
        mid = _midpoint_age(r.age_min, r.age_max)
        if mid is None or mid <= 0:
            continue
        ss = int(r.sample_size)
        if ss <= 0:
            continue
        p = float(r.value)
        if p > 1.0:
            p /= 100.0
        p = min(max(p, 0.0), 1.0)
        records.append((float(mid), round(p * ss), ss))
    return records


def _catalytic_r0_hit(catalytic: dict, dis_key: str | None, life_exp: float = DEFAULT_LIFE_EXPECTANCY,
                      mu_fixed: float | None = None) -> dict:
    """按理论修正从催化模型结果计算 R0 / HIT 目标与来源标签。

    - R0 = λ·L 对 recommended_model == M1_constant 且疾病满足
      「地方性 + 终生免疫」（不在 NON_ENDEMIC_LIFELONG）时计算；
      结果填入 ``r0_to_hit``，来源标 ``mle_foi``。
    - 显式指定血清转阴率（``mu_fixed>0``）时，即便推荐模型为 M2（μ 固定），
      仍用其 λ 按 λ·L 反推 R0/HIT——用户显式假设驱动重算。
    - 其余情况（M2/M3 自由拟合或非地方性/非终生免疫疾病）：默认不输出 r0_to_hit
      （置 None），改用文献 R0 计算 HIT，来源标 ``literature_r0``。
    - ``foi_avg`` 恒为推荐模型的平均 FOI（/年）。
    - ``r0_assumption_note``：当 R0 = λ·L 参与计算时给出固定说明文案。
    """
    rec_name = catalytic.get("recommended_model")
    rec_params = catalytic.get("recommended_params") or {}
    foi_avg = catalytic.get("recommended_foi_avg")
    r0_ref = R0_REFERENCE.get(dis_key) if dis_key else None
    literature_hit = _calc_hit_from_r0(r0_ref[0]) if r0_ref else None

    endemic_lifelong = dis_key not in NON_ENDEMIC_LIFELONG
    explicit_seroreversion = mu_fixed is not None and mu_fixed > 0
    r0_to_hit: float | None = None
    if endemic_lifelong and (rec_name == "M1_constant" or explicit_seroreversion):
        lam = rec_params.get("lambda")
        if lam is not None and lam > 0:
            r0_to_hit = round(float(lam) * life_exp, 3)

    if r0_to_hit is not None and r0_to_hit > 1.0:
        hit_source = "mle_foi"
    elif literature_hit is not None:
        hit_source = "literature_r0"
    else:
        hit_source = None

    r0_assumption_note = R0_ASSUMPTION_NOTE if (
        r0_to_hit is not None or rec_name == "M1_constant" or explicit_seroreversion
    ) else None

    return {
        "foi_avg": foi_avg,
        "r0_to_hit": r0_to_hit,
        "hit_source": hit_source,
        "literature_hit": literature_hit,
        "r0_assumption_note": r0_assumption_note,
    }


def _resolve_hit_target(
    foi_hit: float | None,
    who_threshold: float | None,
    literature_hit: float | None,
    dis_key: str | None,
    hit_source_override: str | None = None,
) -> tuple[float | None, str]:
    """HIT 阈值解析：优先级链 FOI 估算 > WHO > 文献 R0（保持不变）。

    理论修正：对非「地方性 + 终生免疫」疾病（covid19/influenza/hfmd/rotavirus/
    pertussis），上游已把 r0_to_hit 置 None → foi_hit 为 None，因此本函数自然走
    WHO > 文献 R0 链，来源标 who / literature_r0，不再出现错误的 FOI 反推 HIT。
    返回 (hit_target, hit_source)；hit_source ∈ mle_foi/who/literature_r0/none。
    """
    # hit_source_override：显式指定优先使用的阈值来源（foi/who/literature）
    # 覆盖源无值时回落到正常优先级链
    if hit_source_override is not None:
        if hit_source_override == "foi" and foi_hit is not None:
            return foi_hit, "mle_foi"
        if hit_source_override == "who" and who_threshold is not None:
            return who_threshold, "who"
        if hit_source_override in ("literature", "literature_r0") and literature_hit is not None:
            return literature_hit, "literature_r0"
    if foi_hit is not None:
        return foi_hit, "mle_foi"
    if who_threshold is not None:
        return who_threshold, "who"
    if literature_hit is not None:
        return literature_hit, "literature_r0"
    return None, "none"


# ============================================================
# 疫苗效果 (VE) 与接种率 (Coverage)
# ============================================================

# ---- 国家免疫规划 (NIP) 典型接种率（按疾病，参考 2020-2024 年 CDC/WHO 报告）
# 单位：%，值为全国估计平均值
NIP_COVERAGE_REFERENCE: dict[str, dict[str, float]] = {
    # disease: {province: coverage_percent, "__national__": fallback}
    "measles": {
        "__national__": 95.0,
        "北京": 97.0, "上海": 97.5, "江苏": 96.5, "浙江": 96.0, "广东": 95.5,
        "河南": 94.5, "山东": 95.5, "河北": 94.0, "四川": 93.5, "湖北": 94.0,
    },
    "mumps": {"__national__": 90.0},
    "rubella": {"__national__": 92.0},
    "pertussis": {"__national__": 95.0},
    "diphtheria": {"__national__": 95.0},
    "polio": {"__national__": 96.0},
    "hepatitis_b": {"__national__": 95.0},
    "hepatitis_a": {"__national__": 70.0},  # 非强制，部分省
    "varicella": {"__national__": 55.0},    # 二类苗
    "influenza": {"__national__": 3.5},     # 成人低覆盖
    "covid19": {"__national__": 89.0},
    "meningitis": {"__national__": 75.0},
    "hfmd": {"__national__": 35.0},         # EV71 疫苗
    "rotavirus": {"__national__": 30.0},    # 口服轮状
}


def _split_vax_unvax(rows: list) -> tuple[list, list]:
    """根据 DataPoint.population 中的关键词，拆分为「已接种组」和「未接种组」。

    识别关键词：
    - 已接种: 已接种、接种过、疫苗接种、免疫史阳性、vaccinated、immunized
    - 未接种: 未接种、无免疫史、未免疫、未接种疫苗、unvaccinated、naive

    未命中关键词的数据点返回在 unclassified 列表（不参与 VE 计算但仍统计）。
    """
    _VAXXED_KW = ("已接种", "接种过", "疫苗接种", "免疫史阳性", "vaccinated", "immunized",
                  "全程接种", "完成接种", "≥1剂", "1剂及以上")
    _UNVAXXED_KW = ("未接种", "无免疫史", "未免疫", "未接种疫苗", "unvaccinated", "naive",
                    "接种史阴性", "未注射疫苗")
    # 拆分中英文关键词：中文是独立词，英文可能相互包含（unvaccinated ⊃ vaccinated）
    _zh_vax = tuple(k for k in _VAXXED_KW if not all(ord(c) < 128 for c in k))
    _zh_unvax = tuple(k for k in _UNVAXXED_KW if not all(ord(c) < 128 for c in k))

    vaxxed, unvaxxed = [], []
    unclassified_count = 0
    for r in rows:
        pop_orig = getattr(r, "population", None) or ""
        pop = pop_orig.lower()
        dis_name = getattr(r, "disease", None) or ""
        kw_str = f"{pop} {dis_name}"

        # 中文关键词冲突检测：若同时出现「已接种类」和「未接种类」→ 不分类
        zh_v = any(k in pop_orig for k in _zh_vax)
        zh_u = any(k in pop_orig for k in _zh_unvax)
        if zh_v and zh_u:
            unclassified_count += 1
            logger.debug(f"[VE] _split_vax_unvax 冲突跳过: population='{pop_orig}' (同时含已/未接种关键词)")
            continue  # 冲突：如「已接种与未接种人群对比」

        # 英文/其余逻辑：先判 unvaxxed
        u_hit = zh_u or any(k.lower() in kw_str for k in _UNVAXXED_KW)
        if u_hit:
            unvaxxed.append(r)
            continue

        v_hit = zh_v
        if not v_hit:
            for k in _VAXXED_KW:
                kl = k.lower()
                if kl not in kw_str:
                    continue
                # 对 vaccinated/immunized 做前缀保护：前面是 'un'/'non' 时不算
                if all(ord(c) < 128 for c in k) and k.endswith(("vaccinated", "immunized")):
                    idx = kw_str.index(kl)
                    before = kw_str[max(0, idx - 4): idx]
                    if before.endswith("un") or before.endswith("non"):
                        continue
                v_hit = True
                break
        if v_hit:
            vaxxed.append(r)
        else:
            unclassified_count += 1
            logger.debug(f"[VE] _split_vax_unvax 未分类: population='{pop_orig}' (无匹配关键词)")

    logger.info(
        f"[VE] _split_vax_unvax 完成: 总数={len(rows)}, "
        f"已接种={len(vaxxed)}, 未接种={len(unvaxxed)}, 未分类={unclassified_count}"
    )
    return vaxxed, unvaxxed


def _calc_ve_from_sp(sp_vax: float, sp_unvax: float) -> float | None:
    """疫苗保护性效果（抗体阳性率维度）：VE_sero = 1 - SP_vax / SP_unvax。

    注意：这是「VE against seroconversion/infection」的近似值；
    如果 SP_vax > SP_unvax（接种组阳性反而更高，因疫苗诱导抗体），
    说明不是保护性抗体阳转率维度，需返回 None。
    """
    if sp_unvax is None or sp_vax is None or sp_unvax <= 0:
        logger.info(f"[VE] _calc_ve_from_sp 返回None: sp_vax={sp_vax}, sp_unvax={sp_unvax} (参数无效或sp_unvax≤0)")
        return None
    ratio = sp_vax / sp_unvax
    if ratio >= 1.0:
        # 接种组阳性率 >= 未接种组：通常是疫苗诱导了抗体（这是期望的），
        # 但该公式不能用于计算「保护性 VE」，返回 None 并标注
        logger.info(f"[VE] _calc_ve_from_sp 返回None: sp_vax={sp_vax}% ≥ sp_unvax={sp_unvax}% (ratio={ratio:.4f}≥1, 疫苗诱导抗体)")
        return None
    ve = round((1.0 - ratio) * 100.0, 2)  # 转 %
    logger.info(f"[VE] _calc_ve_from_sp: sp_vax={sp_vax}%, sp_unvax={sp_unvax}%, ratio={ratio:.4f} → VE={ve}%")
    return ve


def _get_reference_coverage(disease: str, province: str | None) -> float | None:
    """查 NIP 参考接种率：优先省级别，其次国家级。"""
    if not disease:
        return None
    dis_map = NIP_COVERAGE_REFERENCE.get(disease, {})
    if province and province in dis_map:
        cov = dis_map[province]
        logger.debug(f"[VE] _get_reference_coverage: disease={disease}, province={province} → 省级接种率={cov}%")
        return cov
    cov = dis_map.get("__national__")
    logger.debug(f"[VE] _get_reference_coverage: disease={disease}, province={province} → 国家级接种率={cov}%")
    return cov


def _implied_coverage_from_hit(
    overall_sp: float, hit_target: float,
) -> float | None:
    """粗略反推接种率：若假设 HIT = herd immunity threshold = coverage × VE_induced，
    则 coverage_implied ≈ overall_sp / hit_target（当整体 SP 被视为疫苗诱导+自然感染的混合时，
    此近似偏保守，仅用于给出参考值）。"""
    if hit_target is None or hit_target <= 0 or overall_sp is None:
        logger.debug(f"[VE] _implied_coverage_from_hit 返回None: overall_sp={overall_sp}, hit_target={hit_target}")
        return None
    impl = min(100.0, round(overall_sp / hit_target * 100.0, 2))
    logger.info(f"[VE] _implied_coverage_from_hit: overall_sp={overall_sp}%, hit_target={hit_target}% → implied_coverage={impl}%")
    return impl


# ============================================================
# 空间权重（省级邻接）
# ============================================================

def _load_province_adjacency() -> dict:
    """加载 34 省级 queen 邻接矩阵（binary）。"""
    import json as _json
    import os as _os
    _p = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "core", "reference_data",
        "china_province_adjacency.json",
    )
    with open(_p, encoding="utf-8") as _f:
        return _json.load(_f)


def _build_province_weights(adjacency: dict, data_provinces: list[str]):
    """从 binary 邻接构建仅含有效省份的对称行标准化权重 W。

    - 邻接矩阵以 binary（对称）存储；
    - 缺数省份从 W 中删去行列（邻接列表同步过滤）；
    - 对称化（binary 本身对称，此处兜底）后行标准化。
    """
    from libpysal.weights import W

    id_set = set(data_provinces)
    neighbors = {
        p: [n for n in adjacency.get(p, []) if n in id_set]
        for p in data_provinces
    }
    w = W(neighbors)
    w.symmetrize()
    w.transform = "r"
    return w
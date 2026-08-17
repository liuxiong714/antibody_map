import logging
import math
from datetime import date
from typing import Optional

import scipy.stats as sps
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.core.term_normalizer import normalize_disease, normalize_province
from app.core.methodology import build_methodology_note
from app.core.stats import (
    geometric_mean_with_ci,
    weighted_proportion_with_ci,
    weighted_linear_trend,
    gini,
    coefficient_of_variation,
    reliability_grade,
    lowess,
    inverse_variance_meta,
)
from app.core.stats_engine import (
    gmc_ci,
    weighted_rate_ci,
    fit_age_curve,
    foi_from_curve,
    meta_proportion,
    fit_catalytic_models,
    cochran_armitage_trend,
    two_proportion_test,
    direct_standardize,
    morans_i,
    g_star,
    classify_hotspot_cluster,
    birth_cohort_analysis,
)
from app.core.goal_thresholds import GOAL_THRESHOLDS

logger = logging.getLogger("uvicorn")

# 中国2020年七普标准人口（用于年龄标准化率 ASR）
def _load_std_pop() -> dict:
    import json as _json
    import os as _os
    _p = _os.path.join(
        _os.path.dirname(__file__), "..", "core", "reference_data", "china_pop_2020.json"
    )
    with open(_p, "r", encoding="utf-8") as _f:
        return _json.load(_f)


_CHINA_POP_2020 = _load_std_pop()
CHINA_POP_STD_VERSION = _CHINA_POP_2020["version"]
_STD_WEIGHT_BY_GROUP: dict[str, float] = {
    g["group"]: float(g["weight"]) for g in _CHINA_POP_2020["age_groups"]
}


def _load_disease_note(disease_key: Optional[str]) -> Optional[str]:
    """读取 reference_data/disease_notes.json 中某疾病的解读提示（无则 None）。"""
    import json as _json
    import os as _os
    _p = _os.path.join(
        _os.path.dirname(__file__), "..", "core", "reference_data", "disease_notes.json"
    )
    try:
        with open(_p, "r", encoding="utf-8") as _f:
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


def _build_base_query(disease, province, year_start, year_end, age_min, age_max,
                      data_type=None, review_status="approved", include_subgroups=False,
                      quality_grades: Optional[set[str]] = None):
    """构建通用数据点查询。

    P1-1：默认只查主估计（estimate_type='primary'）避免重复计算，
    传 include_subgroups=True 可包含子估计。
    quality_grades: 可选，仅返回指定质量等级（如 {"A","B"}）的数据点；
    默认 None 不过滤。
    """
    query = select(DataPoint).where(DataPoint.review_status == review_status)
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


async def get_trend(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    data_type: Optional[str] = None,
) -> dict:
    """逐年趋势分析。

    返回 ``{"trend": [...], "trend_significance": {...}}``：
    - trend: 逐年聚合，含 Meta 合并阳性率（Freeman-Tukey 随机/固定效应 + 95% CI）
      与 GMC（几何均数 + 对数域 95% CI）；旧样本量加权值保留于 rate_weighted_legacy（@deprecated）；
    - trend_significance: 对逐年加权阳性率做加权线性回归（stats.weighted_linear_trend，
      权重 = 各年总样本量）；少于 2 个有效年份时为 None。
    """
    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max, data_type)
    result = await db.execute(query)
    rows = result.scalars().all()

    year_groups: dict[int, list[DataPoint]] = {}
    for r in rows:
        if r.collection_year is None:
            continue
        y = r.collection_year
        if y not in year_groups:
            year_groups[y] = []
        year_groups[y].append(r)

    trend = []
    for year in sorted(year_groups.keys()):
        group_rows = year_groups[year]
        meta_info = _meta_merge_cell(group_rows)
        gmc_res = _calc_gmc(group_rows)

        trend.append({
            "year": year,
            "weighted_positivity": meta_info["positivity"],
            "positivity_ci_lower": meta_info["ci_lower"],
            "positivity_ci_upper": meta_info["ci_upper"],
            "rate_weighted_legacy": meta_info["rate_weighted_legacy"],  # @deprecated
            "meta": meta_info["meta"],
            "avg_gmc": gmc_res["gmc"],
            "gmc_ci_lower": gmc_res["ci_lower"],
            "gmc_ci_upper": gmc_res["ci_upper"],
            "total_sample": meta_info["total_sample"],
            "point_count": len(group_rows),
            "ci_meta": {
                "positivity_method": "meta_ft" if meta_info["meta"] else "normal_approx",
                "positivity_model": meta_info["meta"]["model"] if meta_info["meta"] else None,
                "positivity_I2": meta_info["meta"]["I2"] if meta_info["meta"] else None,
                "positivity_n": meta_info["total_sample"],
                "gmc_method": "lognormal",
                "gmc_n": gmc_res["n_total"],
            },
        })

    # 趋势显著性：对逐年加权阳性率做加权线性回归（权重 = 各年总样本量）
    trend_significance = None
    pts = [(d["year"], d["weighted_positivity"], d["total_sample"]) for d in trend if d["weighted_positivity"] is not None]
    if len(pts) >= 2:
        years = [float(t[0]) for t in pts]
        vals = [t[1] for t in pts]
        weights = [float(t[2]) if t[2] else 1.0 for t in pts]
        trend_significance = weighted_linear_trend(years, vals, weights)

    # Cochran-Armitage 趋势检验
    trend_test = None
    if len(pts) >= 3:
        ca_groups = [(d["year"], round(d["weighted_positivity"] * d["total_sample"] / 100), d["total_sample"]) for d in trend if d["weighted_positivity"] is not None and d["total_sample"]]
        trend_test = cochran_armitage_trend(ca_groups)

    return {"trend": trend, "trend_significance": trend_significance, "trend_test": trend_test}


def _compute_province_asr(group_rows: list[DataPoint]) -> dict:
    """计算省份年龄标准化阳性率（ASR，直接法，七普标准人口）。

    将省内容格数据按年龄段（_get_age_group_label）聚合，得到各年龄段率与样本量，
    再把标准人口权重聚合到相同年龄段（_STD_BAND_MAP），调用 direct_standardize。
    有效年龄段 < 3 组时 asr=None（note 注明）。
    """
    band_map: dict[str, list[DataPoint]] = {}
    for r in group_rows:
        label = _get_age_group_label(r.age_min, r.age_max) or "其他"
        if label not in band_map:
            band_map[label] = []
        band_map[label].append(r)

    strata: list[tuple[str, float, float]] = []
    std_bands: list[dict] = []
    for label, rows_ in band_map.items():
        std_groups = _STD_BAND_MAP.get(label)
        if not std_groups:
            continue
        mi = _meta_merge_cell(rows_)
        rate = mi["positivity"]
        n = mi["total_sample"]
        if rate is None or not n or n <= 0:
            continue
        rate = rate / 100.0 if rate > 1.0 else rate
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


async def get_region_compare(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    data_type: Optional[str] = None,
) -> dict:
    """区域对比分析

    同省多篇文献的主估计做 Meta 合并（Freeman-Tukey 随机/固定效应 + 95% CI），
    替代原样本量加权口径；旧加权值保留于 rate_weighted_legacy（@deprecated）。
    各省级联输出 asr 字段；指定恰好两省时返回 comparison_test（RD/RR 两样本率检验）。
    """
    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max, data_type)
    result = await db.execute(query)
    rows = result.scalars().all()

    province_map: dict[str, list[DataPoint]] = {}
    for r in rows:
        for p in (r.province or "").split(";"):
            p = p.strip()
            if not p:
                p = "未知"
            if p not in province_map:
                province_map[p] = []
            province_map[p].append(r)

    results = []
    for prov, group_rows in province_map.items():
        meta_info = _meta_merge_cell(group_rows)
        gmc_res = _calc_gmc(group_rows)
        asr_res = _compute_province_asr(group_rows)

        results.append({
            "province": prov,
            "avg_positivity": meta_info["positivity"],
            "positivity_ci_lower": meta_info["ci_lower"],
            "positivity_ci_upper": meta_info["ci_upper"],
            "rate_weighted_legacy": meta_info["rate_weighted_legacy"],  # @deprecated
            "meta": meta_info["meta"],
            "avg_gmc": gmc_res["gmc"],
            "gmc_ci_lower": gmc_res["ci_lower"],
            "gmc_ci_upper": gmc_res["ci_upper"],
            "point_count": len(group_rows),
            "total_samples": meta_info["total_sample"],
            "asr": asr_res["asr"],
            "asr_ci_lower": asr_res["asr_ci_lower"],
            "asr_ci_upper": asr_res["asr_ci_upper"],
            "crude_rate": asr_res["crude"],
            "asr_meta": {
                "standard_version": asr_res["standard_version"],
                "n_strata": asr_res["n_strata"],
                "used_groups": asr_res["used_groups"],
                "note": asr_res["note"],
            },
            "ci_meta": {
                "positivity_method": "meta_ft" if meta_info["meta"] else "normal_approx",
                "positivity_model": meta_info["meta"]["model"] if meta_info["meta"] else None,
                "positivity_I2": meta_info["meta"]["I2"] if meta_info["meta"] else None,
                "positivity_n": meta_info["total_sample"],
                "gmc_method": "lognormal",
                "gmc_n": gmc_res["n_total"],
            },
        })

    results.sort(key=lambda x: x["province"])

    # 恰好两省时做两样本率比较（z 检验 + RD/RR 及 95%CI）
    comparison_test = None
    if len(results) == 2:
        r0, r1 = results[0], results[1]
        if r0["avg_positivity"] is not None and r1["avg_positivity"] is not None \
                and r0["total_samples"] and r1["total_samples"]:
            p0 = r0["avg_positivity"] / 100.0 if r0["avg_positivity"] > 1 else r0["avg_positivity"]
            p1 = r1["avg_positivity"] / 100.0 if r1["avg_positivity"] > 1 else r1["avg_positivity"]
            comparison_test = two_proportion_test(
                p0 * r0["total_samples"], r0["total_samples"],
                p1 * r1["total_samples"], r1["total_samples"],
            )
            comparison_test["province_a"] = r0["province"]
            comparison_test["province_b"] = r1["province"]

    return {"regions": results, "comparison_test": comparison_test}


async def get_equity_analysis(
    db: AsyncSession,
    disease: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
) -> dict:
    """省间公平性分析（设计 B）。

    以省为粒度聚合血清阳性率（复用 _build_base_query 过滤范式），输出：
      - 省间基尼系数（gini）与变异系数（coefficient_of_variation）
      - 最佳 / 最差省（按加权阳性率）
      - 达标比例：对比 WHO 免疫屏障阈值（WHO_THRESHOLDS）
      - Top / Bottom 排名

    返回结构见 schemas/analysis.py 的 EquityAnalysisResponse。
    """
    query = _build_base_query(disease, None, year_start, year_end, age_min, age_max,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False)
    result = await db.execute(query)
    rows = result.scalars().all()

    empty = {
        "disease": disease,
        "n_provinces": 0,
        "n_data_points": len(rows),
        "summary": {
            "gini": None,
            "coefficient_of_variation": None,
            "best_province": None,
            "best_positivity": None,
            "worst_province": None,
            "worst_positivity": None,
            "target_threshold_percent": None,
            "meeting_ratio": None,
            "meeting_provinces_count": 0,
            "total_provinces": 0,
        },
        "top_provinces": [],
        "bottom_provinces": [],
        "province_rows": [],
        "notes": [],
    }
    if not rows:
        return empty

    province_map: dict[str, list[DataPoint]] = {}
    for r in rows:
        for p in (r.province or "").split(";"):
            p = p.strip()
            if not p:
                p = "未知"
            province_map.setdefault(p, []).append(r)

    threshold = WHO_THRESHOLDS.get(normalize_disease(disease or "")) if disease else None

    province_rows = []
    for prov, group_rows in province_map.items():
        wpr_info = _calc_weighted_positivity(group_rows)
        wpr = wpr_info["weighted_positivity"]
        province_rows.append({
            "rank": None,
            "province": prov,
            "weighted_positivity": wpr,
            "ci_lower": wpr_info["ci_lower"],
            "ci_upper": wpr_info["ci_upper"],
            "total_samples": wpr_info["total_sample"],
            "n_studies": len(group_rows),
            "is_meeting_target": (wpr >= threshold) if (wpr is not None and threshold is not None) else None,
        })

    # 仅用有加权阳性率的省计算离散度指标
    valid = [r for r in province_rows if r["weighted_positivity"] is not None]
    if valid:
        valid.sort(key=lambda r: r["weighted_positivity"], reverse=True)
        for i, r in enumerate(valid, 1):
            r["rank"] = i

        pos_vals = [r["weighted_positivity"] for r in valid]
        gini_val = gini(pos_vals)
        cv_val = coefficient_of_variation(pos_vals)

        n_meeting = sum(1 for r in valid if r["is_meeting_target"] is True)
        n_total = len(valid)
        meeting_ratio = round(n_meeting / n_total, 4) if n_total else None

        best, worst = valid[0], valid[-1]
    else:
        gini_val = None
        cv_val = None
        n_meeting = 0
        n_total = 0
        meeting_ratio = None
        best = {"province": None, "weighted_positivity": None}
        worst = {"province": None, "weighted_positivity": None}

    # 全量排名（含无值省，排最后）
    province_rows.sort(key=lambda r: (r["weighted_positivity"] is None, -(r["weighted_positivity"] or 0)))
    for i, r in enumerate(province_rows, 1):
        r["rank"] = i if r["weighted_positivity"] is not None else None

    top_provinces = valid[:5]
    bottom_provinces = valid[-5:][::-1]

    notes = []
    if threshold is not None:
        notes.append(f"达标阈值参照 WHO 免疫屏障标准：{threshold}%")
    else:
        notes.append("未在 WHO_THRESHOLDS 中找到该疾病阈值，达标比例不可用")
    if not valid:
        notes.append("无含样本量的血清阳性率数据，无法计算省间离散度指标")

    return {
        "disease": disease,
        "n_provinces": len(province_rows),
        "n_data_points": len(rows),
        "summary": {
            "gini": gini_val,
            "coefficient_of_variation": cv_val,
            "best_province": best["province"],
            "best_positivity": best["weighted_positivity"],
            "worst_province": worst["province"],
            "worst_positivity": worst["weighted_positivity"],
            "target_threshold_percent": threshold,
            "meeting_ratio": meeting_ratio,
            "meeting_provinces_count": n_meeting,
            "total_provinces": n_total,
        },
        "top_provinces": top_provinces,
        "bottom_provinces": bottom_provinces,
        "province_rows": province_rows,
        "notes": notes,
    }


async def get_quality_assessment(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
) -> dict:
    """数据质量评估。

    对每个已审核通过的主估计调用 ``stats.reliability_grade``（A/B/C/D），输出：
      - 高质量（A/B）占比、带 CI 比例、原文溯源（grounded）比例
      - 等级分布与省级质量汇总
      - 单点估计省份列表（证据薄弱预警：该省仅 1 个主估计）
    """
    query = _build_base_query(disease, province, year_start, year_end, None, None,
                              data_type=None, review_status="approved",
                              include_subgroups=False)
    result = await db.execute(query)
    rows = result.scalars().all()

    # 先按省统计主估计数（作为 reliability_grade 的 n_studies 依据）
    province_map: dict[str, list[DataPoint]] = {}
    for r in rows:
        for p in (r.province or "").split(";"):
            p = p.strip() or "未知"
            province_map.setdefault(p, []).append(r)
    province_counts = {p: len(v) for p, v in province_map.items()}

    estimates = []
    for r in rows:
        prov = (r.province or "").strip() or "未知"
        has_ci = r.ci_lower is not None and r.ci_upper is not None
        grade = reliability_grade(
            sample_size=r.sample_size,
            has_ci=has_ci,
            confidence=r.confidence,
            is_grounded=bool(r.is_grounded),
            n_studies=province_counts.get(prov, 1),
        )
        estimates.append({
            "id": str(r.id),
            "province": prov,
            "disease": r.disease,
            "collection_year": r.collection_year,
            "data_type": r.data_type,
            "sample_size": r.sample_size,
            "value": float(r.value) if r.value is not None else None,
            "has_ci": has_ci,
            "is_grounded": bool(r.is_grounded),
            "confidence": r.confidence,
            "grade": grade,
        })

    total = len(estimates)
    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for e in estimates:
        grade_counts[e["grade"]] += 1

    high_quality = grade_counts["A"] + grade_counts["B"]
    with_ci = sum(1 for e in estimates if e["has_ci"])
    grounded = sum(1 for e in estimates if e["is_grounded"])

    def _ratio(n: int) -> float:
        return round(n / total, 4) if total else 0.0

    province_groups: dict[str, list[dict]] = {}
    for e in estimates:
        province_groups.setdefault(e["province"], []).append(e)

    province_rows = []
    single_estimate_provinces = []
    for prov, ests in province_groups.items():
        n = len(ests)
        p_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
        for e in ests:
            p_counts[e["grade"]] += 1
        province_rows.append({
            "province": prov,
            "n_estimates": n,
            "high_quality_ratio": _ratio(sum(1 for e in ests if e["grade"] in ("A", "B"))),
            "with_ci_ratio": _ratio(sum(1 for e in ests if e["has_ci"])),
            "grounded_ratio": _ratio(sum(1 for e in ests if e["is_grounded"])),
            "grades": p_counts,
            "is_single_estimate": n == 1,
        })
        if n == 1:
            single_estimate_provinces.append(prov)
    province_rows.sort(key=lambda x: x["province"])

    notes = []
    if total == 0:
        notes.append("无已审核通过的主估计数据，无法评估质量")
    if single_estimate_provinces:
        notes.append(f"{len(single_estimate_provinces)} 个省份仅含单点估计，证据薄弱：{'、'.join(sorted(single_estimate_provinces))}")

    return {
        "disease": disease,
        "province": province,
        "year_start": year_start,
        "year_end": year_end,
        "total_estimates": total,
        "n_provinces": len(province_groups),
        "summary": {
            "high_quality_ratio": _ratio(high_quality),
            "grade_a_ratio": _ratio(grade_counts["A"]),
            "grade_b_ratio": _ratio(grade_counts["B"]),
            "grade_c_ratio": _ratio(grade_counts["C"]),
            "grade_d_ratio": _ratio(grade_counts["D"]),
            "with_ci_ratio": _ratio(with_ci),
            "grounded_ratio": _ratio(grounded),
        },
        "grade_distribution": grade_counts,
        "provinces": province_rows,
        "single_estimate_provinces": sorted(single_estimate_provinces),
        "notes": notes,
    }


async def get_goal_tracking(
    db: AsyncSession,
    disease: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
) -> dict:
    """目标达成追踪（对照每病保护阈值 GOAL_THRESHOLDS / HIT）。

    按年聚合全省血清阳性率主估计：
      - 全国进度：当年全部主估计的逆方差加权阳性率（_calc_weighted_positivity）
      - 达标省比例：各省加权阳性率 >= GOAL_THRESHOLDS[疾病] 的省份占比
      - HIT 缺口：GOAL_THRESHOLDS[疾病] - 全国加权阳性率（百分点，负值表示已超标）
    """
    empty = {
        "disease": disease,
        "goal_threshold_percent": None,
        "n_provinces": 0,
        "years": [],
        "latest_year": None,
        "latest_gap_to_hit": None,
        "notes": [],
    }
    if not disease:
        empty["notes"] = ["请指定疾病（disease）以匹配 GOAL_THRESHOLDS 保护目标阈值"]
        return empty

    threshold = GOAL_THRESHOLDS.get(normalize_disease(disease))
    if threshold is None:
        empty["notes"] = [f"未在 GOAL_THRESHOLDS 中找到疾病「{disease}」的保护目标阈值，无法评估达标进度"]
        return empty

    query = _build_base_query(disease, None, year_start, year_end, None, None,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False)
    result = await db.execute(query)
    rows = result.scalars().all()
    if not rows:
        empty["goal_threshold_percent"] = threshold
        empty["notes"] = ["无已审核通过的血清阳性率数据"]
        return empty

    # 按 (年 → 省 → 数据点) 分层
    by_year_prov: dict[int, dict[str, list[DataPoint]]] = {}
    for r in rows:
        if r.collection_year is None:
            continue
        y = r.collection_year
        if y not in by_year_prov:
            by_year_prov[y] = {}
        for p in (r.province or "").split(";"):
            p = p.strip() or "未知"
            by_year_prov[y].setdefault(p, []).append(r)

    years = []
    for y in sorted(by_year_prov.keys()):
        prov_groups = by_year_prov[y]
        year_rows = [r for g in prov_groups.values() for r in g]
        nat = _calc_weighted_positivity(year_rows)
        n_prov = len(prov_groups)
        meeting = 0
        for g in prov_groups.values():
            wpr = _calc_weighted_positivity(g)["weighted_positivity"]
            if wpr is not None and wpr >= threshold:
                meeting += 1
        years.append({
            "year": y,
            "national_positivity": nat["weighted_positivity"],
            "national_ci_lower": nat["ci_lower"],
            "national_ci_upper": nat["ci_upper"],
            "n_provinces": n_prov,
            "meeting_provinces": meeting,
            "meeting_ratio": round(meeting / n_prov, 4) if n_prov else 0.0,
            "gap_to_hit": round(threshold - nat["weighted_positivity"], 2)
            if nat["weighted_positivity"] is not None else None,
        })

    latest = years[-1]
    return {
        "disease": disease,
        "goal_threshold_percent": threshold,
        "n_provinces": len({p for yp in by_year_prov.values() for p in yp.keys()}),
        "years": years,
        "latest_year": latest["year"],
        "latest_gap_to_hit": latest["gap_to_hit"],
        "notes": [f"达标阈值参照 GOAL_THRESHOLDS（{disease}）：{threshold}%"],
    }


async def get_age_curve(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
) -> dict:
    """血清阳性率-年龄曲线（惩罚样条平滑 + 95% 置信带 + 年龄别 FOI）。

    流程：
    1. 取 seroprevalence 已审核主估计，按 age_mid（无则用 _midpoint_age 推算，仍无则
       剔除并计数）聚合：同中点合并阳性数 x 与样本量 n。
    2. 调用 ``stats_engine.fit_age_curve`` 做惩罚样条拟合（加权 GCV 选 λp），
       输出 0.5 岁步长的 P(a) 曲线 + delta 法置信带。
    3. 调用 ``stats_engine.foi_from_curve`` 由样条解析导数产出年龄别 FOI。
    4. 组装 ``meta``：covarage_warning / dropped_points / lambda_smooth / monotonic_violation。
    """
    query = _build_base_query(disease, province, year_start, year_end, None, None,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False)
    result = await db.execute(query)
    rows = result.scalars().all()

    # 按 age_mid（0.1 取整）聚合 x、n；缺失可推算年龄的剔除并计数
    groups: dict[float, list[DataPoint]] = {}
    dropped = 0
    for r in rows:
        if r.value is None or r.sample_size is None:
            dropped += 1
            continue
        mid = _midpoint_age(r.age_min, r.age_max)
        if mid is None:
            dropped += 1
            continue
        key = round(mid, 1)
        groups.setdefault(key, []).append(r)

    points: list[dict] = []
    records: list[tuple[float, int, int]] = []
    for key in sorted(groups.keys()):
        g = groups[key]
        p_vals, n_vals = [], []
        for r in g:
            p = float(r.value)
            if p > 1.0:
                p /= 100.0
            p = min(max(p, 0.0), 1.0)
            n_vals.append(int(r.sample_size))
            p_vals.append(p)
        n_tot = sum(n_vals)
        # 样本量加权阳性数：x = Σ nᵢ·pᵢ
        x_tot = int(round(sum(n_i * p_i for n_i, p_i in zip(n_vals, p_vals))))
        if n_tot <= 0:
            continue
        points.append({
            "age_mid": key,
            "x": x_tot,
            "n": n_tot,
            "prevalence": round(x_tot / n_tot * 100.0, 2),
        })
        records.append((key, x_tot, n_tot))

    n_points = len(points)

    # 覆盖度警告：相邻年龄中点间隔 >10 年，或覆盖年龄跨度 <5 年
    covarage_warning = False
    if n_points >= 2:
        gaps = [points[i + 1]["age_mid"] - points[i]["age_mid"] for i in range(n_points - 1)]
        if max(gaps) > 10.0:
            covarage_warning = True
        if points[-1]["age_mid"] - points[0]["age_mid"] < 5.0:
            covarage_warning = True

    # 数据点不足（<8）时直接返回空结构，由路由层报 422
    if n_points < 8:
        return {
            "disease": disease,
            "province": province,
            "n_points": n_points,
            "curve": [],
            "points": points,
            "foi_curve": [],
            "meta": {
                "covarage_warning": covarage_warning,
                "dropped_points": dropped,
                "lambda_smooth": None,
                "monotonic_violation": None,
            },
        }

    fit = fit_age_curve(records)
    curve = fit["curve"]
    grid_ages = [pt["age"] for pt in curve]
    foi_curve = foi_from_curve(grid_ages, fit["spline"])

    return {
        "disease": disease,
        "province": province,
        "n_points": n_points,
        "curve": curve,
        "points": points,
        "foi_curve": foi_curve,
        "meta": {
            "covarage_warning": covarage_warning,
            "dropped_points": dropped,
            "lambda_smooth": fit["lambda_smooth"],
            "monotonic_violation": fit["monotonic_violation"],
        },
    }


async def get_birth_cohort(
    db: AsyncSession,
    disease: str,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
) -> dict:
    """出生队列分析：birth_year = collection_year − age_mid，揭示代际免疫差异。

    流程：
    1. 复用 ``_build_base_query`` 取 seroprevalence 已审核主估计（disease 必填）；
    2. age_mid 用 ``_midpoint_age`` 推算，无法推算（无年龄、无调查年、无样本量）
       的点剔除并计数 ``meta.dropped``；
    3. 聚合 cell=(出生十年段, collection_year) → 加权阳性率 + 95% CI
       （复用 stats_engine.birth_cohort_analysis，内部调 weighted_rate_ci）；
    4. 不足 2 点的 cell → rate 置 None（heatmap 留空）。
    响应附 ``disease_note``（麻疹/风疹等计划免疫史解读提示，读 disease_notes.json）。
    """
    query = _build_base_query(disease, province, year_start, year_end, None, None,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False)
    result = await db.execute(query)
    rows = result.scalars().all()

    records: list[tuple] = []
    dropped = 0
    for r in rows:
        if r.value is None or r.sample_size is None or r.collection_year is None:
            dropped += 1
            continue
        mid = _midpoint_age(r.age_min, r.age_max)
        if mid is None:
            dropped += 1
            continue
        records.append((r.collection_year, mid, float(r.value), int(r.sample_size)))

    analysis = birth_cohort_analysis(records)
    analysis["dropped"] += dropped

    normalized = normalize_disease(disease)
    return {
        "disease": normalized,
        "province": province,
        "year_start": year_start,
        "year_end": year_end,
        "cohorts": analysis["cohorts"],
        "matrix": analysis["matrix"],
        "x_years": analysis["x_years"],
        "y_bands": analysis["y_bands"],
        "disease_note": _load_disease_note(normalized),
        "meta": {
            "n_records": analysis["n_records"],
            "dropped": analysis["dropped"],
            "min_cell_points": 2,
            "method": "weighted_rate_ci",
        },
    }


async def get_meta_merge(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    include_low_quality: bool = False,
) -> dict:
    """同省同病多研究 meta 合并（固定/随机效应）+ 异质性 I²。

    以每条已审核主估计（seroprevalence）作为一项「研究」，按省份分组，
    调用 ``stats.inverse_variance_meta`` 做逆方差加权合并并输出 I² / Q / τ²。

    质量过滤：默认仅纳入质量分级为 A+B 的数据点（meta 合并的证据质量门槛）；
    传 include_low_quality=True 可放开，纳入全部已审核主估计。
    """
    query = _build_base_query(disease, province, None, None, None, None,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False,
                              quality_grades=None if include_low_quality else {"A", "B"})
    result = await db.execute(query)
    rows = result.scalars().all()

    # 批量取文献标题，用于标识每项研究
    title_map: dict[str, str] = {}
    lit_ids = {str(r.literature_id) for r in rows if r.literature_id is not None}
    if lit_ids:
        lit_res = await db.execute(
            select(Literature.id, Literature.title).where(Literature.id.in_(list(lit_ids)))
        )
        title_map = {str(lid): title for lid, title in lit_res.all()}

    prov_map: dict[str, list[DataPoint]] = {}
    for r in rows:
        for p in (r.province or "").split(";"):
            p = p.strip() or "未知"
            prov_map.setdefault(p, []).append(r)

    def _run_merge(prov_rows: list[DataPoint]) -> dict:
        studies = []
        p_list, n_list, lo_list, hi_list = [], [], [], []
        for r in prov_rows:
            if r.value is None or not r.sample_size:
                continue
            p_list.append(float(r.value))
            n_list.append(float(r.sample_size))
            lo_list.append(float(r.ci_lower) if r.ci_lower is not None else None)
            hi_list.append(float(r.ci_upper) if r.ci_upper is not None else None)
            studies.append({
                "literature_title": title_map.get(str(r.literature_id)) or "未知文献",
                "collection_year": r.collection_year,
                "sample_size": r.sample_size,
                "value": round(float(r.value), 2),
                "ci_lower": round(float(r.ci_lower), 2) if r.ci_lower is not None else None,
                "ci_upper": round(float(r.ci_upper), 2) if r.ci_upper is not None else None,
                "assay": r.assay,
                "quality_score": r.quality_score,
                "quality_grade": r.quality_grade,
            })
        m = inverse_variance_meta(p_list, n_list, lo_list, hi_list)
        i2 = m["i_squared_percent"]
        if m["k"] == 0:
            het = "n/a"
        elif i2 < 25:
            het = "low"
        elif i2 <= 50:
            het = "moderate"
        else:
            het = "high"
        return {
            "k": m["k"],
            "pooled_fixed_percent": round(m["pooled_fixed"] * 100, 2) if m["pooled_fixed"] is not None else None,
            "pooled_random_percent": round(m["pooled_random"] * 100, 2) if m["pooled_random"] is not None else None,
            "i_squared_percent": i2,
            "q_statistic": m["q_statistic"],
            "tau_squared": m["tau_squared"],
            "heterogeneity": het,
            "studies": studies,
        }

    results = [{"province": p, **_run_merge(g)} for p, g in prov_map.items()]
    results.sort(key=lambda x: x["province"])

    notes = []
    if not results:
        notes.append("无已审核通过的血清阳性率数据，无法进行 meta 合并")

    return {
        "disease": disease,
        "province": province,
        "n_provinces": len(results),
        "results": results,
        "notes": notes,
    }


async def get_meta_analysis(
    db: AsyncSession,
    disease: str,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    group_by: Optional[str] = None,
    include_low_quality: bool = False,
) -> dict:
    """多文献血清阳性率随机效应 Meta 分析（Freeman-Tukey 双反正弦变换）。

    不指定 group_by：把过滤集内每个文献的主估计作为研究单元合并。
    指定 group_by：（逗号分隔 province/year/age_group）按组分别合并，
    返回数组，组间附带 Q_between 亚组异质性检验。

    质量过滤：默认仅纳入 A+B 级（meta 合并的证据质量门槛）。
    """
    quality_grades = None if include_low_quality else {"A", "B"}
    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False,
                              quality_grades=quality_grades)
    result = await db.execute(query)
    rows = result.scalars().all()

    # 批量取文献标题
    title_map: dict[str, str] = {}
    lit_ids = {str(r.literature_id) for r in rows if r.literature_id is not None}
    if lit_ids:
        lit_res = await db.execute(
            select(Literature.id, Literature.title).where(Literature.id.in_(list(lit_ids)))
        )
        title_map = {str(lid): title for lid, title in lit_res.all()}

    def _row_to_study(r: DataPoint) -> Optional[tuple]:
        """转换 DataPoint 为 (x, n, label) 三元组。"""
        if r.value is None or not r.sample_size:
            return None
        p = float(r.value) / 100.0 if float(r.value) > 1.0 else float(r.value)
        n = float(r.sample_size)
        if p < 0.0 or p > 1.0 or n <= 0:
            return None
        x = p * n
        label = title_map.get(str(r.literature_id)) or f"文献{r.literature_id}"
        if r.collection_year:
            label = f"{label} ({r.collection_year})"
        return (x, n, label)

    def _group_key(r: DataPoint, fields: list[str]) -> str:
        """按 group_by 字段生成组键。"""
        parts = []
        for f in fields:
            if f == "province":
                parts.append((r.province or "").strip() or "未知")
            elif f == "year":
                parts.append(str(r.collection_year or 0))
            elif f == "age_group":
                parts.append(_get_age_group_label(r.age_min, r.age_max) or "未分类")
        return "|".join(parts)

    def _compute_q_between(groups: list[dict]) -> Optional[dict]:
        """亚组异质性 Q_between 检验（Cochran Q 分解）。

        Q_between = Q_total − Σ Q_within_j
        - Q_within_j：组 j 内固定效应 Q（取自 meta.pooled.Q，纯函数内已按 FE 权重计算）；
        - Q_total：全部研究合并后（固定效应）的 Q；
        - df = g − 1，p 用 chi2.sf。数值稳定，避免对组 SE 求倒数的爆炸。
        """
        valid = [g for g in groups if g.get("meta") and g["meta"].get("pooled")]
        if len(valid) < 2:
            return None

        # 全部研究的 (t, se)（se = √v，FE 权重 w = 1/v）
        all_studies = []
        for g in valid:
            for s in g["meta"].get("per_study", []):
                if s.get("t") is not None and s.get("se"):
                    all_studies.append((s["t"], s["se"]))
        if not all_studies:
            return None

        # Q_total：全部研究 FE 加权平均周围的 Q
        w_total = sum(1.0 / (se ** 2) for _, se in all_studies)
        t_total = sum(t / (se ** 2) for t, se in all_studies) / w_total
        q_total = sum((t - t_total) ** 2 / (se ** 2) for t, se in all_studies)

        # Σ Q_within_j：各组内 Q（meta.pooled.Q 已是 FE 口径）
        q_within = sum(g["meta"]["pooled"].get("Q") or 0.0 for g in valid)

        q_between = max(0.0, q_total - q_within)
        df = len(valid) - 1
        p = float(sps.chi2.sf(q_between, df)) if df > 0 else 1.0
        return {
            "Q_between": round(q_between, 4),
            "df": df,
            "p_value": round(p, 6),
            "Q_total": round(q_total, 4),
            "Q_within": round(q_within, 4),
        }

    # ── 无 group_by：单次合并 ──────────────────────────────
    if not group_by:
        studies = []
        for r in rows:
            s = _row_to_study(r)
            if s:
                studies.append(s)
        meta = meta_proportion(studies) if studies else meta_proportion([])
        per_study = []
        for s, m in zip(studies, meta.get("per_study", [])):
            per_study.append(m)

        resp = {
            "disease": disease,
            "group_by": None,
            "groups": [{
                "group": "all",
                "n_studies": meta["pooled"]["k"],
                "meta": meta,
            }],
            "q_between": None,
            "notes": meta["notes"],
        }
        return resp

    # ── 有 group_by：按组分合并 ────────────────────────────
    group_fields = [f.strip() for f in group_by.split(",") if f.strip()]
    valid_fields = {"province", "year", "age_group"}
    group_fields = [f for f in group_fields if f in valid_fields]
    if not group_fields:
        group_fields = ["province"]

    groups: dict[str, list[tuple]] = {}
    for r in rows:
        key = _group_key(r, group_fields)
        s = _row_to_study(r)
        if s:
            groups.setdefault(key, []).append(s)

    group_results = []
    for key, studies in sorted(groups.items()):
        meta = meta_proportion(studies)
        group_results.append({
            "group": key,
            "n_studies": len(studies),
            "meta": meta,
        })

    q_between = _compute_q_between(group_results)

    return {
        "disease": disease,
        "group_by": group_by,
        "groups": group_results,
        "q_between": q_between,
        "notes": [m["notes"] for g in group_results for m in [g["meta"]]],
    }


async def get_assay_heterogeneity(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
) -> dict:
    """按 assay（检测方法）分层的异质性对比。

    以每种 assay 作为一组（seroprevalence 主估计），输出各组的加权阳性率与
    95% CI，并用 ``stats.inverse_variance_meta`` 计算跨 assay 的 I² 异质性。
    """
    query = _build_base_query(disease, province, None, None, None, None,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False)
    result = await db.execute(query)
    rows = result.scalars().all()

    assay_map: dict[str, list[DataPoint]] = {}
    for r in rows:
        key = (r.assay or "").strip() or "未注明"
        assay_map.setdefault(key, []).append(r)

    results = []
    for assay, g in assay_map.items():
        wpr = _calc_weighted_positivity(g)
        results.append({
            "assay": assay,
            "n_studies": len(g),
            "total_samples": wpr["total_sample"],
            "weighted_positivity": wpr["weighted_positivity"],
            "ci_lower": wpr["ci_lower"],
            "ci_upper": wpr["ci_upper"],
        })
    results.sort(key=lambda x: (x["weighted_positivity"] is None, -(x["weighted_positivity"] or 0)))

    # 跨 assay 异质性：以各组为「研究」做逆方差合并
    across = inverse_variance_meta(
        [r["weighted_positivity"] for r in results],
        [float(r["total_samples"]) for r in results],
        [r["ci_lower"] for r in results],
        [r["ci_upper"] for r in results],
    )
    pooled_all = _calc_weighted_positivity(rows)

    notes = []
    if not results:
        notes.append("无已审核通过的血清阳性率数据，无法按 assay 分层")
    if across["k"] >= 2:
        i2 = across["i_squared_percent"]
        if i2 >= 50:
            notes.append(f"跨 assay 异质性较高（I²={i2}%），不同检测方法结果差异需谨慎解读")

    return {
        "disease": disease,
        "province": province,
        "n_assays": len(results),
        "results": results,
        "pooled_all_percent": pooled_all["weighted_positivity"],
        "pooled_all_ci_lower": pooled_all["ci_lower"],
        "pooled_all_ci_upper": pooled_all["ci_upper"],
        "across_assay_i_squared_percent": across["i_squared_percent"],
        "across_assay_q_statistic": across["q_statistic"],
        "across_assay_k": across["k"],
        "notes": notes,
    }


async def get_simulation(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    assumed_coverage: float = 90.0,
    booster_rate: float = 0.0,
) -> dict:
    """免疫屏障模拟（复用 FOI 催化模型反推）。

    1. 用观测血清阳性率经催化模型反推平均 FOI → 估计 R0 → HIT；
    2. 给定假设接种覆盖（assumed_coverage）与加强针比例（booster_rate），
       模拟有效免疫比例 effective = cov + (1-cov)·booster；
    3. 对比 HIT 判定屏障状态，并反推「需达到的覆盖/加强组合」。
    """
    empty = {
        "disease": disease,
        "province": province,
        "assumed_coverage_percent": assumed_coverage,
        "booster_rate_percent": booster_rate,
        "current": None,
        "simulated": None,
        "required_coverage_to_reach_hit": None,
        "notes": ["无已审核通过的血清阳性率数据，无法进行 FOI 反推"],
    }
    query = _build_base_query(disease, province, None, None, None, None,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False)
    result = await db.execute(query)
    rows = result.scalars().all()
    if not rows:
        return empty

    # 观测免疫水平（样本量加权）
    current_sp = _calc_weighted_positivity(rows)["weighted_positivity"]

    # FOI：每点催化模型 → 样本量加权平均 FOI → R0 → HIT
    foi_tuples = []
    for r in rows:
        if r.value is None:
            continue
        mid = _midpoint_age(r.age_min, r.age_max)
        if mid is None:
            continue
        foi = _calc_foi_from_sp(float(r.value), mid)
        if foi is not None:
            foi_tuples.append((foi, r.sample_size or 1))
    foi_avg = None
    if foi_tuples:
        w = sum(wt for _, wt in foi_tuples)
        foi_avg = round(sum(v * wt for v, wt in foi_tuples) / w, 6) if w > 0 else None

    estimated_r0 = _calc_r0_from_foi(foi_avg) if foi_avg is not None else None
    hit_from_foi = _calc_hit_from_r0(estimated_r0) if estimated_r0 is not None else None

    dis_key = normalize_disease(disease or "") or (disease or "")
    r0_ref = R0_REFERENCE.get(dis_key)
    reference_hit = _calc_hit_from_r0(r0_ref[0]) if r0_ref else None
    goal_threshold = GOAL_THRESHOLDS.get(dis_key)
    who_threshold = WHO_THRESHOLDS.get(dis_key)

    # 屏障目标：优先 FOI 估计，否则 GOAL/WHO 阈值，再退到文献 R0
    hit_target = hit_from_foi or goal_threshold or who_threshold or reference_hit

    def _status(sp: Optional[float], target: Optional[float]) -> str:
        if sp is None or target is None:
            return "undetermined"
        if sp >= target:
            return "reached"
        if sp >= target - 10:
            return "near"
        return "not_reached"

    current_status = _status(current_sp, hit_target)
    current = {
        "weighted_positivity_percent": current_sp,
        "weighted_avg_foi_per_year": foi_avg,
        "estimated_r0": estimated_r0,
        "r0_reference": {"typical": r0_ref[0] if r0_ref else None,
                         "range_low": r0_ref[1] if r0_ref else None,
                         "range_high": r0_ref[2] if r0_ref else None},
        "hit_percent": hit_target,
        "status": current_status,
    }

    # 模拟有效免疫比例（加强针只作用于尚未免疫者）
    cov = max(0.0, min(100.0, float(assumed_coverage)))
    boost = max(0.0, min(100.0, float(booster_rate)))
    effective = cov + (1.0 - cov / 100.0) * boost  # 单位 %
    sim_status = _status(effective, hit_target)
    gain = effective - cov
    simulated = {
        "effective_coverage_percent": round(effective, 2),
        "hit_percent": hit_target,
        "gap_to_hit_percent": round(hit_target - effective, 2) if hit_target is not None else None,
        "gain_from_booster_percent": round(gain, 2),
        "status": sim_status,
    }

    # 反推：给定 booster 下达到 HIT 所需的基础覆盖
    required = None
    if hit_target is not None:
        hit_ratio = hit_target / 100.0
        b_ratio = boost / 100.0
        if b_ratio >= 1.0:
            required = 0.0 if hit_ratio <= 1.0 else None
        elif hit_ratio <= b_ratio:
            required = 0.0
        else:
            required = round((hit_ratio - b_ratio) / (1.0 - b_ratio) * 100.0, 2)
            if required > 100.0:
                required = None  # 仅靠基础接种无法达标

    notes = []
    if hit_target is None:
        notes.append("无法估计 HIT（无 FOI 数据且无 GOAL/WHO/文献阈值），屏障状态为 undetermined")
    if current_status != "reached" and sim_status == "reached":
        notes.append(f"在当前假设（覆盖 {cov}% + 加强 {boost}%）下模拟可达群体免疫（≥{hit_target}%）")
    if hit_from_foi is not None and r0_ref and estimated_r0 is not None:
        if estimated_r0 < r0_ref[1] * 0.3 or estimated_r0 > r0_ref[2] * 2:
            notes.append("基于 FOI 的 R0 估计超出文献参考区间，模拟结果需谨慎解读")

    return {
        "disease": disease,
        "province": province,
        "assumed_coverage_percent": cov,
        "booster_rate_percent": boost,
        "current": current,
        "simulated": simulated,
        "required_coverage_to_reach_hit": required,
        "notes": notes,
    }


AGE_GROUPS = [
    ("<1岁", 0, 0),
    ("1-4岁", 1, 4),
    ("5-14岁", 5, 14),
    ("15-59岁", 15, 59),
    ("≥60岁", 60, 200),
]


def _get_age_group_label(age_min: Optional[int], age_max: Optional[int]) -> Optional[str]:
    """根据年龄范围判断年龄段标签"""
    if age_min is None:
        return None
    for label, lo, hi in AGE_GROUPS:
        if age_min >= lo and (age_max is not None and age_max <= hi):
            return label
    return "其他"


async def get_age_stratify(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    data_type: Optional[str] = None,
) -> list[dict]:
    """年龄分层分析"""
    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max, data_type)
    result = await db.execute(query)
    rows = result.scalars().all()

    age_map: dict[str, list[DataPoint]] = {}
    for group in AGE_GROUPS:
        age_map[group[0]] = []

    for r in rows:
        label = _get_age_group_label(r.age_min, r.age_max)
        if label is None:
            label = "未分类"
        if label not in age_map:
            age_map[label] = []
        age_map[label].append(r)

    results = []
    for age_group, group_rows in age_map.items():
        if not group_rows:
            continue
        meta_info = _meta_merge_cell(group_rows)
        gmc_res = _calc_gmc(group_rows)

        results.append({
            "age_group": age_group,
            "avg_positivity": meta_info["positivity"],
            "positivity_ci_lower": meta_info["ci_lower"],
            "positivity_ci_upper": meta_info["ci_upper"],
            "rate_weighted_legacy": meta_info["rate_weighted_legacy"],  # @deprecated
            "meta": meta_info["meta"],
            "avg_gmc": gmc_res["gmc"],
            "gmc_ci_lower": gmc_res["ci_lower"],
            "gmc_ci_upper": gmc_res["ci_upper"],
            "point_count": len(group_rows),
            "total_samples": meta_info["total_sample"],
            "ci_meta": {
                "positivity_method": "meta_ft" if meta_info["meta"] else "normal_approx",
                "positivity_model": meta_info["meta"]["model"] if meta_info["meta"] else None,
                "positivity_I2": meta_info["meta"]["I2"] if meta_info["meta"] else None,
                "positivity_n": meta_info["total_sample"],
                "gmc_method": "lognormal",
                "gmc_n": gmc_res["n_total"],
            },
        })

    return {
        "age_groups": results,
        "standard_population_version": CHINA_POP_STD_VERSION,
    }


async def get_summary(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    data_type: Optional[str] = None,
) -> dict:
    """汇总统计"""
    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max, data_type)
    result = await db.execute(query)
    rows = result.scalars().all()

    if not rows:
        return {
            "total_data_points": 0,
            "total_literatures": 0,
            "total_samples": 0,
            "avg_positivity": None,
            "avg_positivity_ci_lower": None,
            "avg_positivity_ci_upper": None,
            "min_positivity": None,
            "max_positivity": None,
            "avg_gmc": None,
            "avg_gmc_ci_lower": None,
            "avg_gmc_ci_upper": None,
            "ci_meta": {
                "positivity_method": "normal_approx",
                "positivity_n": 0,
                "gmc_method": "lognormal",
                "gmc_n": 0,
            },
        }

    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.value is not None]
    lit_ids = set(str(r.literature_id) for r in rows if r.literature_id)

    wpr_info = _calc_weighted_positivity(sp_rows)
    gmc_info = _calc_gmc(rows)

    return {
        "total_data_points": len(rows),
        "total_literatures": len(lit_ids),
        "total_samples": wpr_info["total_sample"],
        "avg_positivity": wpr_info["weighted_positivity"],
        "avg_positivity_ci_lower": wpr_info["ci_lower"],
        "avg_positivity_ci_upper": wpr_info["ci_upper"],
        "min_positivity": round(min(r.value for r in sp_rows), 2) if sp_rows else None,
        "max_positivity": round(max(r.value for r in sp_rows), 2) if sp_rows else None,
        "avg_gmc": gmc_info["gmc"],
        "avg_gmc_ci_lower": gmc_info["ci_lower"],
        "avg_gmc_ci_upper": gmc_info["ci_upper"],
        "ci_meta": {
            "positivity_method": "normal_approx",
            "positivity_n": wpr_info["total_sample"],
            "gmc_method": "lognormal",
            "gmc_n": gmc_info["n_total"],
        },
    }


async def get_immune_barrier_assessment(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    life_expectancy: float = 75.0,
    seroreversion_mu: Optional[float] = None,
    hit_source_override: Optional[str] = None,
) -> dict:
    """免疫屏障评估（复用 FOI 模块的 R0/HIT 计算）。

    优化点（参考 serotracker）：
      1. 复用 FOI 催催化模型 λ = -ln(1-SP)/age 估算 FOI；
      2. 反推 R0 ≈ λ·L，计算 HIT = 1 - 1/R0；
      3. HIT 阈值优先级：FOI 估计 > WHO 硬编码 > 文献 R0；
      4. 新增年龄分层分析（age_groups）；
      5. 新增省份对比矩阵（province_matrix）。
    """
    logger.info(
        f"[ImmuneBarrier] 开始评估: disease={disease}, province={province}, "
        f"year_start={year_start}, year_end={year_end}, age_min={age_min}, age_max={age_max}"
    )

    # 收集本次评估使用的显式参数假设（用于响应透明展示）
    assumptions = {}
    if life_expectancy != 75.0:
        assumptions["life_expectancy"] = life_expectancy
    if seroreversion_mu:
        assumptions["seroreversion_mu"] = seroreversion_mu
    if hit_source_override:
        assumptions["hit_source_override"] = hit_source_override

    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max,
                              review_status="approved")
    result = await db.execute(query)
    rows = result.scalars().all()

    # 标准化疾病 key，用于查 R0_REFERENCE / WHO_THRESHOLDS
    dis_key = normalize_disease(disease) if disease else None
    r0_ref = R0_REFERENCE.get(dis_key) if dis_key else None  # (typical, low, high)
    who_threshold = WHO_THRESHOLDS.get(dis_key) if dis_key else None
    reference_hit = _calc_hit_from_r0(r0_ref[0]) if r0_ref else None

    r0_reference_block = {
        "typical": r0_ref[0] if r0_ref else None,
        "range_low": r0_ref[1] if r0_ref else None,
        "range_high": r0_ref[2] if r0_ref else None,
    }

    if not rows:
        logger.warning(f"[ImmuneBarrier] 无审核通过数据: disease={disease}")
        return {
            "disease": dis_key or disease,
            "who_threshold": who_threshold,
            "r0_reference": r0_reference_block,
            "summary": {
                "total_data_points": 0,
                "total_literatures": 0,
                "total_samples": 0,
                "weighted_positivity_rate": None,
                "weighted_avg_foi_per_year": None,
                "estimated_r0_from_foi": None,
                "hit_from_foi_percent": None,
                "hit_from_reference_r0_percent": reference_hit,
                "hit_target_used_percent": None,
                "hit_target_source": "none",
                "models": [],
                "recommended_model": None,
                "recommended_params": None,
                "fitted_curve": [],
                "modeling_notes": [],
                "r0_assumption_note": None,
                "n_catalytic_records": 0,
                "catalytic_age_range": [None, None],
            },
            "yearly_trend": [],
            "age_groups": [],
            "province_matrix": [],
            "status": "no_data",
            "assessment": "暂无审核通过的数据可供评估。",
            "life_expectancy_used": life_expectancy,
            "assumptions": assumptions or None,
        }

    # --- 1) 总体加权阳性率 ---
    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.sample_size]
    _wpr = _calc_weighted_positivity(rows)
    weighted_rate = _wpr["weighted_positivity"]
    total_sample = _wpr["total_sample"]
    weighted_rate_ci_lower = _wpr["ci_lower"]
    weighted_rate_ci_upper = _wpr["ci_upper"]

    lit_ids = set(str(r.literature_id) for r in rows if r.literature_id)

    # --- 2) FOI 估算（复用催化模型族 MLE 新引擎）---
    # 旧口径：单点 λ=-ln(1-SP)/age 再样本量加权（仅作催化模型失败时的回退）
    foi_tuples: list[tuple[float, int]] = []
    for r in sp_rows:
        if r.value is None:
            continue
        age_mid = _midpoint_age(r.age_min, r.age_max)
        if age_mid is None:
            continue
        foi = _calc_foi_from_sp(float(r.value), age_mid)
        if foi is not None:
            foi_tuples.append((foi, r.sample_size or 1))
    if foi_tuples:
        w_total_foi = sum(w for _, w in foi_tuples)
        legacy_foi = round(
            sum(v * w for v, w in foi_tuples) / w_total_foi, 6
        ) if w_total_foi > 0 else None
    else:
        legacy_foi = None

    # 新引擎：M1/M2/M3 催化模型族 MLE 拟合 + 模型比较 + 理论修正
    catalytic_records = _build_catalytic_records(sp_rows)
    catalytic_result = fit_catalytic_models(catalytic_records, mu_fixed=seroreversion_mu)
    models_out = catalytic_result.get("models") or []
    recommended_model = catalytic_result.get("recommended_model")
    recommended_params = catalytic_result.get("recommended_params") or {}
    fitted_curve = catalytic_result.get("fitted_curve") or []
    catalytic_notes = catalytic_result.get("modeling_notes") or []

    r0_hit_info = _catalytic_r0_hit(catalytic_result, dis_key, life_exp=life_expectancy,
                                    mu_fixed=seroreversion_mu)
    rec_foi = r0_hit_info["foi_avg"]
    r0_to_hit = r0_hit_info["r0_to_hit"]
    literature_hit = r0_hit_info["literature_hit"]
    r0_assumption_note = r0_hit_info["r0_assumption_note"]

    # 兼容旧字段：foi/r0 取 recommended_model 参数重算；无催化结果时回退旧加权平均
    weighted_avg_foi = rec_foi if rec_foi is not None else legacy_foi
    estimated_r0 = r0_to_hit
    foi_hit_percent = _calc_hit_from_r0(estimated_r0) if estimated_r0 is not None else None

    # HIT 阈值优先级链不变：FOI 估算 > WHO 硬编码 > 文献 R0（hit_source 扩展 mle_foi）
    hit_target, hit_source = _resolve_hit_target(
        foi_hit_percent, who_threshold, literature_hit, dis_key,
        hit_source_override=hit_source_override,
    )

    logger.info(
        f"[ImmuneBarrier] FOI/R0/HIT: weighted_avg_foi={weighted_avg_foi}, "
        f"estimated_r0={estimated_r0}, recommended_model={recommended_model}, "
        f"foi_hit={foi_hit_percent}%, reference_hit={literature_hit}%, "
        f"who_threshold={who_threshold}%, hit_target={hit_target}% (source={hit_source})"
    )

    # --- 3) 逐年趋势 ---
    year_groups: dict[int, list[DataPoint]] = {}
    for r in rows:
        if r.collection_year is None:
            continue
        y = r.collection_year
        if y not in year_groups:
            year_groups[y] = []
        year_groups[y].append(r)

    yearly_trend = []
    for year in sorted(year_groups.keys()):
        group = year_groups[year]
        _wpr_g = _calc_weighted_positivity(group)
        y_rate = _wpr_g["weighted_positivity"]
        ys = _wpr_g["total_sample"]
        yearly_trend.append({
            "year": year,
            "weighted_positivity": y_rate,
            "sample_size": ys,
            "ci_lower": _wpr_g["ci_lower"],
            "ci_upper": _wpr_g["ci_upper"],
            "point_count": len(group),
        })

    # --- 4) 年龄分层分析 ---
    age_map: dict[str, dict] = {
        g[0]: {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}
        for g in AGE_GROUPS
    }
    age_map["其他"] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}

    for r in sp_rows:
        if r.value is None:
            continue
        label = _get_age_group_label(r.age_min, r.age_max) or "其他"
        if label not in age_map:
            age_map[label] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}
        bucket = age_map[label]
        sp = float(r.value)
        ss = r.sample_size or 0
        if ss > 0:
            bucket["sp_sum"] += sp * ss
            bucket["sample_sum"] += ss
        bucket["dp_count"] += 1
        age_mid = _midpoint_age(r.age_min, r.age_max)
        foi = _calc_foi_from_sp(sp, age_mid) if age_mid is not None else None
        if foi is not None:
            bucket["foi_values"].append((foi, ss or 1))

    age_groups_out: list[dict] = []
    for age_label, lo, hi in AGE_GROUPS:
        bucket = age_map[age_label]
        if bucket["dp_count"] == 0:
            continue
        w_sp = round(bucket["sp_sum"] / bucket["sample_sum"], 2) if bucket["sample_sum"] > 0 else None
        if bucket["foi_values"]:
            fw = sum(w for _, w in bucket["foi_values"])
            w_foi = round(sum(v * w for v, w in bucket["foi_values"]) / fw, 6) if fw > 0 else None
        else:
            w_foi = None
        age_status = _barrier_status_from_rate(w_sp, hit_target)
        age_groups_out.append({
            "age_group": age_label,
            "age_range": [lo, hi],
            "data_point_count": bucket["dp_count"],
            "total_samples": bucket["sample_sum"],
            "weighted_positivity_rate": w_sp,
            "weighted_avg_foi_per_year": w_foi,
            "status": age_status,
        })

    # --- 5) 省份对比矩阵 ---
    prov_map: dict[str, dict] = {}
    for r in sp_rows:
        if r.value is None:
            continue
        prov_raw = r.province or "未知"
        for p in prov_raw.split(";"):
            p = p.strip()
            if not p:
                p = "未知"
            if p not in prov_map:
                prov_map[p] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}
            pm = prov_map[p]
            sp = float(r.value)
            ss = r.sample_size or 0
            if ss > 0:
                pm["sp_sum"] += sp * ss
                pm["sample_sum"] += ss
            pm["dp_count"] += 1
            age_mid = _midpoint_age(r.age_min, r.age_max)
            foi = _calc_foi_from_sp(sp, age_mid) if age_mid is not None else None
            if foi is not None:
                pm["foi_values"].append((foi, ss or 1))

    province_matrix: list[dict] = []
    for prov_name, pm in prov_map.items():
        if pm["dp_count"] == 0:
            continue
        w_sp = round(pm["sp_sum"] / pm["sample_sum"], 2) if pm["sample_sum"] > 0 else None
        if pm["foi_values"]:
            fw = sum(w for _, w in pm["foi_values"])
            prov_foi = round(sum(v * w for v, w in pm["foi_values"]) / fw, 6) if fw > 0 else None
        else:
            prov_foi = None
        prov_r0 = _calc_r0_from_foi(prov_foi, life_expectancy) if prov_foi is not None else None
        prov_status = _barrier_status_from_rate(w_sp, hit_target)
        province_matrix.append({
            "province": prov_name,
            "data_point_count": pm["dp_count"],
            "total_samples": pm["sample_sum"],
            "weighted_positivity_rate": w_sp,
            "weighted_avg_foi_per_year": prov_foi,
            "estimated_r0_from_foi": prov_r0,
            "hit_target_percent": hit_target,
            "status": prov_status,
        })
    province_matrix.sort(key=lambda x: x["province"])

    # --- 6) 总体状态判定 ---
    status, assessment = _barrier_status_with_message(weighted_rate, hit_target, hit_source)

    logger.info(
        f"[ImmuneBarrier] 评估完成: status={status}, weighted_rate={weighted_rate}%, "
        f"hit_target={hit_target}%, age_groups={len(age_groups_out)}, "
        f"provinces={len(province_matrix)}"
    )

    return {
        "disease": dis_key or disease,
        "who_threshold": who_threshold,
        "r0_reference": r0_reference_block,
        "summary": {
            "total_data_points": len(rows),
            "total_literatures": len(lit_ids),
            "total_samples": total_sample,
            "weighted_positivity_rate": weighted_rate,
            "weighted_positivity_ci_lower": weighted_rate_ci_lower,
            "weighted_positivity_ci_upper": weighted_rate_ci_upper,
            "weighted_avg_foi_per_year": weighted_avg_foi,
            "estimated_r0_from_foi": estimated_r0,
            "hit_from_foi_percent": foi_hit_percent,
            "hit_from_reference_r0_percent": literature_hit,
            "hit_target_used_percent": hit_target,
            "hit_target_source": hit_source,
            # 新增：催化模型族 MLE 拟合 + 模型比较
            "models": models_out,
            "recommended_model": recommended_model,
            "recommended_params": recommended_params,
            "fitted_curve": fitted_curve,
            "modeling_notes": catalytic_notes,
            "r0_assumption_note": r0_assumption_note,
            "n_catalytic_records": catalytic_result.get("n_records"),
            "catalytic_age_range": catalytic_result.get("age_range"),
        },
        "yearly_trend": yearly_trend,
        "age_groups": age_groups_out,
        "province_matrix": province_matrix,
        "status": status,
        "assessment": assessment,
        "life_expectancy_used": life_expectancy,
        "assumptions": assumptions or None,
    }


def _barrier_status_from_rate(rate: Optional[float], hit_target: Optional[float]) -> str:
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
    rate: Optional[float],
    hit_target: Optional[float],
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


async def get_approved_data_points(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    data_type: Optional[str] = None,
    offset: int = 0,
    limit: int = 200,
    sort_by: Optional[str] = None,
    sort_order: str = "desc",
) -> tuple[list[dict], int]:
    """获取所有审核通过的数据点（分页），用于数据分析模块展示"""
    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max,
                              data_type, review_status="approved")

    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # 获取分页数据，关联文献表获取标题
    query = query.add_columns(Literature.title).outerjoin(
        Literature, DataPoint.literature_id == Literature.id
    )

    # 动态排序
    sort_column_map = {
        "literature_title": Literature.title,
        "disease": DataPoint.disease,
        "province": DataPoint.province,
        "city": DataPoint.city,
        "age_group": DataPoint.age_group,
        "sample_size": DataPoint.sample_size,
        "data_type": DataPoint.data_type,
        "value": DataPoint.value,
        "unit": DataPoint.unit,
        "collection_year": DataPoint.collection_year,
        "method": DataPoint.method,
        "population": DataPoint.population,
    }
    if sort_by and sort_by in sort_column_map:
        col = sort_column_map[sort_by]
        if sort_order == "asc":
            query = query.order_by(col.asc().nullslast())
        else:
            query = query.order_by(col.desc().nullslast())
    else:
        query = query.order_by(DataPoint.collection_year.desc().nullslast(), DataPoint.created_at.desc())

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    items = []
    for r in rows:
        dp = r[0]  # DataPoint 对象
        literature_title = r[1]  # Literature.title
        items.append({
            "id": str(dp.id),
            "literature_id": str(dp.literature_id) if dp.literature_id else None,
            "literature_title": literature_title,
            "disease": dp.disease,
            "region": dp.region,
            "province": dp.province,
            "city": dp.city,
            "age_group": dp.age_group,
            "age_min": dp.age_min,
            "age_max": dp.age_max,
            "sample_size": dp.sample_size,
            "data_type": dp.data_type,
            "value": float(dp.value) if dp.value is not None else None,
            "unit": dp.unit,
            "ci_lower": float(dp.ci_lower) if dp.ci_lower is not None else None,
            "ci_upper": float(dp.ci_upper) if dp.ci_upper is not None else None,
            "method": dp.method,
            "assay": dp.assay,
            "population": dp.population,
            "collection_year": dp.collection_year,
            "confidence": dp.confidence,
            "review_status": dp.review_status,
            "created_at": dp.created_at.isoformat() if dp.created_at else None,
        })

    return items, total


async def get_approved_data_points_for_snapshot(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    data_type: Optional[str] = None,
    limit: int = 50000,
) -> list[dict]:
    """P2-1：获取审核通过的数据点（含文献元数据），用于公开数据集快照导出。

    与 get_approved_data_points 的区别：
    - 包含 estimate_type, source_page, is_grounded 字段
    - 关联 Literature 表获取 title/pub_year/journal
    - 不分页（一次性导出，limit 上限 50000 防止 OOM）
    - 默认只导出主估计（include_subgroups=False）
    """
    query = _build_base_query(
        disease, province, year_start, year_end, age_min, age_max, data_type,
        review_status="approved", include_subgroups=False,
    )
    query = query.add_columns(
        Literature.title, Literature.pub_year, Literature.journal
    ).outerjoin(Literature, DataPoint.literature_id == Literature.id)
    query = query.order_by(DataPoint.collection_year.desc().nullslast()).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    items = []
    for r in rows:
        dp = r[0]
        lit_title = r[1]
        lit_year = r[2]
        lit_journal = r[3]
        items.append({
            "disease": dp.disease,
            "province": dp.province,
            "city": dp.city,
            "data_type": dp.data_type,
            "value": float(dp.value) if dp.value is not None else None,
            "unit": dp.unit,
            "ci_lower": float(dp.ci_lower) if dp.ci_lower is not None else None,
            "ci_upper": float(dp.ci_upper) if dp.ci_upper is not None else None,
            "sample_size": dp.sample_size,
            "age_min": dp.age_min,
            "age_max": dp.age_max,
            "population": dp.population,
            "collection_year": dp.collection_year,
            "method": dp.method,
            "assay": dp.assay,
            "estimate_type": dp.estimate_type,
            "confidence": dp.confidence,
            "source_page": dp.source_page,
            "is_grounded": bool(dp.is_grounded),
            "literature_title": lit_title,
            "literature_year": lit_year,
            "literature_journal": lit_journal,
        })
    return items


# 中国 34 省级行政区基准列表（用于检测数据缺失）
CHINA_PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
    "台湾", "香港", "澳门",
]

# 疾病名称标准化统一使用 app.core.term_normalizer.normalize_disease
# 数据库中的 disease 字段已在入库时和迁移脚本中标准化为标准 key


async def get_data_gap_analysis(
    db: AsyncSession,
    disease: Optional[str] = None,
) -> dict:
    """数据覆盖度分析：统计各省份/城市×各年份的数据点分布，识别需要审核和补充的数据缺口。

    增强版（2026-08-05）：
    - 新增城市（地区）维度统计
    - 计算每个省×年和城市×年的**完整性评分**并按评分排序（高→低，完善的排在前面）
    - 区分"需要审核"和"需要补充"两种情况
    - 所有条目（包括已完善）都保留展示

    查询 ALL 数据点（含 pending/approved/rejected 全部状态），
    返回 overview / review_needed / supplement_needed / data_gaps
           / province_year_matrix / city_year_matrix。
    """
    # ---- 完整性评分常量 ----
    # 已审核数据点 ≥ 这个阈值 → 该组合被认为"完善"
    WELL_COVERED_THRESHOLD = 5
    # 每个已审核数据点贡献多少分（满分 100）
    MAX_APPROVED_SCORE = 70
    # 待审核惩罚系数：每个 pending 扣 2 分（最多 30 分）
    PENALTY_PER_PENDING = 2
    MAX_PENDING_PENALTY = 30

    def _calc_completeness(approved_ab: int, pending: int, total_years: int) -> float:
        """计算完整性评分（0-100）。

        规则（2026-08-16 起仅统计 A+B 高质量数据点）：
        - 基础分：min(approved_ab / WELL_COVERED_THRESHOLD, 1) × MAX_APPROVED_SCORE
        - 待审核惩罚：min(pending × PENALTY_PER_PENDING, MAX_PENDING_PENALTY)
        - 特殊：approved_ab=0 且 pending=0 但该省有数据（被循环到）→ 0 分（需补充）
        """
        base = min(approved_ab / WELL_COVERED_THRESHOLD, 1.0) * MAX_APPROVED_SCORE
        penalty = min(pending * PENALTY_PER_PENDING, MAX_PENDING_PENALTY)
        score = base - penalty
        # 如果 total_years=0（该组合无任何年份数据）→ 0 分
        if approved_ab + pending == 0:
            score = 0.0
        return max(0.0, round(score, 2))

    def _status_label(approved_ab: int, pending: int) -> str:
        """给省×年或城市×年组合打标签（approved_ab 仅计 A+B 高质量已通过数据点）。"""
        if approved_ab == 0 and pending == 0:
            return "need_supplement"   # 完全无数据，需要补充
        if approved_ab == 0:
            return "need_review"        # 有待审核但还没通过，需要先审核
        if approved_ab < WELL_COVERED_THRESHOLD:
            if pending > 0:
                return "need_both"       # 数据不足 + 有待审核
            return "need_supplement"     # 数据不足，需要补充
        if pending > 0:
            return "need_review"        # 已达标但仍有待审核
        return "well_covered"            # 完善

    # 基础查询：全部数据点（不限 review_status），同时取 city 与质量等级
    query = select(
        DataPoint.province,
        DataPoint.city,
        DataPoint.collection_year,
        DataPoint.disease,
        DataPoint.review_status,
        DataPoint.quality_grade,
        func.count(DataPoint.id).label("cnt"),
    ).group_by(
        DataPoint.province,
        DataPoint.city,
        DataPoint.collection_year,
        DataPoint.disease,
        DataPoint.review_status,
        DataPoint.quality_grade,
    )
    if disease:
        normalized_disease = normalize_disease(disease)
        query = query.where(DataPoint.disease == normalized_disease)

    result = await db.execute(query)
    rows = result.all()

    # ---- 1. 总览统计 ----
    total_dp = sum(r.cnt for r in rows)
    all_provinces: set[str] = set()
    all_cities: set[str] = set()
    all_diseases: set[str] = set()
    all_years: set[int] = set()
    status_counts = {"pending": 0, "approved": 0, "rejected": 0}
    for r in rows:
        if r.province:
            for p in r.province.split(";"):
                p = p.strip()
                if p:
                    all_provinces.add(p)
        if r.city:
            for c in r.city.replace("；", ";").split(";"):
                c = c.strip()
                if c:
                    all_cities.add(c)
        if r.disease:
            all_diseases.add(normalize_disease(r.disease))
        if r.collection_year:
            all_years.add(r.collection_year)
        if r.review_status in status_counts:
            status_counts[r.review_status] += r.cnt

    year_list = sorted(y for y in all_years if y is not None) if all_years else []

    # ---- 2. 需要审核 / 需要补充的组合（省×年×疾病 细粒度）----
    pyd_map: dict[tuple, dict] = {}
    for r in rows:
        if not r.province:
            continue
        prov = r.province.split(";")[0].strip()
        if not prov:
            continue
        normalized_dis = normalize_disease(r.disease) if r.disease else (r.disease or "未知")
        key = (prov, r.collection_year, normalized_dis)
        if key not in pyd_map:
            pyd_map[key] = {"pending": 0, "approved": 0, "approved_ab": 0, "rejected": 0, "total": 0}
        if r.review_status in pyd_map[key]:
            pyd_map[key][r.review_status] += r.cnt
            if r.review_status == "approved" and r.quality_grade in ("A", "B"):
                pyd_map[key]["approved_ab"] += r.cnt
        pyd_map[key]["total"] += r.cnt

    review_needed: list[dict] = []
    supplement_needed: list[dict] = []
    for (prov, year, dis), counts in pyd_map.items():
        status = _status_label(counts["approved_ab"], counts["pending"])
        base_item = {
            "province": prov,
            "year": year,
            "disease": dis,
            "pending_count": counts["pending"],
            "approved_count": counts["approved"],
            "approved_ab_count": counts["approved_ab"],
            "rejected_count": counts["rejected"],
            "total_count": counts["total"],
            "completeness_score": _calc_completeness(counts["approved_ab"], counts["pending"], len(year_list)),
            "status": status,
        }
        if status in ("need_review", "need_both"):
            review_needed.append(base_item)
        if status in ("need_supplement", "need_both"):
            supplement_needed.append(base_item)

    # review_needed: 按 pending_count 降序（待审越多越紧急）
    review_needed.sort(key=lambda x: (-x["pending_count"], -x["completeness_score"]))
    # supplement_needed: 按 approved 升序（approved=0 的排在最前），再按 pending 升序
    supplement_needed.sort(key=lambda x: (x["approved_count"], x["pending_count"], -x["total_count"]))

    # ---- 3. 数据缺失分析（按疾病分组，找出完全没有数据的省份）----
    disease_provinces: dict[str, set[str]] = {}
    for r in rows:
        if not r.disease or not r.province:
            continue
        normalized_dis = normalize_disease(r.disease)
        if normalized_dis not in disease_provinces:
            disease_provinces[normalized_dis] = set()
        for p in r.province.split(";"):
            p = p.strip()
            if p:
                disease_provinces[normalized_dis].add(p)

    data_gaps: list[dict] = []
    # 对 all_diseases（包含在 disease_provinces 中以及全部）都生成条目，
    # 保证数据"完全完整的疾病"（如麻疹）也能显示，方便用户一目了然。
    for dis in sorted(all_diseases):
        provs = disease_provinces.get(dis, set())
        missing = [p for p in CHINA_PROVINCES if p not in provs]
        if len(missing) == 0:
            # 完全覆盖 CHINA_PROVINCES → 直接记 100%
            coverage = 100.0
        else:
            denom = max(len(CHINA_PROVINCES), 1)
            coverage = round(len(provs) / denom * 100, 2)
        data_gaps.append({
            "disease": dis,
            "covered_provinces": sorted(provs),
            "missing_provinces": missing,
            "covered_count": len(provs),
            "missing_count": len(missing),
            "coverage_percent": min(coverage, 100.0),
        })
    # 越完善（缺失越少）越排在前面；缺失相同时覆盖省数越多越前，再按疾病名稳定排序
    data_gaps.sort(key=lambda x: (x["missing_count"], -x["covered_count"], x["disease"]))
    total_gap_combos = sum(g["missing_count"] for g in data_gaps)

    # ---- 4. 省份×年份矩阵（带完整性评分，按完整性降序）----
    py_matrix_map: dict[str, dict[int, dict]] = {}
    for r in rows:
        if not r.province:
            continue
        prov = r.province.split(";")[0].strip()
        if not prov:
            continue
        year = r.collection_year
        if prov not in py_matrix_map:
            py_matrix_map[prov] = {}
        if year not in py_matrix_map[prov]:
            py_matrix_map[prov][year] = {"total": 0, "pending": 0, "approved": 0, "approved_ab": 0}
        py_matrix_map[prov][year]["total"] += r.cnt
        if r.review_status == "pending":
            py_matrix_map[prov][year]["pending"] += r.cnt
        elif r.review_status == "approved":
            py_matrix_map[prov][year]["approved"] += r.cnt
            if r.quality_grade in ("A", "B"):
                py_matrix_map[prov][year]["approved_ab"] += r.cnt

    province_year_matrix: list[dict] = []
    for prov, year_data in py_matrix_map.items():
        total_for_prov = sum(yd["total"] for yd in year_data.values())
        pending_for_prov = sum(yd["pending"] for yd in year_data.values())
        approved_for_prov = sum(yd["approved"] for yd in year_data.values())
        approved_ab_for_prov = sum(yd["approved_ab"] for yd in year_data.values())
        # 为每个年份单元格追加 completeness_score 和 status
        years_formatted: dict[str, dict] = {}
        for y in sorted(y for y in year_data.keys() if y is not None):
            cell = year_data[y]
            years_formatted[str(y)] = {
                **cell,
                "completeness_score": _calc_completeness(cell["approved_ab"], cell["pending"], len(year_list)),
                "status": _status_label(cell["approved_ab"], cell["pending"]),
            }
        # 省份整体完整性评分（所有年份的加权）
        overall_score = _calc_completeness(approved_ab_for_prov, pending_for_prov, len(year_list))
        overall_status = _status_label(approved_ab_for_prov, pending_for_prov)
        province_year_matrix.append({
            "province": prov,
            "years": years_formatted,
            "total": total_for_prov,
            "pending": pending_for_prov,
            "approved": approved_for_prov,
            "approved_ab": approved_ab_for_prov,
            "completeness_score": overall_score,
            "status": overall_status,
        })

    # 按完整性评分降序（完善的排在前面），评分相同按 total 降序
    province_year_matrix.sort(key=lambda x: (-x["completeness_score"], -x["total"]))

    # ---- 5. 城市×年份矩阵（新增地区维度）----
    cy_matrix_map: dict[tuple[str, str], dict[int, dict]] = {}
    for r in rows:
        if not r.province or not r.city:
            continue
        prov = r.province.split(";")[0].strip()
        city = r.city.replace("；", ";").split(";")[0].strip()
        if not prov or not city:
            continue
        year = r.collection_year
        key = (prov, city)
        if key not in cy_matrix_map:
            cy_matrix_map[key] = {}
        if year not in cy_matrix_map[key]:
            cy_matrix_map[key][year] = {"total": 0, "pending": 0, "approved": 0, "approved_ab": 0}
        cy_matrix_map[key][year]["total"] += r.cnt
        if r.review_status == "pending":
            cy_matrix_map[key][year]["pending"] += r.cnt
        elif r.review_status == "approved":
            cy_matrix_map[key][year]["approved"] += r.cnt
            if r.quality_grade in ("A", "B"):
                cy_matrix_map[key][year]["approved_ab"] += r.cnt

    city_year_matrix: list[dict] = []
    for (prov, city), year_data in cy_matrix_map.items():
        total_city = sum(yd["total"] for yd in year_data.values())
        pending_city = sum(yd["pending"] for yd in year_data.values())
        approved_city = sum(yd["approved"] for yd in year_data.values())
        approved_ab_city = sum(yd["approved_ab"] for yd in year_data.values())
        years_formatted: dict[str, dict] = {}
        for y in sorted(y for y in year_data.keys() if y is not None):
            cell = year_data[y]
            years_formatted[str(y)] = {
                **cell,
                "completeness_score": _calc_completeness(cell["approved_ab"], cell["pending"], len(year_list)),
                "status": _status_label(cell["approved_ab"], cell["pending"]),
            }
        overall_score = _calc_completeness(approved_ab_city, pending_city, len(year_list))
        overall_status = _status_label(approved_ab_city, pending_city)
        city_year_matrix.append({
            "province": prov,
            "city": city,
            "years": years_formatted,
            "total": total_city,
            "pending": pending_city,
            "approved": approved_city,
            "approved_ab": approved_ab_city,
            "completeness_score": overall_score,
            "status": overall_status,
        })

    # 城市矩阵同样按完整性降序
    city_year_matrix.sort(key=lambda x: (-x["completeness_score"], -x["total"]))

    # ---- 6. 概览统计（附加）----
    # 统计"完善"、"待审核"、"需补充"的省×年组合数
    status_counts_combos = {"well_covered": 0, "need_review": 0, "need_supplement": 0, "need_both": 0}
    for row in province_year_matrix:
        for cell in row["years"].values():
            status_counts_combos[cell["status"]] = status_counts_combos.get(cell["status"], 0) + 1

    overview = {
        "total_data_points": total_dp,
        "total_provinces": len(all_provinces),
        "total_cities": len(all_cities),
        "total_diseases": len(all_diseases),
        "year_range": [year_list[0], year_list[-1]] if year_list else None,
        "years": year_list,
        "pending_count": status_counts["pending"],
        "approved_count": status_counts["approved"],
        "rejected_count": status_counts["rejected"],
        "total_gap_combos": total_gap_combos,
        # 新增：组合状态统计
        "combo_status_counts": status_counts_combos,
        # 新增：阈值说明
        "well_covered_threshold": WELL_COVERED_THRESHOLD,
    }

    return {
        "overview": overview,
        "review_needed": review_needed,
        "supplement_needed": supplement_needed,
        "data_gaps": data_gaps,
        "province_year_matrix": province_year_matrix,
        "city_year_matrix": city_year_matrix,
    }


# ============================================================
# P0: FOI（感染力 Force of Infection）+ 群体免疫阈值分析
# 纯分析逻辑，不新增数据库字段，数据全部来自已审核的 seroprevalence 数据点
# ============================================================

# ---- 流行病学参数 ----
# 平均寿命（年），用于 R0 = λ × L（Catalitic 模型近似）
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


def _calc_foi_from_sp(seroprevalence: float, age_mid: float) -> Optional[float]:
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


def _midpoint_age(age_min: Optional[int], age_max: Optional[int]) -> Optional[float]:
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
    logger.debug(f"[FOI] _midpoint_age: age_min和age_max均为None → None")
    return None


def _calc_hit_from_r0(r0: float) -> float:
    """群体免疫阈值 HIT = 1 - 1/R0，转成百分比（0-100）。"""
    if r0 is None or r0 <= 1.0:
        logger.debug(f"[FOI] _calc_hit_from_r0: r0={r0} (≤1或None) → HIT=0.0%")
        return 0.0
    hit = round((1.0 - 1.0 / r0) * 100.0, 2)
    logger.debug(f"[FOI] _calc_hit_from_r0: r0={r0} → HIT={hit}%")
    return hit


def _calc_r0_from_foi(foi_avg: float, life_exp: float = DEFAULT_LIFE_EXPECTANCY) -> Optional[float]:
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
        records.append((float(mid), int(round(p * ss)), ss))
    return records


def _catalytic_r0_hit(catalytic: dict, dis_key: Optional[str], life_exp: float = DEFAULT_LIFE_EXPECTANCY,
                      mu_fixed: Optional[float] = None) -> dict:
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
    r0_to_hit: Optional[float] = None
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
    foi_hit: Optional[float],
    who_threshold: Optional[float],
    literature_hit: Optional[float],
    dis_key: Optional[str],
    hit_source_override: Optional[str] = None,
) -> tuple[Optional[float], str]:
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


async def get_foi_analysis(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    life_expectancy: float = 75.0,
    seroreversion_mu: Optional[float] = None,
    hit_source_override: Optional[str] = None,
) -> dict:
    """P0-1: FOI（感染力）+ 群体免疫阈值综合分析。

    纯分析逻辑（无 DB 变更），输入：已审核通过的 seroprevalence 数据点。
    步骤：
      1. 按疾病聚合（如 disease=None 则按疾病逐一计算）
      2. 对每个年龄组，用催化模型 λ = -ln(1-SP)/age 估算 FOI
      3. 计算加权平均 FOI（按 sample_size 加权）
      4. 反推 R0 估计值：R0 ≈ λ × L
      5. 计算 HIT：HIT = 1 - 1/R0，并与 WHO 阈值对比
      6. 按省份 × 疾病输出 FOI 热力矩阵
    """
    # 仅取已审核通过的 seroprevalence 主估计数据点（含 sample_size + 可计算年龄中点）
    query = _build_base_query(
        disease, province, year_start, year_end,
        age_min=None, age_max=None,
        data_type="seroprevalence",
        review_status="approved",
        include_subgroups=False,
    )
    result = await db.execute(query)
    rows: list[DataPoint] = result.scalars().all()

    logger.info(
        f"[FOI] get_foi_analysis 开始: disease={disease}, province={province}, "
        f"year_start={year_start}, year_end={year_end}, "
        f"查询到 {len(rows)} 条已审核 seroprevalence 数据点"
    )

    # 收集本次分析使用的显式参数假设（用于响应透明展示）
    assumptions = {}
    if life_expectancy != 75.0:
        assumptions["life_expectancy"] = life_expectancy
    if seroreversion_mu:
        assumptions["seroreversion_mu"] = seroreversion_mu
    if hit_source_override:
        assumptions["hit_source_override"] = hit_source_override

    if not rows:
        return {
            "disease": disease,
            "total_data_points": 0,
            "per_disease_results": [],
            "summary": {
                "disease": disease,
                "total_data_points": 0,
                "overall_weighted_positivity_rate": None,
                "weighted_avg_foi_per_year": None,
                "estimated_r0_from_foi": None,
                "r0_reference": {"typical": None, "range_low": None, "range_high": None},
                "hit_from_foi_percent": None,
                "hit_from_reference_r0_percent": None,
                "who_threshold_percent": None,
                "hit_target_used_percent": None,
                "hit_target_source": "none",
                "herd_immunity_status": "no_data",
                "life_expectancy_used": life_expectancy,
                "models": [],
                "recommended_model": None,
                "recommended_params": None,
                "fitted_curve": [],
                "modeling_notes": [],
                "r0_assumption_note": None,
                "n_catalytic_records": 0,
                "catalytic_age_range": [None, None],
            },
            "province_foi_matrix": [],
            "notes": ["无已审核通过的 seroprevalence 数据，无法进行 FOI 分析"],
            "assumptions": assumptions or None,
        }

    # 按疾病分组（若传了 disease 则只有一个组）
    disease_rows: dict[str, list[DataPoint]] = {}
    for r in rows:
        dis = r.disease or "未知"
        normalized = normalize_disease(dis)
        dis_key = normalized or dis
        if dis_key not in disease_rows:
            disease_rows[dis_key] = []
        disease_rows[dis_key].append(r)

    logger.info(f"[FOI] 按疾病分组: {len(disease_rows)} 种疾病 → {list(disease_rows.keys())}")
    for dk, drs in disease_rows.items():
        sp_count = sum(1 for r in drs if r.value is not None)
        age_count = sum(1 for r in drs if _midpoint_age(r.age_min, r.age_max) is not None)
        logger.info(f"[FOI]   疾病={dk}: 总数据点={len(drs)}, 有value={sp_count}, 可算年龄中点={age_count}")

    per_disease_results: list[dict] = []
    province_foi_matrix: list[dict] = []
    notes: list[str] = []

    for dis_key, dis_rows in disease_rows.items():
        # --- 1) FOI 按年龄组汇总 ---
        # 聚合到 AGE_GROUPS 的 5 个标准桶
        age_buckets: dict[str, dict] = {g[0]: {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []} for g in AGE_GROUPS}
        age_buckets["其他"] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}

        for r in dis_rows:
            if r.value is None:
                continue
            sp = float(r.value)
            ss = r.sample_size or 0
            label = _get_age_group_label(r.age_min, r.age_max)
            if label is None:
                label = "其他"
            if label not in age_buckets:
                age_buckets[label] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}

            age_mid = _midpoint_age(r.age_min, r.age_max)
            foi = _calc_foi_from_sp(sp, age_mid) if age_mid is not None else None

            bucket = age_buckets[label]
            if ss and ss > 0:
                bucket["sp_sum"] += sp * ss
                bucket["sample_sum"] += ss
            bucket["dp_count"] += 1
            if foi is not None:
                bucket["foi_values"].append((foi, ss or 1))  # (值, 权重)

        foi_by_age: list[dict] = []
        # 标准 5 个年龄组
        for age_label, lo, hi in AGE_GROUPS:
            bucket = age_buckets[age_label]
            if bucket["dp_count"] == 0:
                continue
            w_sp = round(bucket["sp_sum"] / bucket["sample_sum"], 2) if bucket["sample_sum"] > 0 else None
            if bucket["foi_values"]:
                fv_total_w = sum(w for _, w in bucket["foi_values"])
                w_foi = round(sum(v * w for v, w in bucket["foi_values"]) / fv_total_w, 6) if fv_total_w > 0 else None
            else:
                w_foi = None
            logger.info(
                f"[FOI] [{dis_key}] 年龄组={age_label}: dp_count={bucket['dp_count']}, "
                f"samples={bucket['sample_sum']}, w_sp={w_sp}%, w_foi={w_foi}/年, "
                f"foi_values_count={len(bucket['foi_values'])}"
            )
            foi_by_age.append({
                "age_group": age_label,
                "age_mid_approx": (lo + hi) / 2.0,
                "data_point_count": bucket["dp_count"],
                "total_samples": bucket["sample_sum"],
                "weighted_positivity_rate": w_sp,
                "weighted_avg_foi_per_year": w_foi,
            })
        # 追加"其他"桶（标准年龄组之外的数据），避免数据被丢弃
        other_bucket = age_buckets.get("其他")
        if other_bucket and other_bucket["dp_count"] > 0:
            w_sp = round(other_bucket["sp_sum"] / other_bucket["sample_sum"], 2) if other_bucket["sample_sum"] > 0 else None
            if other_bucket["foi_values"]:
                fv_total_w = sum(w for _, w in other_bucket["foi_values"])
                w_foi = round(sum(v * w for v, w in other_bucket["foi_values"]) / fv_total_w, 6) if fv_total_w > 0 else None
            else:
                w_foi = None
            foi_by_age.append({
                "age_group": "其他",
                "age_mid_approx": 30.0,  # 经验中位年龄
                "data_point_count": other_bucket["dp_count"],
                "total_samples": other_bucket["sample_sum"],
                "weighted_positivity_rate": w_sp,
                "weighted_avg_foi_per_year": w_foi,
            })

        # --- 2) 全年龄段加权平均 FOI（旧口径，仅作催化模型失败时的回退）---
        # 取每个年龄组的 foi 汇总到整体
        all_foi_tuples: list[tuple[float, int]] = []
        for f in foi_by_age:
            if f["weighted_avg_foi_per_year"] is not None and f["total_samples"] > 0:
                all_foi_tuples.append((f["weighted_avg_foi_per_year"], f["total_samples"]))
        if all_foi_tuples:
            w_total = sum(w for _, w in all_foi_tuples)
            legacy_foi = round(
                sum(v * w for v, w in all_foi_tuples) / w_total, 6
            ) if w_total > 0 else None
        else:
            legacy_foi = None

        # --- 2.5) 催化模型族 MLE 拟合（新引擎）---
        # 用 (age_mid, x, n) 拟合 M1/M2/M3，输出模型比较 + 推荐模型 + 拟合曲线
        catalytic_records = _build_catalytic_records(dis_rows)
        catalytic_result = fit_catalytic_models(catalytic_records, mu_fixed=seroreversion_mu)
        models_out = catalytic_result.get("models") or []
        recommended_model = catalytic_result.get("recommended_model")
        recommended_params = catalytic_result.get("recommended_params") or {}
        fitted_curve = catalytic_result.get("fitted_curve") or []
        catalytic_notes = catalytic_result.get("modeling_notes") or []

        # 理论修正：R0/HIT 来源解析（仅 M1 + 地方性/终生免疫 才用 R0=λ·L；显式 μ 强制重算）
        r0_hit_info = _catalytic_r0_hit(catalytic_result, dis_key, life_exp=life_expectancy,
                                        mu_fixed=seroreversion_mu)
        rec_foi = r0_hit_info["foi_avg"]
        r0_to_hit = r0_hit_info["r0_to_hit"]
        literature_hit = r0_hit_info["literature_hit"]
        r0_assumption_note = r0_hit_info["r0_assumption_note"]

        # 兼容旧字段：foi/r0 取 recommended_model 参数重算；无催化结果时回退旧加权平均
        weighted_avg_foi = rec_foi if rec_foi is not None else legacy_foi
        estimated_r0 = r0_to_hit

        logger.info(
            f"[FOI] [{dis_key}] 催化模型: records={len(catalytic_records)}, "
            f"recommended={recommended_model}, foi_avg={weighted_avg_foi}/年, "
            f"r0_to_hit={r0_to_hit}, legacy_foi={legacy_foi}"
        )

        # --- 3) R0 估计（催化模型推荐参数）+ 文献参考 ---
        r0_ref = R0_REFERENCE.get(dis_key)  # (typical, low, high)

        logger.info(
            f"[FOI] [{dis_key}] R0估算: estimated_r0_from_foi={estimated_r0}, "
            f"r0_reference={r0_ref}"
        )

        # 如果 FOI 推出来的 R0 严重超出文献范围，给出 note
        if r0_ref and estimated_r0 is not None:
            typical, rlow, rhigh = r0_ref
            if estimated_r0 < rlow * 0.3:
                notes.append(f"[{dis_key}] 基于 FOI 的 R0 估计（{estimated_r0}）显著低于文献参考区间 [{rlow}, {rhigh}]，可能是 SP 偏低或年龄覆盖不全。")
                logger.warning(f"[FOI] [{dis_key}] R0估计({estimated_r0})显著低于文献参考[{rlow},{rhigh}]")
            elif estimated_r0 > rhigh * 2:
                notes.append(f"[{dis_key}] 基于 FOI 的 R0 估计（{estimated_r0}）显著高于文献参考区间 [{rlow}, {rhigh}]，可能受年龄分组偏差影响。")
                logger.warning(f"[FOI] [{dis_key}] R0估计({estimated_r0})显著高于文献参考[{rlow},{rhigh}]")

        # --- 4) HIT（群体免疫阈值）两种估计 ---
        # 方案 A：FOI → R0 → HIT（仅 M1 + 地方性/终生免疫 有值，理论修正）
        foi_hit_percent = _calc_hit_from_r0(estimated_r0) if estimated_r0 is not None else None
        # 方案 B：文献 R0（typical）→ HIT
        who_threshold = WHO_THRESHOLDS.get(dis_key)

        logger.info(
            f"[FOI] [{dis_key}] HIT计算: hit_from_foi={foi_hit_percent}%, "
            f"hit_from_reference_r0={literature_hit}%, who_threshold={who_threshold}%"
        )

        # --- 5) 群体免疫状态判定 ---
        # HIT 阈值优先级链不变：FOI 估算 > WHO > 文献 R0（hit_source 扩展 mle_foi 标签）
        hit_target, hit_source = _resolve_hit_target(
            foi_hit_percent, who_threshold, literature_hit, dis_key,
            hit_source_override=hit_source_override,
        )

        # 用加权平均 SP 与 HIT 对比
        overall_sp = None
        sp_valid = [(r.value, r.sample_size or 1) for r in dis_rows if r.value is not None]
        if sp_valid:
            w_sum = sum(w for _, w in sp_valid)
            overall_sp = round(sum(v * w for v, w in sp_valid) / w_sum, 2) if w_sum > 0 else None

        if overall_sp is not None and hit_target is not None:
            if overall_sp >= hit_target:
                herd_status = "reached"        # 已达群体免疫
            elif overall_sp >= hit_target - 10:
                herd_status = "near"           # 接近
            else:
                herd_status = "not_reached"    # 未达到
        else:
            herd_status = "undetermined"

        logger.info(
            f"[FOI] [{dis_key}] 群体免疫判定: overall_sp={overall_sp}%, "
            f"hit_target={hit_target}% (来源={hit_source}), "
            f"herd_status={herd_status}"
        )

        # --- 6) 省份 × 疾病 FOI 矩阵 ---
        prov_map: dict[str, dict] = {}
        for r in dis_rows:
            if r.value is None:
                continue
            prov_raw = r.province or "未知"
            for p in prov_raw.split(";"):
                p = p.strip()
                if not p:
                    p = "未知"
                if p not in prov_map:
                    prov_map[p] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}
                pm = prov_map[p]
                sp = float(r.value)
                ss = r.sample_size or 0
                if ss and ss > 0:
                    pm["sp_sum"] += sp * ss
                    pm["sample_sum"] += ss
                pm["dp_count"] += 1
                age_mid = _midpoint_age(r.age_min, r.age_max)
                foi = _calc_foi_from_sp(sp, age_mid) if age_mid is not None else None
                if foi is not None:
                    pm["foi_values"].append((foi, ss or 1))

        for prov_name, pm in prov_map.items():
            if pm["dp_count"] == 0:
                continue
            w_sp = round(pm["sp_sum"] / pm["sample_sum"], 2) if pm["sample_sum"] > 0 else None
            if pm["foi_values"]:
                fw = sum(w for _, w in pm["foi_values"])
                prov_foi = round(sum(v * w for v, w in pm["foi_values"]) / fw, 6) if fw > 0 else None
            else:
                prov_foi = None
            # 省域 HIT 达标判定
            p_hit = "undetermined"
            if w_sp is not None and hit_target is not None:
                if w_sp >= hit_target:
                    p_hit = "reached"
                elif w_sp >= hit_target - 10:
                    p_hit = "near"
                else:
                    p_hit = "not_reached"
            province_foi_matrix.append({
                "disease": dis_key,
                "province": prov_name,
                "data_point_count": pm["dp_count"],
                "total_samples": pm["sample_sum"],
                "weighted_positivity_rate": w_sp,
                "weighted_avg_foi_per_year": prov_foi,
                "herd_immunity_status": p_hit,
                "hit_target_percent": hit_target,
            })
            logger.info(
                f"[FOI] [{dis_key}] 省份={prov_name}: dp={pm['dp_count']}, "
                f"samples={pm['sample_sum']}, w_sp={w_sp}%, foi={prov_foi}/年, "
                f"herd_status={p_hit}"
            )

        logger.info(f"[FOI] [{dis_key}] 疾病分析完成: 年龄组数={len(foi_by_age)}, 省份数={len(prov_map)}")

        summary_block = {
            "disease": dis_key,
            "total_data_points": len(dis_rows),
            "overall_weighted_positivity_rate": overall_sp,
            "weighted_avg_foi_per_year": weighted_avg_foi,
            "estimated_r0_from_foi": estimated_r0,
            "r0_reference": {
                "typical": r0_ref[0] if r0_ref else None,
                "range_low": r0_ref[1] if r0_ref else None,
                "range_high": r0_ref[2] if r0_ref else None,
            },
            "hit_from_foi_percent": foi_hit_percent,
            "hit_from_reference_r0_percent": literature_hit,
            "who_threshold_percent": who_threshold,
            "hit_target_used_percent": hit_target,
            "hit_target_source": hit_source,
            "herd_immunity_status": herd_status,
            "life_expectancy_used": life_expectancy,
            "assumptions": assumptions or None,
            # 新增：催化模型族 MLE 拟合 + 模型比较 + 理论修正
            "models": models_out,
            "recommended_model": recommended_model,
            "recommended_params": recommended_params,
            "fitted_curve": fitted_curve,
            "modeling_notes": catalytic_notes,
            "r0_assumption_note": r0_assumption_note,
            "n_catalytic_records": catalytic_result.get("n_records"),
            "catalytic_age_range": catalytic_result.get("age_range"),
        }

        per_disease_results.append({
            "disease": dis_key,
            "summary": summary_block,
            "foi_by_age_group": foi_by_age,
            "models": models_out,
            "recommended_model": recommended_model,
            "fitted_curve": fitted_curve,
            "modeling_notes": catalytic_notes,
            "r0_assumption_note": r0_assumption_note,
        })

    # 如果只传了一个疾病，把 summary 提升到顶层
    top_disease_summary = per_disease_results[0]["summary"] if len(per_disease_results) == 1 else None

    return {
        "disease": disease,
        "total_data_points": len(rows),
        "per_disease_results": per_disease_results,
        "summary": top_disease_summary or {
            "num_diseases_analyzed": len(per_disease_results),
            "diseases": sorted(disease_rows.keys()),
        },
        "province_foi_matrix": province_foi_matrix,
        "notes": notes if notes else [],
        "assumptions": assumptions or None,
    }


# ============================================================
# P1: 疫苗效果 (VE / Vaccine Effectiveness) + 接种率 (Coverage) 分析
# 策略：
#   1. 不新增 DB 字段，数据来自已有的 seroprevalence 数据点（人群标签）
#   2. 若 population 字段包含"已接种"/"未接种"/"接种过"/"无免疫史"等关键字，
#      则按接种状态拆分，计算 VE = 1 - (SP_vax / SP_unvax)
#   3. 若没有分亚组数据，提供接种率推算（screening method）需要的组件
#      以及参考接种率（按疾病-省份，默认查 NIP 覆盖预设表）
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


def _calc_ve_from_sp(sp_vax: float, sp_unvax: float) -> Optional[float]:
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


def _get_reference_coverage(disease: str, province: Optional[str]) -> Optional[float]:
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
) -> Optional[float]:
    """粗略反推接种率：若假设 HIT = herd immunity threshold = coverage × VE_induced，
    则 coverage_implied ≈ overall_sp / hit_target（当整体 SP 被视为疫苗诱导+自然感染的混合时，
    此近似偏保守，仅用于给出参考值）。"""
    if hit_target is None or hit_target <= 0 or overall_sp is None:
        logger.debug(f"[VE] _implied_coverage_from_hit 返回None: overall_sp={overall_sp}, hit_target={hit_target}")
        return None
    impl = min(100.0, round(overall_sp / hit_target * 100.0, 2))
    logger.info(f"[VE] _implied_coverage_from_hit: overall_sp={overall_sp}%, hit_target={hit_target}% → implied_coverage={impl}%")
    return impl


async def get_vaccine_analysis(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
) -> dict:
    """P1: 疫苗效果 (VE) + 接种率综合分析。

    计算逻辑：
      1. 按疾病-省份聚合所有已审核的 seroprevalence 数据点
      2. 将数据点按接种状态拆分（已接种/未接种），如果两个亚组都有 SP，则计算 VE
      3. 计算「整体 SP」，并结合 FOI 模块的 HIT 反推隐含接种率
      4. 叠加 NIP 参考接种率表，输出省-疾病覆盖矩阵

    不新增 DB 字段；若拆分不出接种亚组，VE 字段返回 null 并在 notes 中说明。
    """
    query = _build_base_query(
        disease, province, year_start, year_end,
        age_min=None, age_max=None,
        data_type="seroprevalence",
        review_status="approved",
        include_subgroups=True,   # VE 计算可能依赖子估计的细分人群
    )
    result = await db.execute(query)
    rows: list = result.scalars().all()

    logger.info(
        f"[VE] get_vaccine_analysis 开始: disease={disease}, province={province}, "
        f"year_start={year_start}, year_end={year_end}, "
        f"查询到 {len(rows)} 条已审核 seroprevalence 数据点 (含子估计)"
    )

    notes: list[str] = []
    if not rows:
        return {
            "disease": disease,
            "province": province,
            "total_data_points": 0,
            "per_disease_results": [],
            "summary": {
                "num_diseases_analyzed": 0,
                "diseases": [],
            },
            "province_coverage_matrix": [],
            "notes": ["无已审核通过的数据点，无法进行疫苗分析"],
        }

    # ---- 先复用 FOI 模块计算 HIT（轻量：只取 summary 部分，用已实现的 helper 直接计算）----
    # 为了避免循环和重复计算，这里用「独立版本」计算每个疾病的 HIT：
    # 用文献 R0 估计计算（若没有则用 WHO 阈值替代），避免再跑 FOI 全流程

    # 按疾病分组
    disease_rows: dict[str, list] = {}
    for r in rows:
        dis = getattr(r, "disease", None) or "未知"
        norm = normalize_disease(dis)
        key = norm or dis
        if key not in disease_rows:
            disease_rows[key] = []
        disease_rows[key].append(r)

    logger.info(f"[VE] 按疾病分组: {len(disease_rows)} 种疾病 → {list(disease_rows.keys())}")

    per_disease_results: list[dict] = []
    province_coverage_matrix: list[dict] = []

    for dis_key, dis_rows in disease_rows.items():
        # 整体 SP（加权）
        sp_list = [(float(r.value), r.sample_size or 1) for r in dis_rows if r.value is not None]
        if sp_list:
            wsum = sum(w for _, w in sp_list)
            overall_sp = round(sum(v * w for v, w in sp_list) / wsum, 2) if wsum > 0 else None
        else:
            overall_sp = None

        logger.info(f"[VE] [{dis_key}] 整体SP计算: 有效数据点={len(sp_list)}/{len(dis_rows)}, overall_sp={overall_sp}%")

        # ---- VE 计算（接种 vs 未接种拆分）----
        vaxxed, unvaxxed = _split_vax_unvax(dis_rows)
        ve_result: dict | None = None
        if vaxxed and unvaxxed:
            def _wsp(group):
                lst = [(float(r.value), r.sample_size or 1) for r in group if r.value is not None]
                if not lst:
                    return None
                sw = sum(w for _, w in lst)
                return round(sum(v * w for v, w in lst) / sw, 2) if sw > 0 else None
            sp_v = _wsp(vaxxed)
            sp_u = _wsp(unvaxxed)
            logger.info(
                f"[VE] [{dis_key}] 亚组SP: 已接种组 sp_v={sp_v}% (n={sum(r.sample_size or 0 for r in vaxxed)}), "
                f"未接种组 sp_u={sp_u}% (n={sum(r.sample_size or 0 for r in unvaxxed)})"
            )
            ve_percent = _calc_ve_from_sp(sp_v, sp_u)
            total_n = sum(r.sample_size or 0 for r in vaxxed) + sum(r.sample_size or 0 for r in unvaxxed)
            ve_result = {
                "vaxxed_points": len(vaxxed),
                "unvaxxed_points": len(unvaxxed),
                "vaxxed_total_samples": sum(r.sample_size or 0 for r in vaxxed),
                "unvaxxed_total_samples": sum(r.sample_size or 0 for r in unvaxxed),
                "vaxxed_weighted_sp": sp_v,
                "unvaxxed_weighted_sp": sp_u,
                "ve_infection_percent": ve_percent,  # 保护性 VE（可能为 None）
                "interpretation": (
                    f"接种组阳性率 {sp_v}% vs 未接种组 {sp_u}%；"
                    + (f"VE(against infection)≈{ve_percent}%" if ve_percent is not None
                       else "接种组阳性率≥未接种组，属疫苗诱导抗体（非保护性维度），无法用该公式算 VE")
                ) if sp_v is not None and sp_u is not None else None,
            }
            logger.info(f"[VE] [{dis_key}] VE结果: ve_percent={ve_percent}%, total_n={total_n}")
        else:
            if len(vaxxed) == 0 and len(unvaxxed) == 0:
                notes.append(
                    f"[{dis_key}] 没有找到明确标注「已接种/未接种」亚组的数据点，无法直接计算 VE。"
                    "建议在文献审核时补充人群标签，或通过子估计（estimate_type='subgroup'）拆分接种状态。"
                )
                logger.info(f"[VE] [{dis_key}] 未找到接种/未接种亚组数据点，VE无法计算")
            elif len(vaxxed) == 0:
                logger.info(f"[VE] [{dis_key}] 仅有未接种组({len(unvaxxed)}条)，缺少已接种组，VE无法计算")
            elif len(unvaxxed) == 0:
                logger.info(f"[VE] [{dis_key}] 仅有已接种组({len(vaxxed)}条)，缺少未接种组，VE无法计算")

        # ---- 接种率推算 ----
        r0_ref = R0_REFERENCE.get(dis_key)
        hit_percent = _calc_hit_from_r0(r0_ref[0]) if r0_ref else WHO_THRESHOLDS.get(dis_key)
        implied_cov = _implied_coverage_from_hit(overall_sp, hit_percent)

        ref_cov = _get_reference_coverage(dis_key, None)  # 国家级先

        logger.info(
            f"[VE] [{dis_key}] 接种率推算: hit_percent={hit_percent}% "
            f"(来源={'r0_ref' if r0_ref else 'who'}), "
            f"implied_cov={implied_cov}%, nip_ref_national={ref_cov}%"
        )

        per_disease_results.append({
            "disease": dis_key,
            "total_data_points": len(dis_rows),
            "overall_weighted_sp": overall_sp,
            "herd_immunity_target_percent": hit_percent,
            "reference_r0_typical": r0_ref[0] if r0_ref else None,
            "ve_result": ve_result,
            "coverage": {
                "nip_reference_national_percent": ref_cov,
                "implied_from_seroprevalence_percent": implied_cov,
            },
        })

        # ---- 省 × 疾病覆盖率矩阵 ----
        # 先按省聚合
        prov_map: dict[str, list] = {}
        for r in dis_rows:
            p_raw = getattr(r, "province", None) or "未知"
            for p in p_raw.split(";"):
                p = p.strip() or "未知"
                if p not in prov_map:
                    prov_map[p] = []
                prov_map[p].append(r)

        for prov_name, prov_rows in prov_map.items():
            sp_l = [(float(r.value), r.sample_size or 1) for r in prov_rows if r.value is not None]
            if sp_l:
                sw = sum(w for _, w in sp_l)
                psp = round(sum(v * w for v, w in sp_l) / sw, 2) if sw > 0 else None
            else:
                psp = None
            # 省级别 VE（同样尝试拆分）
            pv, pu = _split_vax_unvax(prov_rows)
            prov_ve = None
            if pv and pu:
                def _wsp2(group):
                    lst = [(float(r.value), r.sample_size or 1) for r in group if r.value is not None]
                    if not lst: return None
                    sw2 = sum(w for _, w in lst)
                    return round(sum(v * w for v, w in lst) / sw2, 2) if sw2 > 0 else None
                prov_ve = _calc_ve_from_sp(_wsp2(pv), _wsp2(pu))
            prov_nip = _get_reference_coverage(dis_key, prov_name) or ref_cov
            p_impl = _implied_coverage_from_hit(psp, hit_percent)
            # 达标判定：implied_cov >= NIP 参考 → on_track
            status = "undetermined"
            if p_impl is not None and prov_nip is not None:
                if p_impl >= prov_nip:
                    status = "on_track"
                elif p_impl >= prov_nip - 10:
                    status = "near"
                else:
                    status = "below"
            province_coverage_matrix.append({
                "disease": dis_key,
                "province": prov_name,
                "data_point_count": len(prov_rows),
                "weighted_sp_percent": psp,
                "ve_infection_percent": prov_ve,
                "nip_reference_coverage_percent": prov_nip,
                "implied_coverage_from_sp_percent": p_impl,
                "coverage_status": status,
            })

    top_summary = per_disease_results[0] if len(per_disease_results) == 1 else None

    return {
        "disease": disease,
        "province": province,
        "total_data_points": len(rows),
        "summary": top_summary or {
            "num_diseases_analyzed": len(per_disease_results),
            "diseases": sorted(disease_rows.keys()),
        },
        "per_disease_results": per_disease_results,
        "province_coverage_matrix": province_coverage_matrix,
        "notes": notes,
    }


async def get_coverage_review_stats(
    db: AsyncSession,
    disease: Optional[str] = None,
) -> dict:
    """按疾病维度统计：数据点数、样本量、审核状态(approved/pending/rejected)与通过率。

    查询全部数据点（不过滤 review_status，以便统计各审核状态），
    在 Python 层用 normalize_disease 归一化疾病名后按疾病聚合。
    返回 {"overview": {...}, "diseases": [...]}，默认按 pending_points 降序、
    其次 total_points 降序排序。
    """
    from collections import defaultdict

    query = select(
        DataPoint.id,
        DataPoint.disease,
        DataPoint.review_status,
        DataPoint.sample_size,
    )
    if disease:
        query = query.where(DataPoint.disease == normalize_disease(disease))

    result = await db.execute(query)
    rows = result.all()

    # ---- Python 层按疾病聚合 ----
    # 每个疾病维护：total & 各状态的 points / samples
    agg: dict[str, dict] = defaultdict(lambda: {
        "total_points": 0,
        "total_samples": 0,
        "approved_points": 0,
        "approved_samples": 0,
        "pending_points": 0,
        "pending_samples": 0,
        "rejected_points": 0,
        "rejected_samples": 0,
    })

    for r in rows:
        normalized = normalize_disease(r.disease) if r.disease else (r.disease or "未知")
        d = agg[normalized]
        d["total_points"] += 1
        d["total_samples"] += r.sample_size or 0
        status = r.review_status if r.review_status in ("approved", "pending", "rejected") else "pending"
        d[f"{status}_points"] += 1
        d[f"{status}_samples"] += r.sample_size or 0

    # ---- 组装疾病列表 ----
    diseases: list[dict] = []
    for dis, d in agg.items():
        total = d["total_points"]
        approval_rate = (d["approved_points"] / total) if total else 0.0
        diseases.append({
            "disease": dis,
            "total_points": d["total_points"],
            "total_samples": d["total_samples"],
            "approved_points": d["approved_points"],
            "approved_samples": d["approved_samples"],
            "pending_points": d["pending_points"],
            "pending_samples": d["pending_samples"],
            "rejected_points": d["rejected_points"],
            "rejected_samples": d["rejected_samples"],
            "approval_rate": round(approval_rate, 4),
        })

    # 默认排序：pending_points 降序 > total_points 降序 > 疾病名升序（稳定）
    diseases.sort(key=lambda x: (-x["pending_points"], -x["total_points"], x["disease"]))

    total_rows = sum(d["total_points"] for d in diseases)
    total_samples = sum(d["total_samples"] for d in diseases)
    approved_total = sum(d["approved_points"] for d in diseases)
    pending_total = sum(d["pending_points"] for d in diseases)
    rejected_total = sum(d["rejected_points"] for d in diseases)

    overview = {
        "total_diseases": len(diseases),
        "total_points": total_rows,
        "total_samples": total_samples,
        "approved_points": approved_total,
        "pending_points": pending_total,
        "rejected_points": rejected_total,
        "overall_approval_rate": round((approved_total / total_rows), 4) if total_rows else 0.0,
    }

    return {"overview": overview, "diseases": diseases}


# ============================================================
# 空间统计：省级热点/冷点（Moran's I + Getis-Ord Gi*）
# ============================================================

def _load_province_adjacency() -> dict:
    """加载 34 省级 queen 邻接矩阵（binary）。"""
    import json as _json
    import os as _os
    _p = _os.path.join(
        _os.path.dirname(__file__), "..", "core", "reference_data",
        "china_province_adjacency.json",
    )
    with open(_p, "r", encoding="utf-8") as _f:
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


async def get_spatial_hotspots(
    db: AsyncSession,
    disease: str,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    level: str = "province",
) -> dict:
    """省级空间热点/冷点分析（Moran's I 全局自相关 + Getis-Ord Gi* 局部热点）。

    - 率口径：复用 ``get_region_compare`` 的省级加权阳性率（avg_positivity）。
    - 权重口径：binary queen 邻接 → 对称化 → 行标准化；缺数省份不参与且不纳入邻接。
    - 有数据省份 < 8 → 返回 n_valid，由路由层转 422 中文提示。
    """
    region = await get_region_compare(
        db=db,
        disease=disease,
        province=None,
        year_start=year_start,
        year_end=year_end,
        age_min=None,
        age_max=None,
        data_type=None,
    )
    regions = region.get("regions", [])

    adj = _load_province_adjacency()
    adjacency = adj["binary"]

    # 省份名归一化到标准键，仅保留有阳性率的省
    prov_map: dict[str, dict] = {}
    for r in regions:
        rate = r.get("avg_positivity")
        if rate is None:
            continue
        std = normalize_province(r["province"])
        if not std or std not in adjacency or std in prov_map:
            continue
        prov_map[std] = {"name": std, "rate": float(rate)}

    if len(prov_map) < 8:
        return {
            "disease": disease,
            "level": level,
            "year_start": year_start,
            "year_end": year_end,
            "n_valid": len(prov_map),
            "adjacency_version": adj.get("version"),
            "global_moran": None,
            "provinces": [],
        }

    data_provinces = sorted(prov_map.keys())
    rates = [prov_map[p]["rate"] for p in data_provinces]

    # 权重阵 W（对称化 + 行标准化，缺数省份已删行列）
    w = _build_province_weights(adjacency, data_provinces)

    global_moran = morans_i(rates, w)
    gi_list = g_star(rates, w) or []

    provinces = []
    for i, p in enumerate(data_provinces):
        g = gi_list[i] if i < len(gi_list) else None
        gi_z = g["gi_z"] if g else None
        provinces.append({
            "name": p,
            "rate": round(prov_map[p]["rate"], 4),
            "gi_z": gi_z,
            "p": g["p"] if g else None,
            "cluster": classify_hotspot_cluster(gi_z),
        })

    return {
        "disease": disease,
        "level": level,
        "year_start": year_start,
        "year_end": year_end,
        "n_valid": len(data_provinces),
        "adjacency_version": adj.get("version"),
        "global_moran": global_moran,
        "provinces": provinces,
    }



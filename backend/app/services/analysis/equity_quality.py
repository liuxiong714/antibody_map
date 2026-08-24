"""Submodule of app.services.analysis (split from analysis_service.py)."""


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
from app.config import settings
from app.services.goal_threshold_service import get_goal_threshold

from app.services.analysis._common import (
    AGE_GROUPS,
    CHINA_POP_STD_VERSION,
    CHINA_PROVINCES,
    DEFAULT_LIFE_EXPECTANCY,
    NIP_COVERAGE_REFERENCE,
    NON_ENDEMIC_LIFELONG,
    R0_ASSUMPTION_NOTE,
    R0_REFERENCE,
    WHO_THRESHOLDS,
    _CHINA_POP_2020,
    _STD_BAND_MAP,
    _STD_WEIGHT_BY_GROUP,
    _barrier_status_from_rate,
    _barrier_status_with_message,
    _build_base_query,
    _build_catalytic_records,
    _build_province_weights,
    _calc_foi_from_sp,
    _calc_gmc,
    _calc_hit_from_r0,
    _calc_r0_from_foi,
    _calc_ve_from_sp,
    _calc_weighted_positivity,
    _catalytic_r0_hit,
    _compute_province_asr,
    _get_age_group_label,
    _get_reference_coverage,
    _implied_coverage_from_hit,
    _load_disease_note,
    _load_province_adjacency,
    _load_std_pop,
    _meta_merge_cell,
    _midpoint_age,
    _resolve_hit_target,
    _split_vax_unvax,
    logger,
)


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
        # 年龄标化阳性率（直接法，七普标准人口）；无有效分层时回退加权率排名
        asr_info = _compute_province_asr(group_rows)
        asr = asr_info.get("asr")
        is_std = asr is not None
        std_positivity = asr if is_std else wpr
        province_rows.append({
            "rank": None,
            "province": prov,
            "weighted_positivity": wpr,
            "ci_lower": wpr_info["ci_lower"],
            "ci_upper": wpr_info["ci_upper"],
            "asr": asr,
            "asr_ci_lower": asr_info.get("asr_ci_lower"),
            "asr_ci_upper": asr_info.get("asr_ci_upper"),
            "is_age_standardized": is_std,
            "n_strata": asr_info.get("n_strata", 0),
            "std_positivity": std_positivity,
            "total_samples": wpr_info["total_sample"],
            "n_studies": len(group_rows),
            "is_meeting_target": (wpr >= threshold) if (wpr is not None and threshold is not None) else None,
        })

    # 排名 & 离散度：排名键优先年龄标化率，仅纳入样本量达标的省
    # （避免小样本省进入 Top/Bottom，证据不足）
    min_samples = settings.MIN_SAMPLE_FOR_META
    valid = [r for r in province_rows
             if r["std_positivity"] is not None
             and (r["total_samples"] or 0) >= min_samples]
    insufficient = [r for r in province_rows
                    if r["std_positivity"] is not None
                    and (r["total_samples"] or 0) < min_samples]
    if valid:
        valid.sort(key=lambda r: r["std_positivity"], reverse=True)
        for i, r in enumerate(valid, 1):
            r["rank"] = i

        pos_vals = [r["std_positivity"] for r in valid]
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
        best = {"province": None, "weighted_positivity": None, "std_positivity": None}
        worst = {"province": None, "weighted_positivity": None, "std_positivity": None}

    # 全量排名（有值但样本不足的省 rank 置 None；无值省排最后）
    valid_keys = {id(r) for r in valid}
    province_rows.sort(key=lambda r: (r["std_positivity"] is None, -(r["std_positivity"] or 0)))
    rank_counter = 0
    for r in province_rows:
        if id(r) in valid_keys:
            rank_counter += 1
            r["rank"] = rank_counter
        else:
            r["rank"] = None

    top_provinces = valid[:5]
    bottom_provinces = valid[-5:][::-1]

    notes = []
    if threshold is not None:
        notes.append(f"达标阈值参照 WHO 免疫屏障标准：{threshold}%")
    else:
        notes.append("未在 WHO_THRESHOLDS 中找到该疾病阈值，达标比例不可用")
    n_age_std = sum(1 for r in province_rows if r["is_age_standardized"])
    if n_age_std:
        notes.append(
            f"省间排名基于年龄标化阳性率（直接法，七普标准人口）；"
            f"{n_age_std}/{len(province_rows)} 省完成年龄标化，其余省份年龄分层不足回落加权率。"
        )
    else:
        notes.append("无有效年龄分层数据，省间排名回落加权阳性率（未做年龄标化）。")
    if insufficient:
        names = "、".join(
            r["province"] for r in sorted(insufficient, key=lambda r: -(r["total_samples"] or 0))
        )
        notes.append(
            f"{len(insufficient)} 个省份累计样本量 < {min_samples}，证据不足，"
            f"未纳入公平性排名与离散度指标：{names}"
        )
    if not valid:
        notes.append("无样本量达标的血清阳性率数据，无法计算省间离散度指标")

    return {
        "disease": disease,
        "n_provinces": len(province_rows),
        "n_data_points": len(rows),
        "summary": {
            "gini": gini_val,
            "coefficient_of_variation": cv_val,
            "best_province": best["province"],
            "best_positivity": best.get("std_positivity", best.get("weighted_positivity")),
            "worst_province": worst["province"],
            "worst_positivity": worst.get("std_positivity", worst.get("weighted_positivity")),
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

    threshold = await get_goal_threshold(db, normalize_disease(disease))
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


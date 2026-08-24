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
    goal_threshold = await get_goal_threshold(db, dis_key)
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



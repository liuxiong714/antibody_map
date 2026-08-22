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
from app.core.goal_thresholds import GOAL_THRESHOLDS

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



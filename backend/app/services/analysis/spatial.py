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
from app.services.analysis.basic import get_region_compare  # noqa: E501,F401


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




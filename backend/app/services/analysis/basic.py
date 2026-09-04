"""Submodule of app.services.analysis (split from analysis_service.py)."""



from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.stats import (
    weighted_linear_trend,
)
from app.core.stats_engine import (
    birth_cohort_analysis,
    cochran_armitage_trend,
    fit_age_curve,
    foi_from_curve,
    two_proportion_test,
)
from app.core.term_normalizer import normalize_disease
from app.models.data_point import DataPoint
from app.services.analysis._common import (
    AGE_GROUPS,
    CHINA_POP_STD_VERSION,
    _build_base_query,
    _calc_gmc,
    _calc_weighted_positivity,
    _compute_province_asr,
    _get_age_group_label,
    _load_disease_note,
    _meta_merge_cell,
    _midpoint_age,
)


async def get_trend(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    data_type: str | None = None,
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




async def get_region_compare(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    data_type: str | None = None,
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
            # 4.5：最小样本护栏——研究数/样本量不足时标记证据不足，避免误导
            "evidence_insufficient": (
                len(group_rows) < settings.MIN_STUDIES_FOR_META
                or (meta_info["total_sample"] or 0) < settings.MIN_SAMPLE_FOR_META
            ),
            "evidence_note": (
                "研究数不足或累计样本量过小，合并值仅供参考"
                if (
                    len(group_rows) < settings.MIN_STUDIES_FOR_META
                    or (meta_info["total_sample"] or 0) < settings.MIN_SAMPLE_FOR_META
                )
                else None
            ),
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




async def get_age_curve(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
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
        x_tot = round(sum(n_i * p_i for n_i, p_i in zip(n_vals, p_vals, strict=False)))
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
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
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




async def get_age_stratify(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    data_type: str | None = None,
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
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    data_type: str | None = None,
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
    lit_ids = {str(r.literature_id) for r in rows if r.literature_id}

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



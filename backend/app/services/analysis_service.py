from typing import Optional

from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint

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
                      data_type=None, review_status="approved"):
    """构建通用数据点查询"""
    query = select(DataPoint).where(DataPoint.review_status == review_status)

    if disease:
        query = query.where(DataPoint.disease == disease)
    if province:
        query = query.where(DataPoint.province.ilike(f"%{province}%"))
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


def _calc_weighted_positivity(rows: list[DataPoint]) -> tuple[float, int]:
    """计算加权阳性率（仅 seroprevalence 且有 sample_size）"""
    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.sample_size]
    if not sp_rows:
        return 0.0, 0
    total_sample = sum(r.sample_size for r in sp_rows)
    weighted_sum = sum(r.value * r.sample_size for r in sp_rows)
    if total_sample == 0:
        return 0.0, 0
    return round(weighted_sum / total_sample, 2), total_sample


async def get_trend(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    data_type: Optional[str] = None,
) -> list[dict]:
    """逐年趋势分析"""
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
        wpr, total_sample = _calc_weighted_positivity(group_rows)

        gmc_rows = [r for r in group_rows if r.data_type == "gmc"]
        avg_gmc = round(sum(r.value for r in gmc_rows if r.value) / len(gmc_rows), 2) if gmc_rows else None

        trend.append({
            "year": year,
            "weighted_positivity": wpr,
            "avg_gmc": avg_gmc,
            "total_sample": total_sample,
            "point_count": len(group_rows),
        })

    return trend


async def get_region_compare(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    data_type: Optional[str] = None,
) -> list[dict]:
    """区域对比分析"""
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
        wpr, total_sample = _calc_weighted_positivity(group_rows)
        gmc_rows = [r for r in group_rows if r.data_type == "gmc" and r.value is not None]
        avg_gmc = round(sum(r.value for r in gmc_rows) / len(gmc_rows), 2) if gmc_rows else None

        results.append({
            "province": prov,
            "avg_positivity": wpr,
            "avg_gmc": avg_gmc,
            "point_count": len(group_rows),
            "total_samples": total_sample,
        })

    results.sort(key=lambda x: x["province"])
    return results


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
        wpr, total_sample = _calc_weighted_positivity(group_rows)
        gmc_rows = [r for r in group_rows if r.data_type == "gmc" and r.value is not None]
        avg_gmc = round(sum(r.value for r in gmc_rows) / len(gmc_rows), 2) if gmc_rows else None

        results.append({
            "age_group": age_group,
            "avg_positivity": wpr,
            "avg_gmc": avg_gmc,
            "point_count": len(group_rows),
            "total_samples": total_sample,
        })

    return results


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
            "min_positivity": None,
            "max_positivity": None,
            "avg_gmc": None,
        }

    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.value is not None]
    gmc_rows = [r for r in rows if r.data_type == "gmc" and r.value is not None]

    lit_ids = set(str(r.literature_id) for r in rows if r.literature_id)

    _, total_sample = _calc_weighted_positivity(rows)

    return {
        "total_data_points": len(rows),
        "total_literatures": len(lit_ids),
        "total_samples": total_sample,
        "avg_positivity": round(sum(r.value for r in sp_rows) / len(sp_rows), 2) if sp_rows else None,
        "min_positivity": round(min(r.value for r in sp_rows), 2) if sp_rows else None,
        "max_positivity": round(max(r.value for r in sp_rows), 2) if sp_rows else None,
        "avg_gmc": round(sum(r.value for r in gmc_rows) / len(gmc_rows), 2) if gmc_rows else None,
    }


async def get_immune_barrier_assessment(
    db: AsyncSession,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
) -> dict:
    """免疫屏障评估"""
    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max,
                              review_status="approved")
    result = await db.execute(query)
    rows = result.scalars().all()

    if not rows:
        return {
            "disease": disease,
            "who_threshold": WHO_THRESHOLDS.get(disease) if disease else None,
            "summary": {
                "total_data_points": 0,
                "total_literatures": 0,
                "total_samples": 0,
                "weighted_positivity_rate": None,
            },
            "yearly_trend": [],
            "status": "no_data",
            "assessment": "暂无审核通过的数据可供评估。",
        }

    # 加权阳性率
    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.sample_size]
    if sp_rows:
        total_sample = sum(r.sample_size for r in sp_rows)
        weighted_sum = sum(r.value * r.sample_size for r in sp_rows)
        weighted_rate = round(weighted_sum / total_sample, 2) if total_sample > 0 else None
    else:
        total_sample = 0
        weighted_rate = None

    lit_ids = set(str(r.literature_id) for r in rows if r.literature_id)

    # 逐年趋势
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
        sp_g = [r for r in group if r.data_type == "seroprevalence" and r.sample_size]
        if sp_g:
            ys = sum(r.sample_size for r in sp_g)
            yw = sum(r.value * r.sample_size for r in sp_g)
            y_rate = round(yw / ys, 2) if ys > 0 else None
        else:
            ys = 0
            y_rate = None
        yearly_trend.append({
            "year": year,
            "weighted_positivity": y_rate,
            "sample_size": ys,
            "point_count": len(group),
        })

    # WHO 阈值对比
    threshold = WHO_THRESHOLDS.get(disease) if disease else None

    if threshold is not None and weighted_rate is not None:
        if weighted_rate >= threshold:
            status = "established"
            assessment = f"该疾病群体抗体阳性率（{weighted_rate}%）已达到 WHO 建议的免疫屏障阈值（{threshold}%），免疫屏障已建立。"
        elif weighted_rate >= threshold - 10:
            status = "borderline"
            assessment = f"该疾病群体抗体阳性率（{weighted_rate}%）接近但未完全达到 WHO 建议的免疫屏障阈值（{threshold}%），建议加强重点人群免疫。"
        else:
            status = "insufficient"
            assessment = f"该疾病群体抗体阳性率（{weighted_rate}%）低于 WHO 建议的免疫屏障阈值（{threshold}%），免疫屏障不足，建议加强免疫接种。"
    else:
        status = "no_data"
        assessment = "暂无足够数据或对应的 WHO 阈值进行对比评估。"

    return {
        "disease": disease,
        "who_threshold": threshold,
        "summary": {
            "total_data_points": len(rows),
            "total_literatures": len(lit_ids),
            "total_samples": total_sample,
            "weighted_positivity_rate": weighted_rate,
        },
        "yearly_trend": yearly_trend,
        "status": status,
        "assessment": assessment,
    }

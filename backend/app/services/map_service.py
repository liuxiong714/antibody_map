from typing import Optional

from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint


async def get_province_data(
    db: AsyncSession,
    disease: Optional[str] = None,
    data_type: Optional[str] = None,
    province: Optional[str] = None,
    age_group: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
) -> list[dict]:
    """获取省份聚合数据（仅审核通过的数据点）"""
    base = select(DataPoint).where(DataPoint.review_status == "approved")

    if disease:
        base = base.where(DataPoint.disease == disease)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)
    if province:
        base = base.where(DataPoint.province.ilike(f"%{province}%"))
    if year_start:
        base = base.where(DataPoint.collection_year >= year_start)
    if year_end:
        base = base.where(DataPoint.collection_year <= year_end)

    result = await db.execute(base)
    rows = result.scalars().all()

    # 按省份聚合（province 字段可能包含 ; 分隔的多省，每个省单独计入）
    province_map: dict[str, dict] = {}

    for dp in rows:
        provinces = [p.strip() for p in (dp.province or "").split(";") if p.strip()]
        if not provinces:
            provinces = ["未知"]

        for key in provinces:
            if key not in province_map:
                province_map[key] = {
                    "province": key,
                    "literature_ids": set(),
                    "data_points": [],
                }
            province_map[key]["literature_ids"].add(str(dp.literature_id) if dp.literature_id else "")
            province_map[key]["data_points"].append(dp)

    result_list = []
    for key, group in province_map.items():
        dps = group["data_points"]
        sp_dps = [dp for dp in dps if dp.data_type == "seroprevalence" and dp.sample_size]

        if sp_dps:
            weighted_sum = sum(dp.value * dp.sample_size for dp in sp_dps)
            total_sample = sum(dp.sample_size for dp in sp_dps)
            weighted_rate = round(weighted_sum / total_sample, 2) if total_sample > 0 else None
        else:
            total_sample = 0
            weighted_rate = None

        result_list.append({
            "province": key,
            "point_count": len(dps),
            "study_count": len(group["literature_ids"]),
            "total_sample": total_sample,
            "weighted_positivity": weighted_rate,
        })

    result_list.sort(key=lambda x: x["province"])
    return result_list


async def get_city_data(
    db: AsyncSession,
    province: str,
    disease: Optional[str] = None,
    data_type: Optional[str] = None,
) -> list[dict]:
    """获取城市级聚合数据"""
    base = (
        select(DataPoint)
        .where(DataPoint.review_status == "approved")
        .where(DataPoint.province.ilike(f"%{province}%"))
    )
    if disease:
        base = base.where(DataPoint.disease == disease)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)

    result = await db.execute(base)
    rows = result.scalars().all()

    city_map: dict[str, dict] = {}

    for dp in rows:
        city = dp.city or "未知"
        if city not in city_map:
            city_map[city] = {"data_points": [], "literature_ids": set()}

        city_map[city]["data_points"].append(dp)
        city_map[city]["literature_ids"].add(str(dp.literature_id) if dp.literature_id else "")

    result_list = []
    for city, group in city_map.items():
        dps = group["data_points"]
        sp_dps = [dp for dp in dps if dp.data_type == "seroprevalence" and dp.sample_size]

        if sp_dps:
            weighted_sum = sum(dp.value * dp.sample_size for dp in sp_dps)
            total_sample = sum(dp.sample_size for dp in sp_dps)
            weighted_rate = round(weighted_sum / total_sample, 2) if total_sample > 0 else None
        else:
            total_sample = 0
            weighted_rate = None

        result_list.append({
            "city": city,
            "point_count": len(dps),
            "study_count": len(group["literature_ids"]),
            "total_sample": total_sample,
            "weighted_positivity": weighted_rate,
        })

    result_list.sort(key=lambda x: x["city"])
    return result_list


async def get_summary(
    db: AsyncSession,
    disease: Optional[str] = None,
    data_type: Optional[str] = None,
) -> dict:
    """获取全国汇总统计"""
    base = select(DataPoint).where(DataPoint.review_status == "approved")
    if disease:
        base = base.where(DataPoint.disease == disease)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)

    result = await db.execute(base)
    rows = result.scalars().all()

    if not rows:
        return {
            "province_count": 0,
            "point_count": 0,
            "study_count": 0,
            "total_sample": 0,
            "national_weighted_rate": None,
        }

    # 统计去重的省份和文献
    provinces = set()
    lit_ids = set()
    for dp in rows:
        for p in (dp.province or "").split(";"):
            p = p.strip()
            if p:
                provinces.add(p)
        if dp.literature_id:
            lit_ids.add(str(dp.literature_id))

    # 加权全国阳性率
    sp_dps = [dp for dp in rows if dp.data_type == "seroprevalence" and dp.sample_size]
    if sp_dps:
        weighted_sum = sum(dp.value * dp.sample_size for dp in sp_dps)
        total_sample = sum(dp.sample_size for dp in sp_dps)
        national_rate = round(weighted_sum / total_sample, 2) if total_sample > 0 else None
    else:
        total_sample = 0
        national_rate = None

    return {
        "province_count": len(provinces),
        "point_count": len(rows),
        "study_count": len(lit_ids),
        "total_sample": total_sample,
        "national_weighted_rate": national_rate,
    }

from typing import Optional

from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint
from app.core.term_normalizer import normalize_province, CHINA_PROVINCE_NAMES


def _parse_provinces(raw: Optional[str]) -> list[str]:
    """从原始省份字符串中解析出标准省份名称列表"""
    if not raw:
        return ["unknown"]
    # 先按分号拆分
    parts = [p.strip() for p in raw.replace("；", ";").split(";") if p.strip()]
    result = []
    for part in parts:
        # 尝试标准化
        normalized = normalize_province(part)
        if normalized and normalized in CHINA_PROVINCE_NAMES:
            result.append(normalized)
            continue
        # 尝试从长文本中提取已知省份名称
        found = []
        for province_name in sorted(CHINA_PROVINCE_NAMES, key=len, reverse=True):
            if province_name in part:
                found.append(province_name)
                part = part.replace(province_name, "", 1)
        if found:
            result.extend(found)
        else:
            result.append(part)  # 无法识别的保留原文
    return result if result else ["unknown"]


async def get_province_data(
    db: AsyncSession,
    disease: Optional[str] = None,
    data_type: Optional[str] = None,
    province: Optional[str] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    gender: Optional[str] = None,
    occupation: Optional[str] = None,
) -> list[dict]:
    """get province aggregated data (approved only)"""
    base = select(DataPoint).where(DataPoint.review_status == "approved")

    if disease:
        base = base.where(DataPoint.disease == disease)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)
    if province:
        base = base.where(DataPoint.province.ilike(f"%{province}%"))
    if age_min is not None:
        base = base.where(DataPoint.age_min >= age_min)
    if age_max is not None:
        base = base.where(DataPoint.age_max <= age_max)
    if year_start:
        base = base.where(DataPoint.collection_year >= year_start)
    if year_end:
        base = base.where(DataPoint.collection_year <= year_end)
    if gender:
        base = base.where(DataPoint.population.ilike(f"%{gender}%"))
    if occupation:
        base = base.where(DataPoint.population.ilike(f"%{occupation}%"))

    result = await db.execute(base)
    rows = result.scalars().all()

    province_map: dict[str, dict] = {}

    for dp in rows:
        provinces = _parse_provinces(dp.province)

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
        valid_dps = [dp for dp in dps if dp.sample_size and dp.value is not None]

        if valid_dps:
            weighted_sum = float(sum(dp.value * dp.sample_size for dp in valid_dps))
            total_sample = int(sum(dp.sample_size for dp in valid_dps))
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
    """get city-level aggregated data"""
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
        city = dp.city or "unknown"
        if city not in city_map:
            city_map[city] = {"data_points": [], "literature_ids": set()}

        city_map[city]["data_points"].append(dp)
        city_map[city]["literature_ids"].add(str(dp.literature_id) if dp.literature_id else "")

    result_list = []
    for city, group in city_map.items():
        dps = group["data_points"]
        valid_dps = [dp for dp in dps if dp.sample_size and dp.value is not None]

        if valid_dps:
            weighted_sum = float(sum(dp.value * dp.sample_size for dp in valid_dps))
            total_sample = int(sum(dp.sample_size for dp in valid_dps))
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
    """get national summary"""
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

    provinces = set()
    lit_ids = set()
    for dp in rows:
        for p in (dp.province or "").split(";"):
            p = p.strip()
            if p:
                provinces.add(p)
        if dp.literature_id:
            lit_ids.add(str(dp.literature_id))

    valid_dps = [dp for dp in rows if dp.sample_size and dp.value is not None]
    if valid_dps:
        weighted_sum = sum(dp.value * dp.sample_size for dp in valid_dps)
        total_sample = sum(dp.sample_size for dp in valid_dps)
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
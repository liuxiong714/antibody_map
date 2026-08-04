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


def _normalize_seroprevalence(value: float) -> float:
    """标准化血清阳性率值：
    - 如果值在 0~1 之间（小数格式），转换为百分比（×100）
    - 上限封顶 100%
    """
    if value is None:
        return None
    v = float(value)
    if 0 < v <= 1:
        v = v * 100
    if v > 100:
        v = 100.0
    if v < 0:
        v = 0.0
    return round(v, 4)


def _calc_weighted_rate(dps: list, target_data_type: Optional[str] = None) -> tuple[Optional[float], int]:
    """计算加权平均率和总样本量。

    - target_data_type='seroprevalence': 仅使用阳性率数据点，值标准化到 0-100%
    - target_data_type='gmc': 仅使用 GMC 数据点
    - target_data_type=None: 仅使用 seroprevalence 数据点（避免与 GMC 混合导致 >100%）
    - 返回 (weighted_rate, total_sample)
    """
    # 未指定数据类型时，默认只计算 seroprevalence（阳性率），避免 GMC 混入导致 >100%
    effective_type = target_data_type or "seroprevalence"

    valid_dps = [
        dp for dp in dps
        if dp.sample_size and dp.value is not None and dp.data_type == effective_type
    ]

    if not valid_dps:
        return None, 0

    if effective_type == "seroprevalence":
        # 阳性率：标准化小数格式并封顶 100%
        weighted_sum = float(sum(_normalize_seroprevalence(dp.value) * dp.sample_size for dp in valid_dps))
    else:
        # GMC: 直接使用原始值
        weighted_sum = float(sum(float(dp.value) * dp.sample_size for dp in valid_dps))

    total_sample = int(sum(dp.sample_size for dp in valid_dps))
    weighted_rate = round(weighted_sum / total_sample, 2) if total_sample > 0 else None

    return weighted_rate, total_sample


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
    """get province aggregated data (approved only, P1-1: primary estimates by default)"""
    base = select(DataPoint).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
    )

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
        weighted_rate, total_sample = _calc_weighted_rate(dps, data_type)

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
    """get city-level aggregated data (P1-1: primary estimates by default)"""
    base = (
        select(DataPoint)
        .where(DataPoint.review_status == "approved")
        .where(DataPoint.estimate_type == "primary")
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
        weighted_rate, total_sample = _calc_weighted_rate(dps, data_type)

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
    """get national summary (P1-1: primary estimates by default)"""
    base = select(DataPoint).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
    )
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

    national_rate, total_sample = _calc_weighted_rate(rows, data_type)

    return {
        "province_count": len(provinces),
        "point_count": len(rows),
        "study_count": len(lit_ids),
        "total_sample": total_sample,
        "national_weighted_rate": national_rate,
    }


async def get_province_yearly_data(
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
    """按年份分组返回各省抗体水平数据，用于时间序列动态展示 (P1-1: primary estimates by default)"""
    base = select(DataPoint).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
    )

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

    # 按年份分组: year -> { province_key -> aggregate }
    year_map: dict[int, dict[str, dict]] = {}

    for dp in rows:
        year = dp.collection_year or 0
        if year not in year_map:
            year_map[year] = {}

        provinces = _parse_provinces(dp.province)
        for key in provinces:
            if key not in year_map[year]:
                year_map[year][key] = {
                    "province": key,
                    "literature_ids": set(),
                    "data_points": [],
                }
            year_map[year][key]["literature_ids"].add(str(dp.literature_id) if dp.literature_id else "")
            year_map[year][key]["data_points"].append(dp)

    result_list = []
    for year in sorted(year_map.keys()):
        year_data = []
        for key, group in year_map[year].items():
            dps = group["data_points"]
            weighted_rate, total_sample = _calc_weighted_rate(dps, data_type)

            year_data.append({
                "province": key,
                "point_count": len(dps),
                "study_count": len(group["literature_ids"]),
                "total_sample": total_sample,
                "weighted_positivity": weighted_rate,
            })

        result_list.append({
            "year": year,
            "data": sorted(year_data, key=lambda x: x["province"]),
        })

    return result_list


async def get_available_years(
    db: AsyncSession,
    disease: Optional[str] = None,
) -> list[int]:
    """获取可用的年份列表（去重排序, P1-1: primary estimates by default）"""
    query = select(DataPoint.collection_year).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
        DataPoint.collection_year.isnot(None),
    )
    if disease:
        query = query.where(DataPoint.disease == disease)
    query = query.distinct().order_by(DataPoint.collection_year)

    result = await db.execute(query)
    return [v for v in result.scalars().all() if v]


async def get_population_options(
    db: AsyncSession,
    disease: Optional[str] = None,
) -> list[str]:
    """获取所有已审核数据点中出现的人群分类（population 字段）。

    population 字段可能包含多个值（以分号分隔），这里拆分、去空白、去重、排序。
    仅查询主估计（estimate_type='primary'）避免子组重复。
    结果用于前端"全部职业"下拉框的动态选项。
    """
    query = select(DataPoint.population).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
        DataPoint.population.isnot(None),
        DataPoint.population != "",
    )
    if disease:
        query = query.where(DataPoint.disease == disease)

    result = await db.execute(query)
    raw_values = result.scalars().all()

    # 拆分分号分隔的多个值，去空白、去重
    seen: set[str] = set()
    options: list[str] = []
    for raw in raw_values:
        if not raw:
            continue
        # 兼容中英文分号
        parts = raw.replace("；", ";").split(";")
        for p in parts:
            p = p.strip()
            if p and p not in seen:
                seen.add(p)
                options.append(p)

    # 按拼音/字符排序（中文按 Unicode 排序）
    options.sort()
    return options

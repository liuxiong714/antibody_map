from typing import Optional

from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.core.term_normalizer import normalize_disease

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
        # 标准化疾病名称，数据库中的 disease 字段已统一为标准 key
        normalized = normalize_disease(disease)
        query = query.where(DataPoint.disease == normalized)
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
    """数据覆盖度分析：统计各省份各年份的数据点分布，识别需要审核和补充的数据缺口。

    查询 ALL 数据点（含 pending/approved/rejected 全部状态），
    返回 overview / review_needed / data_gaps / province_year_matrix。
    """
    # 基础查询：全部数据点（不限 review_status）
    query = select(
        DataPoint.province,
        DataPoint.collection_year,
        DataPoint.disease,
        DataPoint.review_status,
        func.count(DataPoint.id).label("cnt"),
    ).group_by(
        DataPoint.province,
        DataPoint.collection_year,
        DataPoint.disease,
        DataPoint.review_status,
    )
    if disease:
        # 标准化查询参数，数据库中的 disease 字段已统一为标准 key
        normalized_disease = normalize_disease(disease)
        query = query.where(DataPoint.disease == normalized_disease)

    result = await db.execute(query)
    rows = result.all()

    # ---- 1. 总览统计 ----
    total_dp = sum(r.cnt for r in rows)
    all_provinces = set()
    all_diseases = set()
    all_years = set()
    status_counts = {"pending": 0, "approved": 0, "rejected": 0}
    for r in rows:
        if r.province:
            for p in r.province.split(";"):
                p = p.strip()
                if p:
                    all_provinces.add(p)
        if r.disease:
            # 使用标准化名称统计
            all_diseases.add(normalize_disease(r.disease))
        if r.collection_year:
            all_years.add(r.collection_year)
        if r.review_status in status_counts:
            status_counts[r.review_status] += r.cnt

    year_list = sorted(y for y in all_years if y is not None) if all_years else []

    # ---- 2. 需要审核的数据点（pending > 0 的 province+year+disease 组合）----
    # 聚合: province, year, disease -> {pending: N, approved: N, rejected: N}
    pyd_map: dict[tuple, dict] = {}
    for r in rows:
        if not r.province:
            continue
        prov = r.province.split(";")[0].strip()
        if not prov:
            continue
        # 使用标准化疾病名称作为 key
        normalized_dis = normalize_disease(r.disease) if r.disease else r.disease
        key = (prov, r.collection_year, normalized_dis)
        if key not in pyd_map:
            pyd_map[key] = {"pending": 0, "approved": 0, "rejected": 0, "total": 0}
        if r.review_status in pyd_map[key]:
            pyd_map[key][r.review_status] += r.cnt
        pyd_map[key]["total"] += r.cnt

    review_needed = []
    for (prov, year, dis), counts in pyd_map.items():
        if counts["pending"] > 0:
            review_needed.append({
                "province": prov,
                "year": year,
                "disease": dis or "未知",
                "pending_count": counts["pending"],
                "approved_count": counts["approved"],
                "rejected_count": counts["rejected"],
                "total_count": counts["total"],
            })
    review_needed.sort(key=lambda x: x["pending_count"], reverse=True)

    # ---- 3. 数据缺失分析（按疾病分组，找出完全没有数据的省份）----
    # disease -> set of provinces that have data
    disease_provinces: dict[str, set[str]] = {}
    for r in rows:
        if not r.disease or not r.province:
            continue
        # 使用标准化疾病名称进行分组
        normalized_dis = normalize_disease(r.disease)
        if normalized_dis not in disease_provinces:
            disease_provinces[normalized_dis] = set()
        for p in r.province.split(";"):
            p = p.strip()
            if p:
                disease_provinces[normalized_dis].add(p)

    data_gaps = []
    for dis, provs in disease_provinces.items():
        missing = [p for p in CHINA_PROVINCES if p not in provs]
        if missing:
            data_gaps.append({
                "disease": dis,
                "covered_provinces": sorted(provs),
                "missing_provinces": missing,
                "covered_count": len(provs),
                "missing_count": len(missing),
            })
    data_gaps.sort(key=lambda x: x["missing_count"], reverse=True)

    total_gap_combos = sum(g["missing_count"] for g in data_gaps)

    # ---- 4. 省份×年份矩阵 ----
    # province -> year -> {total, pending, approved}
    matrix_map: dict[str, dict[int, dict]] = {}
    for r in rows:
        if not r.province:
            continue
        prov = r.province.split(";")[0].strip()
        if not prov:
            continue
        year = r.collection_year
        if prov not in matrix_map:
            matrix_map[prov] = {}
        if year not in matrix_map[prov]:
            matrix_map[prov][year] = {"total": 0, "pending": 0, "approved": 0}
        matrix_map[prov][year]["total"] += r.cnt
        if r.review_status == "pending":
            matrix_map[prov][year]["pending"] += r.cnt
        elif r.review_status == "approved":
            matrix_map[prov][year]["approved"] += r.cnt

    province_year_matrix = []
    for prov in sorted(matrix_map.keys()):
        year_data = matrix_map[prov]
        total_for_prov = sum(yd["total"] for yd in year_data.values())
        pending_for_prov = sum(yd["pending"] for yd in year_data.values())
        province_year_matrix.append({
            "province": prov,
            "years": {str(y): year_data[y] for y in sorted(y for y in year_data.keys() if y is not None)},
            "total": total_for_prov,
            "pending": pending_for_prov,
        })

    overview = {
        "total_data_points": total_dp,
        "total_provinces": len(all_provinces),
        "total_diseases": len(all_diseases),
        "year_range": [year_list[0], year_list[-1]] if year_list else None,
        "years": year_list,
        "pending_count": status_counts["pending"],
        "approved_count": status_counts["approved"],
        "rejected_count": status_counts["rejected"],
        "total_gap_combos": total_gap_combos,
    }

    return {
        "overview": overview,
        "review_needed": review_needed,
        "data_gaps": data_gaps,
        "province_year_matrix": province_year_matrix,
    }

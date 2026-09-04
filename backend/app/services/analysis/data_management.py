"""Submodule of app.services.analysis (split from analysis_service.py)."""



from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.term_normalizer import normalize_disease
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.services.analysis._common import (
    CHINA_PROVINCES,
    _build_base_query,
)


async def get_approved_data_points(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    data_type: str | None = None,
    offset: int = 0,
    limit: int = 200,
    sort_by: str | None = None,
    sort_order: str = "desc",
) -> tuple[list[dict], int]:
    """获取所有审核通过的数据点（分页），用于数据分析模块展示"""
    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max,
                              data_type, review_status="approved")

    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # 获取分页数据，关联文献表获取标题（_build_base_query 已 join Literature 并过滤软删除）
    query = query.add_columns(
        Literature.title, Literature.authors, Literature.doi, Literature.pmid,
        Literature.pub_year, Literature.journal,
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
        literature_authors = r[2]
        literature_doi = r[3]
        literature_pmid = r[4]
        literature_year = r[5]
        literature_journal = r[6]
        items.append({
            "id": str(dp.id),
            "literature_id": str(dp.literature_id) if dp.literature_id else None,
            "literature_title": literature_title,
            # P1-3：Excel 导出新增作者/DOI/PMID/年份/期刊
            "literature_authors": literature_authors,
            "literature_doi": literature_doi,
            "literature_pmid": literature_pmid,
            "literature_year": literature_year,
            "literature_journal": literature_journal,
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




async def get_approved_data_points_for_snapshot(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    data_type: str | None = None,
    limit: int = 50000,
) -> list[dict]:
    """P2-1：获取审核通过的数据点（含文献元数据），用于公开数据集快照导出。

    与 get_approved_data_points 的区别：
    - 包含 estimate_type, source_page, is_grounded 字段
    - 关联 Literature 表获取 title/pub_year/journal
    - 不分页（一次性导出，limit 上限 50000 防止 OOM）
    - 默认只导出主估计（include_subgroups=False）
    """
    query = _build_base_query(
        disease, province, year_start, year_end, age_min, age_max, data_type,
        review_status="approved", include_subgroups=False,
    )
    # 关联文献元数据（_build_base_query 已 join Literature 并过滤软删除）
    query = query.add_columns(
        Literature.title, Literature.pub_year, Literature.journal,
        Literature.authors, Literature.doi, Literature.pmid,
    )
    query = query.order_by(DataPoint.collection_year.desc().nullslast()).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    items = []
    for r in rows:
        dp = r[0]
        lit_title = r[1]
        lit_year = r[2]
        lit_journal = r[3]
        lit_authors = r[4]
        lit_doi = r[5]
        lit_pmid = r[6]
        items.append({
            "disease": dp.disease,
            "province": dp.province,
            "city": dp.city,
            "data_type": dp.data_type,
            "value": float(dp.value) if dp.value is not None else None,
            "unit": dp.unit,
            "ci_lower": float(dp.ci_lower) if dp.ci_lower is not None else None,
            "ci_upper": float(dp.ci_upper) if dp.ci_upper is not None else None,
            "sample_size": dp.sample_size,
            "age_min": dp.age_min,
            "age_max": dp.age_max,
            "population": dp.population,
            "collection_year": dp.collection_year,
            "method": dp.method,
            "assay": dp.assay,
            "estimate_type": dp.estimate_type,
            "confidence": dp.confidence,
            "source_page": dp.source_page,
            "is_grounded": bool(dp.is_grounded),
            "literature_title": lit_title,
            "literature_year": lit_year,
            "literature_journal": lit_journal,
            # P1-3：导出新增作者/DOI/PMID 列
            "literature_authors": lit_authors,
            "literature_doi": lit_doi,
            "literature_pmid": lit_pmid,
        })
    return items


# 中国 34 省级行政区基准列表（用于检测数据缺失）


async def get_data_gap_analysis(
    db: AsyncSession,
    disease: str | None = None,
) -> dict:
    """数据覆盖度分析：统计各省份/城市×各年份的数据点分布，识别需要审核和补充的数据缺口。

    增强版（2026-08-05）：
    - 新增城市（地区）维度统计
    - 计算每个省×年和城市×年的**完整性评分**并按评分排序（高→低，完善的排在前面）
    - 区分"需要审核"和"需要补充"两种情况
    - 所有条目（包括已完善）都保留展示

    查询 ALL 数据点（含 pending/approved/rejected 全部状态），
    返回 overview / review_needed / supplement_needed / data_gaps
           / province_year_matrix / city_year_matrix。
    """
    # ---- 完整性评分常量 ----
    # 已审核数据点 ≥ 这个阈值 → 该组合被认为"完善"
    WELL_COVERED_THRESHOLD = 5
    # 每个已审核数据点贡献多少分（满分 100）
    MAX_APPROVED_SCORE = 70
    # 待审核惩罚系数：每个 pending 扣 2 分（最多 30 分）
    PENALTY_PER_PENDING = 2
    MAX_PENDING_PENALTY = 30

    def _calc_completeness(approved_ab: int, pending: int, total_years: int) -> float:
        """计算完整性评分（0-100）。

        规则（2026-08-16 起仅统计 A+B 高质量数据点）：
        - 基础分：min(approved_ab / WELL_COVERED_THRESHOLD, 1) × MAX_APPROVED_SCORE
        - 待审核惩罚：min(pending × PENALTY_PER_PENDING, MAX_PENDING_PENALTY)
        - 特殊：approved_ab=0 且 pending=0 但该省有数据（被循环到）→ 0 分（需补充）
        """
        base = min(approved_ab / WELL_COVERED_THRESHOLD, 1.0) * MAX_APPROVED_SCORE
        penalty = min(pending * PENALTY_PER_PENDING, MAX_PENDING_PENALTY)
        score = base - penalty
        # 如果 total_years=0（该组合无任何年份数据）→ 0 分
        if approved_ab + pending == 0:
            score = 0.0
        return max(0.0, round(score, 2))

    def _status_label(approved_ab: int, pending: int) -> str:
        """给省×年或城市×年组合打标签（approved_ab 仅计 A+B 高质量已通过数据点）。"""
        if approved_ab == 0 and pending == 0:
            return "need_supplement"   # 完全无数据，需要补充
        if approved_ab == 0:
            return "need_review"        # 有待审核但还没通过，需要先审核
        if approved_ab < WELL_COVERED_THRESHOLD:
            if pending > 0:
                return "need_both"       # 数据不足 + 有待审核
            return "need_supplement"     # 数据不足，需要补充
        if pending > 0:
            return "need_review"        # 已达标但仍有待审核
        return "well_covered"            # 完善

    # 基础查询：全部数据点（不限 review_status），同时取 city 与质量等级
    query = select(
        DataPoint.province,
        DataPoint.city,
        DataPoint.collection_year,
        DataPoint.disease,
        DataPoint.review_status,
        DataPoint.quality_grade,
        func.count(DataPoint.id).label("cnt"),
    ).group_by(
        DataPoint.province,
        DataPoint.city,
        DataPoint.collection_year,
        DataPoint.disease,
        DataPoint.review_status,
        DataPoint.quality_grade,
    )
    if disease:
        normalized_disease = normalize_disease(disease)
        query = query.where(DataPoint.disease == normalized_disease)

    result = await db.execute(query)
    rows = result.all()

    # ---- 1. 总览统计 ----
    total_dp = sum(r.cnt for r in rows)
    all_provinces: set[str] = set()
    all_cities: set[str] = set()
    all_diseases: set[str] = set()
    all_years: set[int] = set()
    status_counts = {"pending": 0, "approved": 0, "rejected": 0}
    for r in rows:
        if r.province:
            for p in r.province.split(";"):
                p = p.strip()
                if p:
                    all_provinces.add(p)
        if r.city:
            for c in r.city.replace("；", ";").split(";"):
                c = c.strip()
                if c:
                    all_cities.add(c)
        if r.disease:
            all_diseases.add(normalize_disease(r.disease))
        if r.collection_year:
            all_years.add(r.collection_year)
        if r.review_status in status_counts:
            status_counts[r.review_status] += r.cnt

    year_list = sorted(y for y in all_years if y is not None) if all_years else []

    # ---- 2. 需要审核 / 需要补充的组合（省×年×疾病 细粒度）----
    pyd_map: dict[tuple, dict] = {}
    for r in rows:
        if not r.province:
            continue
        prov = r.province.split(";")[0].strip()
        if not prov:
            continue
        normalized_dis = normalize_disease(r.disease) if r.disease else (r.disease or "未知")
        key = (prov, r.collection_year, normalized_dis)
        if key not in pyd_map:
            pyd_map[key] = {"pending": 0, "approved": 0, "approved_ab": 0, "rejected": 0, "total": 0}
        if r.review_status in pyd_map[key]:
            pyd_map[key][r.review_status] += r.cnt
            if r.review_status == "approved" and r.quality_grade in ("A", "B"):
                pyd_map[key]["approved_ab"] += r.cnt
        pyd_map[key]["total"] += r.cnt

    review_needed: list[dict] = []
    supplement_needed: list[dict] = []
    for (prov, year, dis), counts in pyd_map.items():
        status = _status_label(counts["approved_ab"], counts["pending"])
        base_item = {
            "province": prov,
            "year": year,
            "disease": dis,
            "pending_count": counts["pending"],
            "approved_count": counts["approved"],
            "approved_ab_count": counts["approved_ab"],
            "rejected_count": counts["rejected"],
            "total_count": counts["total"],
            "completeness_score": _calc_completeness(counts["approved_ab"], counts["pending"], len(year_list)),
            "status": status,
        }
        if status in ("need_review", "need_both"):
            review_needed.append(base_item)
        if status in ("need_supplement", "need_both"):
            supplement_needed.append(base_item)

    # review_needed: 按 pending_count 降序（待审越多越紧急）
    review_needed.sort(key=lambda x: (-x["pending_count"], -x["completeness_score"]))
    # supplement_needed: 按 approved 升序（approved=0 的排在最前），再按 pending 升序
    supplement_needed.sort(key=lambda x: (x["approved_count"], x["pending_count"], -x["total_count"]))

    # ---- 3. 数据缺失分析（按疾病分组，找出完全没有数据的省份）----
    disease_provinces: dict[str, set[str]] = {}
    for r in rows:
        if not r.disease or not r.province:
            continue
        normalized_dis = normalize_disease(r.disease)
        if normalized_dis not in disease_provinces:
            disease_provinces[normalized_dis] = set()
        for p in r.province.split(";"):
            p = p.strip()
            if p:
                disease_provinces[normalized_dis].add(p)

    data_gaps: list[dict] = []
    # 对 all_diseases（包含在 disease_provinces 中以及全部）都生成条目，
    # 保证数据"完全完整的疾病"（如麻疹）也能显示，方便用户一目了然。
    for dis in sorted(all_diseases):
        provs = disease_provinces.get(dis, set())
        missing = [p for p in CHINA_PROVINCES if p not in provs]
        if len(missing) == 0:
            # 完全覆盖 CHINA_PROVINCES → 直接记 100%
            coverage = 100.0
        else:
            denom = max(len(CHINA_PROVINCES), 1)
            coverage = round(len(provs) / denom * 100, 2)
        data_gaps.append({
            "disease": dis,
            "covered_provinces": sorted(provs),
            "missing_provinces": missing,
            "covered_count": len(provs),
            "missing_count": len(missing),
            "coverage_percent": min(coverage, 100.0),
        })
    # 越完善（缺失越少）越排在前面；缺失相同时覆盖省数越多越前，再按疾病名稳定排序
    data_gaps.sort(key=lambda x: (x["missing_count"], -x["covered_count"], x["disease"]))
    total_gap_combos = sum(g["missing_count"] for g in data_gaps)

    # ---- 4. 省份×年份矩阵（带完整性评分，按完整性降序）----
    py_matrix_map: dict[str, dict[int, dict]] = {}
    for r in rows:
        if not r.province:
            continue
        prov = r.province.split(";")[0].strip()
        if not prov:
            continue
        year = r.collection_year
        if prov not in py_matrix_map:
            py_matrix_map[prov] = {}
        if year not in py_matrix_map[prov]:
            py_matrix_map[prov][year] = {"total": 0, "pending": 0, "approved": 0, "approved_ab": 0}
        py_matrix_map[prov][year]["total"] += r.cnt
        if r.review_status == "pending":
            py_matrix_map[prov][year]["pending"] += r.cnt
        elif r.review_status == "approved":
            py_matrix_map[prov][year]["approved"] += r.cnt
            if r.quality_grade in ("A", "B"):
                py_matrix_map[prov][year]["approved_ab"] += r.cnt

    province_year_matrix: list[dict] = []
    for prov, year_data in py_matrix_map.items():
        total_for_prov = sum(yd["total"] for yd in year_data.values())
        pending_for_prov = sum(yd["pending"] for yd in year_data.values())
        approved_for_prov = sum(yd["approved"] for yd in year_data.values())
        approved_ab_for_prov = sum(yd["approved_ab"] for yd in year_data.values())
        # 为每个年份单元格追加 completeness_score 和 status
        years_formatted: dict[str, dict] = {}
        for y in sorted(y for y in year_data if y is not None):
            cell = year_data[y]
            years_formatted[str(y)] = {
                **cell,
                "completeness_score": _calc_completeness(cell["approved_ab"], cell["pending"], len(year_list)),
                "status": _status_label(cell["approved_ab"], cell["pending"]),
            }
        # 省份整体完整性评分（所有年份的加权）
        overall_score = _calc_completeness(approved_ab_for_prov, pending_for_prov, len(year_list))
        overall_status = _status_label(approved_ab_for_prov, pending_for_prov)
        province_year_matrix.append({
            "province": prov,
            "years": years_formatted,
            "total": total_for_prov,
            "pending": pending_for_prov,
            "approved": approved_for_prov,
            "approved_ab": approved_ab_for_prov,
            "completeness_score": overall_score,
            "status": overall_status,
        })

    # 按完整性评分降序（完善的排在前面），评分相同按 total 降序
    province_year_matrix.sort(key=lambda x: (-x["completeness_score"], -x["total"]))

    # ---- 5. 城市×年份矩阵（新增地区维度）----
    cy_matrix_map: dict[tuple[str, str], dict[int, dict]] = {}
    for r in rows:
        if not r.province or not r.city:
            continue
        prov = r.province.split(";")[0].strip()
        city = r.city.replace("；", ";").split(";")[0].strip()
        if not prov or not city:
            continue
        year = r.collection_year
        key = (prov, city)
        if key not in cy_matrix_map:
            cy_matrix_map[key] = {}
        if year not in cy_matrix_map[key]:
            cy_matrix_map[key][year] = {"total": 0, "pending": 0, "approved": 0, "approved_ab": 0}
        cy_matrix_map[key][year]["total"] += r.cnt
        if r.review_status == "pending":
            cy_matrix_map[key][year]["pending"] += r.cnt
        elif r.review_status == "approved":
            cy_matrix_map[key][year]["approved"] += r.cnt
            if r.quality_grade in ("A", "B"):
                cy_matrix_map[key][year]["approved_ab"] += r.cnt

    city_year_matrix: list[dict] = []
    for (prov, city), year_data in cy_matrix_map.items():
        total_city = sum(yd["total"] for yd in year_data.values())
        pending_city = sum(yd["pending"] for yd in year_data.values())
        approved_city = sum(yd["approved"] for yd in year_data.values())
        approved_ab_city = sum(yd["approved_ab"] for yd in year_data.values())
        years_formatted: dict[str, dict] = {}
        for y in sorted(y for y in year_data if y is not None):
            cell = year_data[y]
            years_formatted[str(y)] = {
                **cell,
                "completeness_score": _calc_completeness(cell["approved_ab"], cell["pending"], len(year_list)),
                "status": _status_label(cell["approved_ab"], cell["pending"]),
            }
        overall_score = _calc_completeness(approved_ab_city, pending_city, len(year_list))
        overall_status = _status_label(approved_ab_city, pending_city)
        city_year_matrix.append({
            "province": prov,
            "city": city,
            "years": years_formatted,
            "total": total_city,
            "pending": pending_city,
            "approved": approved_city,
            "approved_ab": approved_ab_city,
            "completeness_score": overall_score,
            "status": overall_status,
        })

    # 城市矩阵同样按完整性降序
    city_year_matrix.sort(key=lambda x: (-x["completeness_score"], -x["total"]))

    # ---- 6. 概览统计（附加）----
    # 统计"完善"、"待审核"、"需补充"的省×年组合数
    status_counts_combos = {"well_covered": 0, "need_review": 0, "need_supplement": 0, "need_both": 0}
    for row in province_year_matrix:
        for cell in row["years"].values():
            status_counts_combos[cell["status"]] = status_counts_combos.get(cell["status"], 0) + 1

    overview = {
        "total_data_points": total_dp,
        "total_provinces": len(all_provinces),
        "total_cities": len(all_cities),
        "total_diseases": len(all_diseases),
        "year_range": [year_list[0], year_list[-1]] if year_list else None,
        "years": year_list,
        "pending_count": status_counts["pending"],
        "approved_count": status_counts["approved"],
        "rejected_count": status_counts["rejected"],
        "total_gap_combos": total_gap_combos,
        # 新增：组合状态统计
        "combo_status_counts": status_counts_combos,
        # 新增：阈值说明
        "well_covered_threshold": WELL_COVERED_THRESHOLD,
    }

    return {
        "overview": overview,
        "review_needed": review_needed,
        "supplement_needed": supplement_needed,
        "data_gaps": data_gaps,
        "province_year_matrix": province_year_matrix,
        "city_year_matrix": city_year_matrix,
    }


# ============================================================
# P0: FOI（感染力 Force of Infection）+ 群体免疫阈值分析
# 纯分析逻辑，不新增数据库字段，数据全部来自已审核的 seroprevalence 数据点
# ============================================================

# ---- 流行病学参数 ----
# 平均寿命（年），用于 R0 = λ × L（Catalitic 模型近似）

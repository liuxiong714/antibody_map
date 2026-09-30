"""流行病学 / 病原学监测数据只读 API（阶段3：前端展示整合）。

数据来源：
  - 流行病学指标（发病人数/发病率/死亡率/死亡数）：data_point 表，data_type ∈ {incidence, case_count, mortality, death_count}
  - 病原学监测：独立表 pathogen_monitoring（阶段2 提取落表）

本模块全部为只读（GET），不修改任何数据，与既有血清抗体展示/分析互不影响。
流行病学聚合不套用阳性率的样本量加权逻辑（对"发病人数/发病率"加权无流行病学意义），
按各自语义处理：case_count/death_count 求和，incidence/mortality 取均值。
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.data_point import DataPoint
from app.models.pathogen_monitoring import PathogenMonitoring
from app.schemas.common import ApiResponse

router = APIRouter()

EPIDEMIC_DATA_TYPES = ("incidence", "case_count", "mortality", "death_count")
# data_type 语义：True=求和型（发病人数/死亡数），False=比率型（发病率/死亡率）
_SUM_TYPES = {"case_count", "death_count"}


def _page(row_dict: dict, page: int, page_size: int) -> dict:
    rows = row_dict.get("rows", [])
    total = row_dict.get("total", len(rows))
    start = (page - 1) * page_size
    return {
        "items": rows[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/epidemic/overview", response_model=ApiResponse, summary="流行病学指标概览", description="按疾病/省份聚合发病人数、发病率、死亡率、死亡数的汇总统计（含省级分布）")
async def epidemic_overview(
    disease: str | None = Query(None, description="disease key"),
    province: str | None = Query(None, description="省份筛选"),
    year_start: int | None = Query(None, description="起始年份"),
    year_end: int | None = Query(None, description="结束年份"),
    db: AsyncSession = Depends(get_db),
):
    """流行病学指标概览：按 data_type 汇总 + 省级分布。只读已审核数据点。"""
    base = select(DataPoint).where(DataPoint.review_status == "approved")
    base = base.where(DataPoint.data_type.in_(EPIDEMIC_DATA_TYPES))
    if disease:
        base = base.where(DataPoint.disease == disease)
    if province:
        base = base.where(DataPoint.province == province)
    if year_start:
        base = base.where(DataPoint.collection_year >= year_start)
    if year_end:
        base = base.where(DataPoint.collection_year <= year_end)
    rows = (await db.execute(base)).scalars().all()

    # 按 data_type 顶层汇总 + 省级分布
    by_type: dict[str, dict] = {}
    by_province: dict[str, dict] = {}
    lit_ids: set = set()
    for dp in rows:
        if dp.literature_id:
            lit_ids.add(dp.literature_id)
        p = dp.province or "未知"
        bp = by_province.setdefault(p, {"province": p, "lits": set()})
        bp.setdefault("lits").add(dp.literature_id)

        dt = dp.data_type or ""
        agg = by_type.setdefault(dt, {
            "data_type": dt, "count": 0, "literature_count": 0,
            "first_year": None, "latest_year": None,
            "sum": 0.0, "avg": 0.0, "raw_values": [],
            "units": {},
        })
        agg["count"] += 1
        agg["literature_count"] = len(bp["lits"])  # 会随后续点修正，底部重算
        if dp.collection_year is not None:
            if agg["first_year"] is None or dp.collection_year < agg["first_year"]:
                agg["first_year"] = dp.collection_year
            if agg["latest_year"] is None or dp.collection_year > agg["latest_year"]:
                agg["latest_year"] = dp.collection_year
        if dp.value is not None:
            agg["sum"] = round(float(agg["sum"]) + float(dp.value), 6)
            agg["raw_values"].append(float(dp.value))
            if dp.unit:
                agg["units"][dp.unit] = agg["units"].get(dp.unit, 0) + 1

        # 省级聚合：求和型求和，比率型求和后底部求均值
        key = f"__{dt}_sum"
        bpo = bp.setdefault(key, 0.0)
        if dp.value is not None:
            bp[key] = round(bpo + float(dp.value), 6)
        cnt_key = f"__{dt}_cnt"
        bp[cnt_key] = bp.get(cnt_key, 0) + 1 if dp.value is not None else bp.get(cnt_key, 0)

    # 收尾：重算每种 type 的文献数、均值、单位；省级转 final
    for dt, agg in by_type.items():
        agg["literature_count"] = len({dp.literature_id for dp in rows if dp.data_type == dt})
        if agg["raw_values"]:
            agg["avg"] = round(sum(agg["raw_values"]) / len(agg["raw_values"]), 6)
        agg["unit"] = max(agg["units"], key=agg["units"].get) if agg["units"] else None
        agg.pop("raw_values", None)
        agg.pop("units", None)

    province_rows = []
    for p, bp in by_province.items():
        row: dict = {"province": p, "literature_count": len(bp.pop("lits"))}
        for dt in EPIDEMIC_DATA_TYPES:
            s = bp.pop(f"__{dt}_sum", None)
            c = bp.pop(f"__{dt}_cnt", 0)
            if s is None:
                row[dt] = None
            elif dt in _SUM_TYPES:
                row[dt] = round(s, 2)
            else:
                row[dt] = round(s / c, 6) if c else None
        province_rows.append(row)
    province_rows.sort(key=lambda r: r["literature_count"], reverse=True)

    return ApiResponse(data={
        "by_type": [by_type.get(dt, {"data_type": dt, "count": 0, "literature_count": 0}) for dt in
                    ["incidence", "case_count", "mortality", "death_count"]],
        "by_province": province_rows,
        "total_literatures": len(lit_ids),
        "total_data_points": len(rows),
    })


@router.get("/epidemic/data-points", response_model=ApiResponse, summary="流行病学数据点明细", description="按疾病/省份/数据类型分页返回已审核流行病学指标数据点")
async def epidemic_data_points(
    disease: str | None = Query(None, description="disease key"),
    province: str | None = Query(None, description="省份筛选"),
    data_type: str | None = Query(None, description="incidence|case_count|mortality|death_count"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    base = select(DataPoint).where(DataPoint.review_status == "approved")
    base = base.where(DataPoint.data_type.in_(EPIDEMIC_DATA_TYPES))
    if disease:
        base = base.where(DataPoint.disease == disease)
    if province:
        base = base.where(DataPoint.province == province)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)
    rows = (await db.execute(base)).scalars().all()

    items = [{
        "id": str(dp.id),
        "literature_id": str(dp.literature_id) if dp.literature_id else None,
        "disease": dp.disease,
        "province": dp.province,
        "city": dp.city,
        "data_type": dp.data_type,
        "value": float(dp.value) if dp.value is not None else None,
        "unit": dp.unit,
        "sample_size": dp.sample_size,
        "collection_year": dp.collection_year,
        "population": dp.population,
        "source_context": dp.source_context,
    } for dp in rows]

    return ApiResponse(data=_page({"rows": items, "total": len(items)}, page, page_size))


@router.get("/epidemic/pathogen-monitoring", response_model=ApiResponse, summary="病原学监测列表与分布", description="按疾病/省份/来源分页返回病原学监测记录，并统计基因型/血清型/亚型/病原体类型分布")
async def pathogen_monitoring_list(
    disease: str | None = Query(None, description="disease key"),
    province: str | None = Query(None, description="省份筛选"),
    source: str | None = Query(None, description="审核状态: approved|pending|rejected"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    base = select(PathogenMonitoring)
    if disease:
        base = base.where(PathogenMonitoring.disease == disease)
    if province:
        base = base.where(PathogenMonitoring.province == province)
    if source:
        base = base.where(PathogenMonitoring.review_status == source)
    rows = (await db.execute(base)).scalars().all()

    # 分布统计（记录量小，Python 聚合即可）
    def _dist(field: str):
        counter: dict[str, int] = {}
        for pm in rows:
            v = getattr(pm, field)
            if v:
                counter[v] = counter.get(v, 0) + 1
        return [{"value": k, "count": c} for k, c in
                sorted(counter.items(), key=lambda x: x[1], reverse=True)]

    items = [{
        "id": str(pm.id),
        "literature_id": str(pm.literature_id) if pm.literature_id else None,
        "disease": pm.disease,
        "pathogen_type": pm.pathogen_type,
        "pathogen_name": pm.pathogen_name,
        "serotype": pm.serotype,
        "genotype": pm.genotype,
        "subtype": pm.subtype,
        "lineage": pm.lineage,
        "variant_sites": pm.variant_sites,
        "detection_rate": float(pm.detection_rate) if pm.detection_rate is not None else None,
        "isolation_count": pm.isolation_count,
        "sample_size": pm.sample_size,
        "detection_method": pm.detection_method,
        "population": pm.population,
        "specimen": pm.specimen,
        "region": pm.region,
        "province": pm.province,
        "city": pm.city,
        "collection_year": pm.collection_year,
        "source_context": pm.source_context,
        "review_status": pm.review_status,
    } for pm in rows]

    return ApiResponse(data={
        "list": _page({"rows": items, "total": len(items)}, page, page_size),
        "by_genotype": _dist("genotype"),
        "by_serotype": _dist("serotype"),
        "by_subtype": _dist("subtype"),
        "by_pathogen_type": _dist("pathogen_type"),
        "by_pathogen_name": _dist("pathogen_name"),
    })


@router.get("/epidemic/pathogen-monitoring/literature/{literature_id}", response_model=ApiResponse, summary="单篇文献病原学记录", description="按文献返回该文献的病原学监测记录（只读，供文献详情展示）")
async def pathogen_monitoring_by_literature(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PathogenMonitoring).where(PathogenMonitoring.literature_id == literature_id)
    rows = (await db.execute(stmt)).scalars().all()

    items = [{
        "id": str(pm.id),
        "disease": pm.disease,
        "pathogen_type": pm.pathogen_type,
        "pathogen_name": pm.pathogen_name,
        "serotype": pm.serotype,
        "genotype": pm.genotype,
        "subtype": pm.subtype,
        "lineage": pm.lineage,
        "variant_sites": pm.variant_sites,
        "detection_rate": float(pm.detection_rate) if pm.detection_rate is not None else None,
        "isolation_count": pm.isolation_count,
        "sample_size": pm.sample_size,
        "detection_method": pm.detection_method,
        "population": pm.population,
        "specimen": pm.specimen,
        "region": pm.region,
        "province": pm.province,
        "city": pm.city,
        "collection_year": pm.collection_year,
        "source_context": pm.source_context,
        "review_status": pm.review_status,
    } for pm in rows]

    return ApiResponse(data={"items": items, "total": len(items)})
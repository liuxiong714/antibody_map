import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.kg_entity import KGEntity
from app.models.kg_triple import KGTriple
from app.schemas.common import ApiResponse
from app.schemas.kg_schemas import KGBatchRequest
from app.services import knowledge_graph_service as kg
from app.services.kg_entity_resolver import persist_triples

router = APIRouter(prefix="/kg", tags=["knowledge_graph"])
logger = logging.getLogger("kg")


@router.get("/overview", response_model=ApiResponse, summary="知识图谱概览")
async def overview(db: AsyncSession = Depends(get_db)):
    data = await kg.get_overview(db)
    return ApiResponse(data=data)


@router.get("/options", response_model=ApiResponse, summary="图谱筛选选项")
async def options(db: AsyncSession = Depends(get_db)):
    data = await kg.get_options(db)
    return ApiResponse(data=data)


@router.get("/graph", response_model=ApiResponse, summary="知识图谱数据")
async def graph(
    disease: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    data_type: Optional[str] = Query(None),
    year_start: Optional[int] = Query(None, ge=1900, le=2100),
    year_end: Optional[int] = Query(None, ge=1900, le=2100),
    max_nodes: int = Query(600, ge=50, le=5000),
    db: AsyncSession = Depends(get_db),
):
    data = await kg.get_graph(
        db,
        disease=disease,
        province=province,
        data_type=data_type,
        year_start=year_start,
        year_end=year_end,
        max_nodes=max_nodes,
    )
    return ApiResponse(data=data)


@router.post("/triples/batch", response_model=ApiResponse, summary="批量写入三元组")
async def batch_triples(
    req: KGBatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量写入 LLM 抽取的实体和三元组，自动消歧合并。"""
    lit_id = None
    if req.literature_id:
        try:
            lit_id = uuid.UUID(req.literature_id)
        except ValueError:
            return ApiResponse(code=1, message="无效的 literature_id")

    entities_data = [e.model_dump() for e in req.entities]
    triples_data = [t.model_dump() for t in req.triples]

    written = await persist_triples(db, entities_data, triples_data, lit_id)
    await db.commit()

    return ApiResponse(data={
        "written_triples": written,
        "total_entities": len(entities_data),
        "total_triples": len(triples_data),
    })


@router.get("/entities/search", response_model=ApiResponse, summary="模糊搜索实体")
async def search_entities(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    type: Optional[str] = Query(None, description="实体类型过滤"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """在持久化实体表中模糊搜索（同时回退到计算式维度搜索）。"""
    results = []

    # 1. 搜索持久化 kg_entity 表
    stmt = select(KGEntity).where(
        KGEntity.merged_into.is_(None),
        KGEntity.name.ilike(f"%{q}%"),
    )
    if type:
        stmt = stmt.where(KGEntity.entity_type == type)
    stmt = stmt.limit(limit)
    rows = await db.execute(stmt)
    for ent in rows.scalars():
        # 统计关联三元组数
        count_stmt = select(func.count()).where(
            or_(KGTriple.subject_id == ent.id, KGTriple.object_id == ent.id)
        )
        count_result = await db.execute(count_stmt)
        triple_count = count_result.scalar() or 0
        results.append({
            "id": ent.id,
            "entity_type": ent.entity_type,
            "name": ent.name,
            "attributes": ent.attributes or {},
            "triple_count": triple_count,
            "source": "persistent",
        })

    # 2. 若持久化结果不足，回退到计算式维度搜索
    if len(results) < limit:
        computed = await kg.search_computed(db, q, type, limit - len(results))
        results.extend(computed)

    return ApiResponse(data=results[:limit])


@router.get("/query/direct", response_model=ApiResponse, summary="查询两个实体的直接关系")
async def query_direct(
    subject_id: str = Query(..., description="主体实体ID"),
    object_id: str = Query(..., description="客体实体ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询持久化三元组中两个实体的直接关系。"""
    stmt = select(KGTriple).where(
        KGTriple.subject_id == subject_id,
        KGTriple.object_id == object_id,
    )
    rows = await db.execute(stmt)
    triples = []
    for t in rows.scalars():
        triples.append({
            "predicate": t.predicate,
            "confidence": t.confidence,
            "source_context": t.source_context,
        })
    return ApiResponse(data={"triples": triples, "count": len(triples)})


@router.get("/query/path", response_model=ApiResponse, summary="BFS路径推理")
async def query_path(
    from_id: str = Query(..., description="起始实体ID"),
    to_id: str = Query(..., description="目标实体ID"),
    max_depth: int = Query(3, ge=1, le=4, description="最大搜索深度"),
    db: AsyncSession = Depends(get_db),
):
    """BFS 路径搜索（限深 max_depth 层），在持久化三元组上搜索。"""
    if from_id == to_id:
        return ApiResponse(data={"found": True, "path": [{"id": from_id, "depth": 0}], "depth": 0})

    # 加载所有三元组构建邻接表（KG 数据量有限，全量加载可行）
    stmt = select(KGTriple.subject_id, KGTriple.predicate, KGTriple.object_id)
    rows = await db.execute(stmt)
    adj: dict[str, list[tuple[str, str]]] = {}
    for sid, pred, oid in rows:
        adj.setdefault(sid, []).append((pred, oid))

    # BFS
    from collections import deque
    queue = deque([(from_id, [{"id": from_id, "predicate": None}])])
    visited = {from_id}

    while queue:
        current_id, path = queue.popleft()
        if len(path) - 1 >= max_depth:
            continue
        for pred, neighbor_id in adj.get(current_id, []):
            if neighbor_id == to_id:
                final_path = path + [{"id": neighbor_id, "predicate": pred}]
                # 补全路径上的实体信息
                ent_ids = [p["id"] for p in final_path]
                ent_stmt = select(KGEntity).where(KGEntity.id.in_(ent_ids))
                ent_rows = await db.execute(ent_stmt)
                ent_map = {e.id: e for e in ent_rows.scalars()}
                for p in final_path:
                    ent = ent_map.get(p["id"])
                    if ent:
                        p["name"] = ent.name
                        p["entity_type"] = ent.entity_type
                return ApiResponse(data={
                    "found": True,
                    "path": final_path,
                    "depth": len(final_path) - 1,
                })
            if neighbor_id not in visited:
                visited.add(neighbor_id)
                queue.append((neighbor_id, path + [{"id": neighbor_id, "predicate": pred}]))

    return ApiResponse(data={"found": False, "path": [], "depth": 0})


@router.get("/survey/{survey_id}/subgraph", response_model=ApiResponse, summary="获取调查的星型子图")
async def survey_subgraph(
    survey_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取某个 survey 实体关联的所有三元组子图。"""
    # 查找以 survey_id 为 subject 的所有三元组
    stmt = select(KGTriple).where(
        or_(KGTriple.subject_id == survey_id, KGTriple.object_id == survey_id)
    )
    rows = await db.execute(stmt)
    triples = rows.scalars().all()

    if not triples:
        return ApiResponse(data={"nodes": [], "edges": []})

    # 收集所有涉及的实体 ID
    ent_ids = set()
    for t in triples:
        ent_ids.add(t.subject_id)
        ent_ids.add(t.object_id)

    # 加载实体
    ent_stmt = select(KGEntity).where(KGEntity.id.in_(ent_ids))
    ent_rows = await db.execute(ent_stmt)
    ent_map = {e.id: e for e in ent_rows.scalars()}

    nodes = []
    for eid in ent_ids:
        ent = ent_map.get(eid)
        if ent:
            nodes.append({
                "id": ent.id,
                "type": ent.entity_type,
                "label": ent.name,
                "attributes": ent.attributes or {},
            })

    edges = []
    for t in triples:
        edges.append({
            "source": t.subject_id,
            "target": t.object_id,
            "type": t.predicate,
            "confidence": t.confidence,
            "source_context": t.source_context,
        })

    return ApiResponse(data={"nodes": nodes, "edges": edges})


@router.get("/stats", response_model=ApiResponse, summary="图谱统计概览")
async def stats(db: AsyncSession = Depends(get_db)):
    """持久化 KG 统计：节点数/关系数/各类型分布。"""
    entity_counts = {}
    for et in ["survey", "pathogen", "geo_area", "time_period", "host_group",
               "lab_assay", "indicator", "institution", "author", "sample",
               "vaccine", "data_quality", "publication"]:
        count_stmt = select(func.count()).select_from(KGEntity).where(
            KGEntity.entity_type == et,
            KGEntity.merged_into.is_(None),
        )
        result = await db.execute(count_stmt)
        entity_counts[et] = result.scalar() or 0

    relation_counts = {}
    for rt in ["surveyed_at", "covered_time", "targets_host", "detects_pathogen",
               "uses_assay", "reports_indicator", "conducted_by", "authored_by",
               "affiliated_with", "has_sample", "vaccinated_with", "has_quality",
               "contains_survey", "same_cohort", "adjusted_for"]:
        count_stmt = select(func.count()).select_from(KGTriple).where(
            KGTriple.predicate == rt
        )
        result = await db.execute(count_stmt)
        relation_counts[rt] = result.scalar() or 0

    total_entities = sum(entity_counts.values())
    total_triples = sum(relation_counts.values())

    return ApiResponse(data={
        "total_entities": total_entities,
        "total_triples": total_triples,
        "entity_counts": entity_counts,
        "relation_counts": relation_counts,
    })

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.config import settings
from app.core import redis_background_tasks as bg
from app.models.kg_entity import KGEntity
from app.models.kg_qa_log import KgQaLog
from app.models.kg_triple import KGTriple
from app.models.literature import Literature
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.kg_schemas import KGBatchRequest
from app.services import knowledge_graph_service as kg
from app.services.kg_entity_resolver import (
    persist_triples,
    _normalize_for_dedup,
    _edit_distance_similarity,
)
from app.services.kg_qa_service import ask_question


class QARequest(BaseModel):
    question: str
    prev_slots: dict[str, str] | None = None


class EntityMergeRequest(BaseModel):
    keep_id: str
    merge_ids: list[str]


class QaFeedbackRequest(BaseModel):
    feedback: str  # up / down


class TripleReviewRequest(BaseModel):
    ids: list[str]
    status: str  # approved / rejected


class TripleDeleteRequest(BaseModel):
    ids: list[str]

router = APIRouter(prefix="/kg", tags=["knowledge_graph"])
logger = logging.getLogger("kg")


@router.get("/overview", response_model=ApiResponse, summary="知识图谱概览")
async def overview(
    review_status: list[str] = Query(["approved"], description="审核状态过滤（可重复传）：approved / pending / rejected"),
    db: AsyncSession = Depends(get_db),
):
    data = await kg.get_overview(db, review_statuses=review_status)
    return ApiResponse(data=data)


@router.get("/options", response_model=ApiResponse, summary="图谱筛选选项")
async def options(db: AsyncSession = Depends(get_db)):
    data = await kg.get_options(db)
    return ApiResponse(data=data)


@router.get("/graph", response_model=ApiResponse, summary="知识图谱数据")
async def graph(
    disease: str | None = Query(None),
    province: str | None = Query(None),
    data_type: str | None = Query(None),
    year_start: int | None = Query(None, ge=1900, le=2100),
    year_end: int | None = Query(None, ge=1900, le=2100),
    max_nodes: int = Query(600, ge=50, le=5000),
    review_status: list[str] = Query(["approved"], description="审核状态过滤（可重复传）：approved / pending / rejected"),
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
        review_statuses=review_status,
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


@router.get("/triples/review-sample", response_model=ApiResponse, summary="抽取质量评估：抽样待校验三元组")
async def triples_review_sample(
    limit: int = Query(20, ge=1, le=100, description="抽样数量"),
    min_confidence: float | None = Query(None, ge=0, le=1, description="最低置信度过滤"),
    db: AsyncSession = Depends(get_db),
):
    """抽样返回待人工校验的三元组（含实体名、来源文献标题与抽取上下文）。"""
    stmt = (
        select(KGTriple, KGEntity, KGEntity, Literature.title)
        .join(KGEntity, KGTriple.subject_id == KGEntity.id)
        .join(KGEntity, KGTriple.object_id == KGEntity.id)
        .outerjoin(Literature, KGTriple.literature_id == Literature.id)
        .where(KGTriple.review_status == "pending")
        .order_by(KGTriple.confidence.asc(), KGTriple.created_at.asc())
        .limit(limit)
    )
    if min_confidence is not None:
        stmt = stmt.where(KGTriple.confidence >= min_confidence)
    rows = (await db.execute(stmt)).all()
    items = [
        {
            "id": t.id,
            "subject": s.name,
            "subject_type": s.entity_type,
            "predicate": t.predicate,
            "object": o.name,
            "object_type": o.entity_type,
            "confidence": t.confidence,
            "source_context": t.source_context,
            "literature_id": str(t.literature_id) if t.literature_id else None,
            "literature_title": title,
        }
        for t, s, o, title in rows
    ]
    return ApiResponse(data=items)


@router.post("/triples/review", response_model=ApiResponse, summary="标记三元组校验结果（管理员）")
async def triples_review(
    req: "TripleReviewRequest",
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """将抽样三元组标记为 approved / rejected。"""
    if req.status not in ("approved", "rejected"):
        return ApiResponse(code=1, message="status 仅支持 approved/rejected")
    ids = [i for i in req.ids if i]
    if not ids:
        return ApiResponse(code=1, message="ids 不能为空")
    result = await db.execute(select(KGTriple).where(KGTriple.id.in_(ids)))
    rows = result.scalars().all()
    for t in rows:
        t.review_status = req.status
    await db.commit()
    return ApiResponse(data={"updated": len(rows), "status": req.status})


@router.post("/triples/batch-delete", response_model=ApiResponse, summary="批量删除错误三元组（管理员）")
async def triples_batch_delete(
    req: "TripleDeleteRequest",
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """批量删除人工确认的错误三元组（连同悬空实体一起清理由 CASCADE 处理）。"""
    ids = [i for i in req.ids if i]
    if not ids:
        return ApiResponse(code=1, message="ids 不能为空")
    result = await db.execute(select(KGTriple).where(KGTriple.id.in_(ids)))
    rows = result.scalars().all()
    for t in rows:
        await db.delete(t)
    await db.commit()
    return ApiResponse(data={"deleted": len(rows)})


@router.get("/entities/search", response_model=ApiResponse, summary="模糊搜索实体")
async def search_entities(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    type: str | None = Query(None, description="实体类型过滤"),
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


def _ent_payload(ent: KGEntity, subj_counts: dict, obj_counts: dict) -> dict:
    """实体负载（含三元组计数）。"""
    return {
        "id": ent.id,
        "entity_type": ent.entity_type,
        "name": ent.name,
        "attributes": ent.attributes or {},
        "source_literature_id": str(ent.source_literature_id) if ent.source_literature_id else None,
        "triple_count": (subj_counts.get(ent.id, 0) or 0) + (obj_counts.get(ent.id, 0) or 0),
    }


@router.get("/entities/merge-candidates", response_model=ApiResponse, summary="实体合并候选（相似度聚类）")
async def merge_candidates(
    limit: int = Query(30, ge=1, le=100, description="最多返回候选组数"),
    db: AsyncSession = Depends(get_db),
):
    """发现疑似重复实体（同名 / 归一化后相似度 ≥ 85%），供管理员合并。"""
    stmt = select(KGEntity).where(KGEntity.merged_into.is_(None))
    rows = await db.execute(stmt)
    entities = list(rows.scalars().all())

    # 预统计三元组计数
    subj_counts = dict(
        (await db.execute(select(KGTriple.subject_id, func.count()).group_by(KGTriple.subject_id))).all()
    )
    obj_counts = dict(
        (await db.execute(select(KGTriple.object_id, func.count()).group_by(KGTriple.object_id))).all()
    )

    # 按实体类型分组
    by_type: dict[str, list[KGEntity]] = {}
    for e in entities:
        by_type.setdefault(e.entity_type, []).append(e)

    groups: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for etype, items in by_type.items():
        # 1) 归一化后完全同名的桶 → 直接成组
        buckets: dict[str, list[KGEntity]] = {}
        for e in items:
            buckets.setdefault(_normalize_for_dedup(e.name), []).append(e)
        for key, bucket in buckets.items():
            if len(bucket) >= 2:
                groups.append({
                    "entity_type": etype,
                    "reason": "同名",
                    "members": [_ent_payload(e, subj_counts, obj_counts) for e in bucket],
                })
                if len(groups) >= limit:
                    return ApiResponse(data=groups)
        # 2) 相似度 ≥ 0.85 的两两候选
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if a.id == b.id:
                    continue
                na, nb = _normalize_for_dedup(a.name), _normalize_for_dedup(b.name)
                if na == nb:
                    continue
                sim = _edit_distance_similarity(na, nb)
                if sim >= 0.85:
                    pair = tuple(sorted((str(a.id), str(b.id))))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    groups.append({
                        "entity_type": etype,
                        "reason": f"相似度 {sim:.0%}",
                        "members": [
                            _ent_payload(a, subj_counts, obj_counts),
                            _ent_payload(b, subj_counts, obj_counts),
                        ],
                    })
                    if len(groups) >= limit:
                        return ApiResponse(data=groups)

    return ApiResponse(data=groups)


@router.post("/entities/merge", response_model=ApiResponse, summary="合并实体（管理员）")
async def merge_entities(
    req: EntityMergeRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """将 merge_ids 指向的实体合并到 keep_id：
    1. 重定向涉及的三元组（subject/object → keep_id），自环与重复边删除
    2. 被合并实体标记 merged_into=keep_id（软合并，查询层自动隐藏）
    """
    if not req.merge_ids:
        return ApiResponse(code=1, message="merge_ids 不能为空")
    if req.keep_id in req.merge_ids:
        return ApiResponse(code=1, message="keep_id 不能出现在 merge_ids 中")

    keep = await db.get(KGEntity, req.keep_id)
    if not keep or keep.merged_into:
        return ApiResponse(code=1, message="保留实体不存在或已被合并")

    merge_set = set(req.merge_ids)
    for mid in merge_set:
        ent = await db.get(KGEntity, mid)
        if not ent or ent.merged_into:
            return ApiResponse(code=1, message=f"实体 {mid} 不存在或已被合并")
        if ent.entity_type != keep.entity_type:
            return ApiResponse(code=1, message="仅支持合并同类型实体")

    # 重定向三元组
    tri_stmt = select(KGTriple).where(
        or_(KGTriple.subject_id.in_(merge_set), KGTriple.object_id.in_(merge_set))
    )
    tri_rows = (await db.execute(tri_stmt)).scalars().all()
    moved = 0
    for t in tri_rows:
        new_subj = keep.id if str(t.subject_id) in merge_set else t.subject_id
        new_obj = keep.id if str(t.object_id) in merge_set else t.object_id
        if new_subj == new_obj:
            await db.delete(t)
            continue
        dup = await db.execute(select(KGTriple.id).where(
            KGTriple.subject_id == new_subj,
            KGTriple.predicate == t.predicate,
            KGTriple.object_id == new_obj,
            KGTriple.literature_id == t.literature_id,
            KGTriple.id != t.id,
        ))
        if dup.scalar_one_or_none():
            await db.delete(t)
        else:
            t.subject_id = new_subj
            t.object_id = new_obj
            moved += 1

    # 软合并
    for mid in merge_set:
        ent = await db.get(KGEntity, mid)
        ent.merged_into = keep.id

    await db.commit()
    logger.info(f"实体合并: keep={keep.id}({keep.name}), merged={len(merge_set)}, moved_triples={moved}")
    return ApiResponse(data={"merged": len(merge_set), "moved_triples": moved})


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
                final_path = [*path, {"id": neighbor_id, "predicate": pred}]
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
                queue.append((neighbor_id, [*path, {"id": neighbor_id, "predicate": pred}]))

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


@router.post("/extraction/trigger", response_model=ApiResponse, summary="手动触发三元组抽取")
async def trigger_kg_extraction(
    limit: int = Query(5, ge=1, le=50, description="本次处理篇数"),
    literature_ids: list[uuid.UUID] | None = Query(
        None,
        alias="literature_id",
        description="定向抽取的文献ID列表（可传多个）。提供时仅处理指定且已有缓存文本、未抽取的文献；省略时自动从全部未抽取缓存文本中取未处理的",
    ),
    model: str | None = Query(None, description="用户选择的抽取模型（本地 ollama: 前缀，或远程配置 remote:<id> /配置 UUID；空则用后端默认模型）"),
    db: AsyncSession = Depends(get_db),
):
    """手动触发 LLM 三元组抽取。

    - 省略 literature_id：从全部未抽取文献中顺序取前 limit 篇，串行执行抽取。
    - 指定 literature_id：仅对指定的文献做定向抽取（幂等，已抽取的会被忽略）。
    - model：允许用户指定抽取所用的模型（本地模型或系统配置的远程 API 模型）。
    每篇超时 300 秒。需要提前在 .env 中配置 ENABLE_KG_EXTRACTION=true。
    """
    if not getattr(settings, "ENABLE_KG_EXTRACTION", False):
        raise HTTPException(status_code=400, detail="ENABLE_KG_EXTRACTION 未开启，请在 .env 中配置后重启容器")

    text_dir = Path("/app/backend/data/pdfs")
    if not text_dir.exists():
        raise HTTPException(status_code=500, detail="缓存文本目录 /app/backend/data/pdfs 不存在")

    # 解析用户选择的模型 → (model_name, api_key, base_url)；远程配置按 remote:<id> 或配置 UUID 查库
    from app.core.extraction.llm_client import LLMClientMixin
    from app.models.api_model_config import ApiModelConfig

    resolved_model = ""
    resolved_key = ""
    resolved_url = ""
    if model:
        s = model.strip()
        lookup = s
        if s.startswith("remote:"):
            lookup = s[len("remote:"):]
        elif s.startswith("ollama:"):
            s = s.split(":", 1)[1]  # 剥离前缀，交给抽取器；从调用链传原生名
        try:
            uid = uuid.UUID(str(lookup))
            from sqlalchemy import select as _sel
            row = (await db.execute(_sel(ApiModelConfig).where(ApiModelConfig.id == uid))).scalar_one_or_none()
            if row is not None:
                resolved_model = row.model_name
                resolved_key = row.api_key or ""
                resolved_url = row.base_url or ""
                s = resolved_model
            else:
                s = lookup
        except (ValueError, TypeError, AttributeError):
            s = lookup
        resolved_model = s
        if not resolved_url:
            # 本地/默认模型：交由抽取器按模型自动解析 base_url（含 Ollama 网关归一化）
            resolved_url = LLMClientMixin._normalize_ollama_url(settings.LLM_BASE_URL or "")

    # 提交后台 Celery 异步任务，立即返回；进度可在系统设置「任务状态」页与知识图谱页查看
    from app.tasks.background_task import run_kg_extraction

    scope = "directed" if literature_ids else "auto"
    task = run_kg_extraction.delay(
        scope=scope, limit=limit,
        literature_ids=[str(i) for i in literature_ids] if literature_ids else None,
        model=resolved_model,
        api_key=resolved_key,
        base_url=resolved_url,
    )
    # 提交后立即登记任务状态，使前端立刻能按 task_id 轮询到"排队中"，避免 worker
    # 尚未拉取执行（尤其并发=1、前面任务未结束时）导致轮询短暂 404 被误判为过期。
    # worker 真正开始时会再次 start 覆盖为 running，随后 finish 写最终状态并清理 ids。
    try:
        await bg.start("kg_extraction", task_id=str(task.id), scope=scope)
    except Exception:
        logger.warning("登记知识图谱抽取任务状态失败（忽略）", exc_info=True)
    return ApiResponse(data={"task_id": str(task.id), "status": "queued", "scope": scope})


@router.post("/qa/ask", response_model=ApiResponse, summary="知识图谱咨询问答")
async def qa_ask(
    req: QARequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """知识图谱咨询问答接口。

    支持的问题类型：
    - 阳性率查询：如「北京麻疹阳性率是多少」
    - GMC 查询：如「上海麻疹GMC」
    - 地区对比：如「北京和上海麻疹阳性率对比」
    - 机构调查：如「哈尔滨医科大学做过哪些调查」
    - 人群查询：如「儿童麻疹抗体阳性率」
    - 趋势分析：如「麻疹阳性率变化趋势」
    - 未匹配问题自动降级到 LLM 回答

    同时写入问答日志（P3-⑩），供质量分析与反馈统计。
    """
    if not req.question or not req.question.strip():
        return ApiResponse(code=1, message="问题不能为空")

    result = await ask_question(req.question.strip(), db, prev_slots=req.prev_slots)
    # 记录问答日志（P3-⑩）：失败不影响主流程；log_id 回传给前端用于点赞/点踩
    try:
        log = KgQaLog(
            question=req.question.strip(),
            answer=result.get("answer") or "",
            method=result.get("method"),
            result_count=int(result.get("result_count") or 0),
            user_id=user.id if user else None,
        )
        db.add(log)
        await db.flush()
        await db.commit()
        result["log_id"] = str(log.id)
    except Exception:
        logger.warning("写入问答日志失败（忽略）", exc_info=True)
    return ApiResponse(data=result)


@router.post("/qa/log/{log_id}/feedback", response_model=ApiResponse, summary="问答反馈（点赞/点踩）")
async def qa_feedback(
    log_id: str,
    req: QaFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """用户对一次问答给出 up/down 反馈，供后续质量分析。"""
    if req.feedback not in ("up", "down"):
        return ApiResponse(code=1, message="feedback 仅支持 up/down")
    try:
        uid = uuid.UUID(log_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="日志不存在")
    result = await db.execute(select(KgQaLog).where(KgQaLog.id == uid))
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    log.feedback = req.feedback
    log.user_id = user.id if user else log.user_id
    await db.commit()
    return ApiResponse(data={"id": str(log.id), "feedback": log.feedback})

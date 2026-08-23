import logging
import uuid
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.models.data_point import DataPoint
from app.models.extraction_history import ExtractionHistory
from app.models.api_model_config import ApiModelConfig
from app.tasks.extract_task import process_literature

logger = logging.getLogger("uvicorn")


def _metadata_quality_breakdown(dp: DataPoint) -> dict | None:
    """元数据级质量明细（无文献全文时的实时估算，仅用于前端 Tooltip 展示）。

    有全文时以异步任务落库的 quality_score/quality_grade 为准；此处仅给出六项分项。
    """
    try:
        from app.services.quality_service import score_data_point

        result = score_data_point(dp, literature_text=None)
        return result["breakdown"]
    except Exception as e:  # 评分失败不应影响列表加载
        logger.warning(f"质量明细估算失败: {e}")
        return None


async def trigger_extraction(
    db: AsyncSession,
    literature_id: uuid.UUID,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_config_id: Optional[str] = None,
    clear_existing_data: bool = True,
    use_cache: bool = True,
) -> dict:
    """触发文献 AI 提取任务（通过 Celery 异步执行）

    安全说明：前端自定义的 api_key/base_url 会先加密存入 ApiModelConfig，
    任务参数只传递 model_config_id，避免明文凭证出现在 Redis 队列中。
    """
    # 检查文献存在
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = result.scalar_one_or_none()
    if not literature:
        raise ValueError("文献不存在")

    if not literature.file_path and not literature.abstract:
        raise ValueError("文献既无 PDF 文件也无摘要，无法提取")

    # == 竞态防护：检查当前状态，防止重复触发提取 ==
    if literature.extraction_status in ("processing", "queued"):
        raise ValueError(f"文献正在提取中（当前状态: {literature.extraction_status}），请等待完成后再试")

    # 更新状态为 queued（等待 Celery 工作线程处理）
    literature.extraction_status = "queued"
    literature.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # == 安全处理：如果前端提供了自定义 api_key，先加密存入 ApiModelConfig ==
    # 任务参数只传 model_config_id，不传明文 api_key/base_url
    resolved_model_config_id = model_config_id
    if api_key and not model_config_id:
        # 创建临时 ApiModelConfig，加密存储 api_key
        from app.core.crypto import encrypt
        temp_config = ApiModelConfig(
            name=f"临时提取配置-{model or 'default'}",
            model_name=model or "",
            base_url=base_url or "",
            is_active=False,
        )
        # 通过 hybrid_property setter 自动加密
        temp_config.api_key = api_key
        db.add(temp_config)
        await db.flush()
        resolved_model_config_id = str(temp_config.id)
        logger.info(f"前端自定义 API Key 已加密存入 ApiModelConfig(id={temp_config.id})")

    # 提交到 Celery 队列异步执行（失败标记与重试由任务自身处理）
    lit_id_str = str(literature_id)
    process_literature.delay(
        literature_id=lit_id_str,
        model=model,
        model_config_id=resolved_model_config_id,
        clear_existing_data=clear_existing_data,
        use_cache=use_cache,
    )

    return {
        "literature_id": lit_id_str,
        "status": "queued",
    }


async def get_extraction_status(
    db: AsyncSession,
    literature_id: uuid.UUID,
) -> dict:
    """获取提取状态"""
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = result.scalar_one_or_none()
    if not literature:
        raise ValueError("文献不存在")

    # 查询数据点数量
    count_result = await db.execute(
        select(func.count(DataPoint.id)).where(
            DataPoint.literature_id == literature_id
        )
    )
    data_point_count = count_result.scalar() or 0

    return {
        "literature_id": str(literature_id),
        "status": literature.extraction_status,
        "extracted_count": literature.extracted_count,
        "approved_count": literature.approved_count,
        "data_point_count": data_point_count,
        # LLM token 用量与费用（提取完成时写入，未提取时为默认值）
        "llm_model_used": literature.llm_model_used,
        "prompt_tokens": literature.prompt_tokens or 0,
        "completion_tokens": literature.completion_tokens or 0,
        "total_tokens": literature.total_tokens or 0,
        "llm_cost_usd": float(literature.llm_cost_usd) if literature.llm_cost_usd is not None else 0.0,
        "llm_call_count": literature.llm_call_count or 0,
        "llm_usage_detail": literature.llm_usage_detail,
    }


async def get_extraction_results(
    db: AsyncSession,
    literature_id: uuid.UUID,
) -> list[dict]:
    """获取提取的数据点列表"""
    result = await db.execute(
        select(DataPoint).where(
            DataPoint.literature_id == literature_id
        ).order_by(DataPoint.created_at.desc())
    )
    data_points = result.scalars().all()

    # 一次性解析审核人姓名（reviewer_id -> display_name/username）
    from app.models.user import User

    reviewer_ids = {dp.reviewer_id for dp in data_points if dp.reviewer_id}
    reviewer_names: dict[uuid.UUID, str] = {}
    if reviewer_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(reviewer_ids)))
        ).scalars().all()
        reviewer_names = {u.id: (u.display_name or u.username) for u in users}

    return [
        {
            "id": str(dp.id),
            "disease": dp.disease,
            "region": dp.region,
            "province": dp.province,
            "city": dp.city,
            "data_type": dp.data_type,
            "value": float(dp.value) if dp.value else None,
            "unit": dp.unit,
            "ci_lower": float(dp.ci_lower) if dp.ci_lower else None,
            "ci_upper": float(dp.ci_upper) if dp.ci_upper else None,
            "sample_size": dp.sample_size,
            "method": dp.method,
            "assay": dp.assay,
            "population": dp.population,
            "age_min": dp.age_min,
            "age_max": dp.age_max,
            "collection_year": dp.collection_year,
            "source_page": dp.source_page,
            "source_context": dp.source_context,
            # P0 新增：精确字符级溯源
            "source_char_start": dp.source_char_start,
            "source_char_end": dp.source_char_end,
            "is_grounded": bool(dp.is_grounded),
            "confidence": dp.confidence,
            "review_status": dp.review_status,
            "review_comment": dp.review_comment,
            "reviewer_id": str(dp.reviewer_id) if dp.reviewer_id else None,
            "reviewer_name": reviewer_names.get(dp.reviewer_id) if dp.reviewer_id else None,
            "reviewed_at": dp.reviewed_at.isoformat() if dp.reviewed_at else None,
            # 质量分级（审核通过后异步打分写入；breakdown 为元数据级实时估算，用于前端 Tooltip 明细）
            "quality_score": dp.quality_score,
            "quality_grade": dp.quality_grade,
            "estimate_grade": dp.estimate_grade,
            "quality_breakdown": _metadata_quality_breakdown(dp),
            "created_at": dp.created_at.isoformat() if dp.created_at else None,
            "updated_at": dp.updated_at.isoformat() if dp.updated_at else None,
        }
        for dp in data_points
    ]


async def get_extraction_history(
    db: AsyncSession,
    literature_id: uuid.UUID,
) -> list[dict]:
    """获取文献的 AI 提取历史记录"""
    result = await db.execute(
        select(ExtractionHistory).where(
            ExtractionHistory.literature_id == literature_id
        ).order_by(ExtractionHistory.extracted_at.desc())
    )
    history_list = result.scalars().all()

    return [
        {
            "id": str(h.id),
            "extracted_at": h.extracted_at.isoformat() if h.extracted_at else None,
            "model": h.model,
            "status": h.status,
            "data_point_count": h.data_point_count,
            "error_message": h.error_message,
            "prompt_tokens": h.prompt_tokens,
            "completion_tokens": h.completion_tokens,
            "total_tokens": h.total_tokens,
            "llm_cost_usd": float(h.llm_cost_usd) if h.llm_cost_usd is not None else 0.0,
            "llm_call_count": h.llm_call_count,
            "llm_usage_detail": h.llm_usage_detail,
        }
        for h in history_list
    ]


async def review_data_points(
    db: AsyncSession,
    literature_id: uuid.UUID,
    ids: list[str],
    status: str,
    comment: Optional[str],
    reviewer_id: uuid.UUID,
) -> int:
    """批量审核数据点：写入审核意见、审核人与审核时间。

    审核状态固定为 status（approved/rejected），仅覆盖给定 ids 且属于该文献的数据点。
    返回受影响行数。调用方负责 commit。
    """
    uuids = [uuid.UUID(i) for i in ids]
    now = datetime.now(timezone.utc)
    stmt = (
        update(DataPoint)
        .where(DataPoint.id.in_(uuids))
        .where(DataPoint.literature_id == literature_id)
        .values(
            review_status=status,
            review_comment=comment,
            reviewer_id=reviewer_id,
            reviewed_at=now,
        )
    )
    result = await db.execute(stmt)
    return result.rowcount


async def get_review_stats(db: AsyncSession) -> dict:
    """审核统计：按疾病 / 审核人维度聚合审核量、通过率、平均审核时间。

    平均审核时间 = approved 与 rejected 均视为已审核，取 reviewed_at 与 created_at 的分钟差均值。
    """
    from app.models.user import User

    reviewed_rows = (
        select(
            DataPoint.disease,
            DataPoint.reviewer_id,
            DataPoint.review_status,
            DataPoint.reviewed_at,
            DataPoint.created_at,
        )
        .where(DataPoint.review_status.in_(("approved", "rejected")))
        .where(DataPoint.reviewed_at.is_not(None))
    )
    rows = (await db.execute(reviewed_rows)).all()

    def _fold(items):
        total = len(items)
        approved = sum(1 for st, _, _ in items if st == "approved")
        durations = [
            (rv - created).total_seconds() / 60.0
            for st, rv, created in items
            if rv and created and rv > created
        ]
        avg_min = round(sum(durations) / len(durations), 2) if durations else None
        return {
            "reviewed": total,
            "approved": approved,
            "rejected": total - approved,
            "pass_rate": round(approved / total, 4) if total else 0.0,
            "avg_review_minutes": avg_min,
        }

    # 按疾病聚合
    by_disease: dict[str, list] = {}
    for disease, _rid, st, rv, created in rows:
        key = disease or "未知"
        by_disease.setdefault(key, []).append((st, rv, created))
    total_by_disease = [
        {"disease": key, **_fold(items)} for key, items in by_disease.items()
    ]
    total_by_disease.sort(key=lambda x: x["reviewed"], reverse=True)

    # 按审核人聚合（汇总用户 id -> 名称）
    reviewer_ids = {r.reviewer_id for r in rows if r.reviewer_id}
    reviewer_names: dict[uuid.UUID, str] = {}
    if reviewer_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(reviewer_ids)))
        ).scalars().all()
        reviewer_names = {
            u.id: (u.display_name or u.username or str(u.id)) for u in users
        }

    by_reviewer: dict[uuid.UUID, list] = {}
    for _disease, rid, st, rv, created in rows:
        if not rid:
            continue
        by_reviewer.setdefault(rid, []).append((st, rv, created))
    total_by_reviewer = [
        {
            "reviewer_id": str(rid),
            "reviewer_name": reviewer_names.get(rid, "未知用户"),
            **_fold(items),
        }
        for rid, items in by_reviewer.items()
    ]
    total_by_reviewer.sort(key=lambda x: x["reviewed"], reverse=True)

    all_items = [(st, rv, created) for _d, _r, st, rv, created in rows]
    return {
        "grand_total": _fold(all_items),
        "by_disease": total_by_disease,
        "by_reviewer": total_by_reviewer,
    }

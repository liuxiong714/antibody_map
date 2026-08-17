import logging
import uuid
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.models.data_point import DataPoint
from app.models.extraction_history import ExtractionHistory
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
    clear_existing_data: bool = True,
) -> dict:
    """触发文献 AI 提取任务（通过 Celery 异步执行）"""
    # 检查文献存在
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = result.scalar_one_or_none()
    if not literature:
        raise ValueError("文献不存在")

    if not literature.file_path:
        raise ValueError("文献无关联 PDF 文件，无法提取")

    # == 竞态防护：检查当前状态，防止重复触发提取 ==
    if literature.extraction_status == "processing":
        raise ValueError(f"文献正在提取中（当前状态: processing），请等待完成后再试")

    # 更新状态为 processing
    literature.extraction_status = "processing"
    literature.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # 提交到 Celery 队列异步执行（失败标记与重试由任务自身处理）
    lit_id_str = str(literature_id)
    process_literature.delay(
        literature_id=lit_id_str,
        model=model,
        api_key=api_key,
        base_url=base_url,
        clear_existing_data=clear_existing_data,
    )

    return {
        "literature_id": lit_id_str,
        "status": "processing",
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

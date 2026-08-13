import asyncio
import logging
import uuid
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.models.data_point import DataPoint
from app.models.extraction_history import ExtractionHistory
from app.tasks.extract_task import _process_literature_async
from app.models.base import async_session

logger = logging.getLogger("uvicorn")

# 持有后台提取任务的引用，防止被 GC 回收（Python asyncio 已知陷阱）
_background_tasks: set[asyncio.Task] = set()


async def trigger_extraction(
    db: AsyncSession,
    literature_id: uuid.UUID,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> dict:
    """触发文献 AI 提取任务（后台异步执行）"""
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

    # 后台异步执行提取（不阻塞响应）
    lit_id_str = str(literature_id)
    task = asyncio.create_task(_run_extraction_background(lit_id_str, model, api_key, base_url))
    # 持有引用防止 GC 回收
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {
        "literature_id": lit_id_str,
        "status": "processing",
    }


async def _run_extraction_background(
    literature_id: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
):
    """后台执行提取并处理失败"""
    try:
        result = await _process_literature_async(literature_id, model, api_key, base_url)
        logger.info(f"文献 {literature_id} 提取完成，数据点: {result['extracted_count']}")
    except Exception as e:
        logger.error(f"文献 {literature_id} 提取失败: {e}", exc_info=True)
        try:
            async with async_session() as fail_db:
                from app.models.literature import Literature as Lit
                r = await fail_db.execute(select(Lit).where(Lit.id == literature_id))
                lit = r.scalar_one_or_none()
                if lit:
                    lit.extraction_status = "failed"
                    lit.updated_at = datetime.now(timezone.utc)
                    # 写入失败历史记录
                    try:
                        history = ExtractionHistory(
                            literature_id=lit.id,
                            status="failed",
                            data_point_count=0,
                            error_message=str(e)[:2000],
                        )
                        fail_db.add(history)
                    except Exception as he:
                        logger.error(f"写入失败历史记录出错: {he}", exc_info=True)
                    await fail_db.commit()
        except Exception as mark_err:
            logger.error(f"标记失败状态时出错: {mark_err}", exc_info=True)


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

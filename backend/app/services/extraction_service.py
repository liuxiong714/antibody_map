import logging
import uuid
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.models.data_point import DataPoint
from app.tasks.extract_task import process_literature

logger = logging.getLogger("uvicorn")


async def trigger_extraction(
    db: AsyncSession,
    literature_id: uuid.UUID,
    model: Optional[str] = None,
) -> dict:
    """触发文献 AI 提取任务"""
    # 检查文献存在
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = result.scalar_one_or_none()
    if not literature:
        raise ValueError("文献不存在")

    if not literature.file_path:
        raise ValueError("文献无关联 PDF 文件，无法提取")

    # 更新状态为 processing
    literature.extraction_status = "processing"
    literature.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # 提交 Celery 任务
    task = process_literature.delay(str(literature_id), model=model)

    return {
        "task_id": task.id,
        "literature_id": str(literature_id),
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
            "confidence": dp.confidence,
            "review_status": dp.review_status,
            "created_at": dp.created_at.isoformat() if dp.created_at else None,
        }
        for dp in data_points
    ]

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.schemas.common import ApiResponse
from app.services.extraction_service import (
    trigger_extraction,
    get_extraction_status,
    get_extraction_results,
)

router = APIRouter()
logger = logging.getLogger("uvicorn")


# ── 请求体模型 ──────────────────────────────────────────

class DataPointReviewItem(BaseModel):
    id: str
    review_status: Optional[str] = None  # "approved" | "rejected" | None (仅编辑时不审核)
    review_note: Optional[str] = None
    # 以下为可编辑的数据字段
    disease: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    data_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    sample_size: Optional[int] = None
    population: Optional[str] = None
    age_min: Optional[float] = None
    age_max: Optional[float] = None
    collection_year: Optional[int] = None
    confidence: Optional[str] = None
    method: Optional[str] = None
    assay: Optional[str] = None


class UpdateDataPointsRequest(BaseModel):
    data_points: list[DataPointReviewItem]


class BatchReviewRequest(BaseModel):
    ids: list[str]
    note: Optional[str] = None


class ExtractionRequest(BaseModel):
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


# ── 提取相关路由 ────────────────────────────────────────

@router.post("/literatures/{literature_id}/extraction", response_model=ApiResponse)
async def start_extraction(
    literature_id: uuid.UUID,
    req: ExtractionRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """触发文献 AI 数据提取任务"""
    try:
        model = req.model if req else None
        api_key = req.api_key if req else None
        base_url = req.base_url if req else None
        result = await trigger_extraction(db, literature_id, model, api_key, base_url)
        return ApiResponse(message="提取任务已提交", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/literatures/{literature_id}/extraction/status", response_model=ApiResponse)
async def check_status(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """查询提取任务状态"""
    try:
        result = await get_extraction_status(db, literature_id)
        return ApiResponse(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/literatures/{literature_id}/extraction", response_model=ApiResponse)
async def get_results(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取提取的数据点列表"""
    try:
        data_points = await get_extraction_results(db, literature_id)
        status = await get_extraction_status(db, literature_id)
        return ApiResponse(
            data={
                "literature_id": str(literature_id),
                "status": status["status"],
                "data_points": data_points,
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 审核相关路由 ────────────────────────────────────────

@router.put("/literatures/{literature_id}/extraction", response_model=ApiResponse)
async def update_data_points(
    literature_id: uuid.UUID,
    req: UpdateDataPointsRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新数据点（可编辑任意字段 + 审核状态）"""
    updated = []
    editable_fields = [
        "disease", "province", "city", "data_type", "value", "unit",
        "sample_size", "population", "age_min", "age_max", "collection_year",
        "confidence", "method", "assay",
    ]

    for item in req.data_points:
        # 构建要更新的字段
        values: dict[str, Any] = {}

        # 审核状态
        if item.review_status:
            if item.review_status not in ("approved", "rejected"):
                raise HTTPException(status_code=400, detail=f"无效的审核状态: {item.review_status}")
            values["review_status"] = item.review_status

        # 可编辑的数据字段（仅更新显式传入的字段，None 值表示清空）
        explicit = item.model_dump(exclude_unset=True, exclude={"id", "review_status", "review_note"})
        for field in editable_fields:
            if field in explicit:
                values[field] = explicit[field]

        if not values:
            continue

        stmt = (
            update(DataPoint)
            .where(DataPoint.id == uuid.UUID(item.id))
            .where(DataPoint.literature_id == literature_id)
            .values(**values)
        )
        await db.execute(stmt)
        updated.append(item.id)

    await db.commit()
    return ApiResponse(message="数据点已更新", data={"updated": updated})


@router.post("/literatures/{literature_id}/extraction/confirm", response_model=ApiResponse)
async def batch_confirm(
    literature_id: uuid.UUID,
    req: BatchReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量审核通过"""
    uuids = [uuid.UUID(i) for i in req.ids]
    stmt = (
        update(DataPoint)
        .where(DataPoint.id.in_(uuids))
        .where(DataPoint.literature_id == literature_id)
        .values(review_status="approved")
    )
    result = await db.execute(stmt)

    await _sync_approved_count(db, literature_id)
    await db.commit()

    return ApiResponse(message=f"已批量通过 {result.rowcount} 个数据点")


@router.post("/literatures/{literature_id}/extraction/dispute", response_model=ApiResponse)
async def batch_dispute(
    literature_id: uuid.UUID,
    req: BatchReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量驳回"""
    uuids = [uuid.UUID(i) for i in req.ids]
    stmt = (
        update(DataPoint)
        .where(DataPoint.id.in_(uuids))
        .where(DataPoint.literature_id == literature_id)
        .values(review_status="rejected")
    )
    result = await db.execute(stmt)

    await _sync_approved_count(db, literature_id)
    await db.commit()

    return ApiResponse(message=f"已批量驳回 {result.rowcount} 个数据点", data={"note": req.note})


async def _sync_approved_count(db: AsyncSession, literature_id: uuid.UUID):
    """同步文献表中 approved_count"""
    count_result = await db.execute(
        select(func.count(DataPoint.id))
        .where(DataPoint.literature_id == literature_id)
        .where(DataPoint.review_status == "approved")
    )
    approved = count_result.scalar() or 0

    await db.execute(
        update(Literature)
        .where(Literature.id == literature_id)
        .values(approved_count=approved, updated_at=datetime.now(timezone.utc))
    )

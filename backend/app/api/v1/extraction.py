import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
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
    source_page: Optional[int] = None
    source_context: Optional[str] = None
    # P0 新增：精确字符级溯源
    source_char_start: Optional[int] = None
    source_char_end: Optional[int] = None
    is_grounded: Optional[bool] = None


class UpdateDataPointsRequest(BaseModel):
    data_points: list[DataPointReviewItem]


class BatchReviewRequest(BaseModel):
    ids: list[str]
    note: Optional[str] = None


class ExtractionRequest(BaseModel):
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class CreateDataPointRequest(BaseModel):
    """手动新增数据点"""
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
    confidence: Optional[str] = "medium"
    method: Optional[str] = None
    assay: Optional[str] = None
    source_page: Optional[int] = None
    source_context: Optional[str] = None
    # P0 新增：精确字符级溯源
    source_char_start: Optional[int] = None
    source_char_end: Optional[int] = None
    is_grounded: bool = False


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


@router.get("/literatures/{literature_id}/extraction/export")
async def export_data_points(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """导出文献的数据点为 CSV"""
    data_points = await get_extraction_results(db, literature_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "疾病", "省份", "城市", "数据类型", "数值", "单位", "样本量",
        "年龄下限", "年龄上限", "采集年份", "置信度", "审核状态", "来源页码",
        "原文依据", "溯源区间", "是否已匹配原文",
    ])
    for dp in data_points:
        interval = ""
        if dp.get("source_char_start") is not None and dp.get("source_char_end") is not None:
            interval = f"[{dp['source_char_start']}, {dp['source_char_end']})"
        writer.writerow([
            dp.get("disease", ""),
            dp.get("province", ""),
            dp.get("city", ""),
            dp.get("data_type", ""),
            dp.get("value"),
            dp.get("unit", ""),
            dp.get("sample_size"),
            dp.get("age_min"),
            dp.get("age_max"),
            dp.get("collection_year"),
            dp.get("confidence", ""),
            dp.get("review_status", ""),
            dp.get("source_page", ""),
            (dp.get("source_context") or "").replace("\n", " "),
            interval,
            "是" if dp.get("is_grounded") else "否",
        ])

    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''data_points_{literature_id}.csv"},
    )


@router.post("/literatures/{literature_id}/extraction/data-points", response_model=ApiResponse)
async def create_data_point(
    literature_id: uuid.UUID,
    req: CreateDataPointRequest,
    db: AsyncSession = Depends(get_db),
):
    """手动新增数据点"""
    # 验证文献存在
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = result.scalar_one_or_none()
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    # 创建数据点
    dp = DataPoint(
        literature_id=literature_id,
        disease=req.disease,
        province=req.province,
        city=req.city,
        data_type=req.data_type,
        value=req.value,
        unit=req.unit,
        sample_size=req.sample_size,
        population=req.population,
        age_min=req.age_min,
        age_max=req.age_max,
        collection_year=req.collection_year,
        confidence=req.confidence or "medium",
        method=req.method,
        assay=req.assay,
        source_page=req.source_page,
        source_context=req.source_context,
        # P0 新增：精确字符级溯源
        source_char_start=req.source_char_start,
        source_char_end=req.source_char_end,
        is_grounded=bool(req.is_grounded),
        review_status="pending",
    )
    db.add(dp)
    await db.flush()

    # 更新文献提取状态和计数
    if literature.extraction_status in (None, "", "failed", "pending"):
        literature.extraction_status = "done"
    literature.extracted_count = (literature.extracted_count or 0) + 1
    literature.updated_at = datetime.now(timezone.utc)

    await db.commit()

    return ApiResponse(
        message="数据点已添加",
        data={"id": str(dp.id)},
    )


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
        "confidence", "method", "assay", "source_page", "source_context",
        # P0 新增：精确字符级溯源
        "source_char_start", "source_char_end", "is_grounded",
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

    # 如果有审核状态变更，同步 literature.approved_count（修复审核状态显示不正确的问题）
    has_review_change = any(item.review_status for item in req.data_points)
    if has_review_change:
        await _sync_approved_count(db, literature_id)

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

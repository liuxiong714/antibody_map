import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

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
from app.core.traceability_html import (
    generate_traceability_html,
    datapoint_dict_to_trace,
)

from app.core.term_normalizer import CHINA_PROVINCE_NAMES

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


@router.get("/literatures/{literature_id}/extraction/traceability-html")
async def export_traceability_html(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """P1-2：导出自包含溯源 HTML（高亮原文 + 侧边栏数据点列表，可离线打开）"""
    # 1. 文献标题
    lit_result = await db.execute(
        select(Literature.title).where(Literature.id == literature_id)
    )
    title_row = lit_result.scalar_one_or_none()
    if not title_row:
        raise HTTPException(status_code=404, detail="文献不存在")
    title = title_row or str(literature_id)

    # 2. 数据点列表
    data_points = await get_extraction_results(db, literature_id)
    if not data_points:
        raise HTTPException(status_code=404, detail="该文献暂无提取数据点，无法生成溯源 HTML")

    # 3. 读取缓存的 clean_text（溯源文本）
    text_path = Path("data/pdfs") / f"{literature_id}.txt"
    if not text_path.exists():
        raise HTTPException(
            status_code=404,
            detail="溯源文本未缓存，请重新提取该文献后再导出 HTML",
        )
    try:
        full_text = text_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取溯源文本失败: {e}")

    # 4. 转换数据点为 TracePoint 并生成 HTML
    traces = [datapoint_dict_to_trace(dpo) for dpo in data_points]
    html_content = generate_traceability_html(
        title=title,
        full_text=full_text,
        data_points=traces,
    )

    # 5. 构建安全的下载文件名
    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip() or str(literature_id)
    filename = quote(f"{safe_title}_溯源报告.html")

    logger.info(
        f"[P1-2] 导出溯源 HTML: literature_id={literature_id}, "
        f"dp_count={len(traces)}, text_len={len(full_text)}"
    )

    return Response(
        content=html_content.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
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


@router.post("/literatures/{literature_id}/sync-metadata", response_model=ApiResponse)
async def sync_literature_metadata(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """从数据点聚合同步文献的 pub_year 和 province 元数据"""
    lit_result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = lit_result.scalar_one_or_none()
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    # 查询该文献的所有数据点
    dp_result = await db.execute(
        select(DataPoint).where(DataPoint.literature_id == literature_id)
    )
    all_data_points = dp_result.scalars().all()

    if not all_data_points:
        return ApiResponse(message="无需同步：该文献暂无数据点", data={
            "pub_year_updated": False,
            "province_updated": False,
            "data_point_count": 0,
        })

    pub_year_updated = False
    province_updated = False

    # 聚合 pub_year
    if not literature.pub_year:
        years = []
        for dp in all_data_points:
            y = dp.collection_year
            if y:
                years.append(y)
        if years:
            literature.pub_year = max(set(years), key=years.count)
            pub_year_updated = True
            logger.info(f"[MetadataSync] 文献 {literature_id} 聚合更新 pub_year={literature.pub_year}")

    # 聚合 province
    if not literature.province:
        provinces = [
            dp.province for dp in all_data_points
            if dp.province and dp.province in CHINA_PROVINCE_NAMES
        ]
        if provinces:
            literature.province = max(set(provinces), key=provinces.count)
            province_updated = True
            logger.info(
                f"[MetadataSync] 文献 {literature_id} 聚合更新 province={literature.province} "
                f"(覆盖{len(set(provinces))}省)"
            )

    if pub_year_updated or province_updated:
        literature.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(literature)

    return ApiResponse(
        message="元数据同步完成",
        data={
            "id": str(literature.id),
            "pub_year": literature.pub_year,
            "province": literature.province,
            "pub_year_updated": pub_year_updated,
            "province_updated": province_updated,
            "data_point_count": len(all_data_points),
        },
    )


@router.post("/literatures/sync-metadata-batch", response_model=ApiResponse)
async def sync_metadata_batch(db: AsyncSession = Depends(get_db)):
    """批量同步所有提取完成但缺少年份/省份的文献元数据"""
    # 查询所有 extraction_status='done' 且 pub_year 或 province 为空的文献
    result = await db.execute(
        select(Literature).where(
            Literature.extraction_status == "done",
            (Literature.pub_year.is_(None)) | (Literature.province.is_(None)),
        )
    )
    literatures = result.scalars().all()

    if not literatures:
        return ApiResponse(message="无需同步：没有缺少元数据的已完成文献", data={
            "total": 0, "synced": 0, "skipped": 0, "details": [],
        })

    # 查询这些文献的所有数据点
    lit_ids = [lit.id for lit in literatures]
    dp_result = await db.execute(
        select(DataPoint).where(DataPoint.literature_id.in_(lit_ids))
    )
    all_dps = dp_result.scalars().all()

    # 按 literature_id 分组
    dp_map: dict[uuid.UUID, list[DataPoint]] = {}
    for dp in all_dps:
        dp_map.setdefault(dp.literature_id, []).append(dp)

    synced_count = 0
    skipped_count = 0
    details = []

    for literature in literatures:
        dps = dp_map.get(literature.id, [])
        if not dps:
            skipped_count += 1
            continue

        pub_year_updated = False
        province_updated = False

        if not literature.pub_year:
            years = [dp.collection_year for dp in dps if dp.collection_year]
            if years:
                literature.pub_year = max(set(years), key=years.count)
                pub_year_updated = True

        if not literature.province:
            provinces = [
                dp.province for dp in dps
                if dp.province and dp.province in CHINA_PROVINCE_NAMES
            ]
            if provinces:
                literature.province = max(set(provinces), key=provinces.count)
                province_updated = True

        if pub_year_updated or province_updated:
            literature.updated_at = datetime.now(timezone.utc)
            synced_count += 1
            details.append({
                "id": str(literature.id),
                "title": literature.title,
                "pub_year": literature.pub_year,
                "province": literature.province,
                "pub_year_updated": pub_year_updated,
                "province_updated": province_updated,
            })
        else:
            skipped_count += 1

    if synced_count > 0:
        await db.commit()

    logger.info(
        f"[MetadataSync-Batch] 批量同步完成: 共{len(literatures)}篇, "
        f"同步{synced_count}篇, 跳过{skipped_count}篇"
    )

    return ApiResponse(
        message=f"批量同步完成：{synced_count}篇已更新，{skipped_count}篇无需更新",
        data={
            "total": len(literatures),
            "synced": synced_count,
            "skipped": skipped_count,
            "details": details,
        },
    )

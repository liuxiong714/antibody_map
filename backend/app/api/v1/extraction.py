import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import csv
import io
import re
from collections import Counter

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.literature_service import LOCAL_STORAGE_DIR
from app.services.extraction_service import (
    trigger_extraction,
    get_extraction_status,
    get_extraction_results,
    get_extraction_history,
    review_data_points,
    get_review_stats,
)
from app.core.traceability_html import (
    generate_traceability_html,
    datapoint_dict_to_trace,
)

from app.core.term_normalizer import CHINA_PROVINCE_NAMES
from app.tasks.quality_task import score_data_point_task

router = APIRouter()
logger = logging.getLogger("uvicorn")

# 文件扩展名列表，用于从标题中去除
_EXTENSIONS_PATTERN = re.compile(r"\.(pdf|caj|doc|docx|txt|epub|pptx|xlsx|ps|wps|md)$", re.IGNORECASE)
# 年份前缀，如 "2025 ", "2024_", "2025-", "2025." 等
_YEAR_PREFIX_PATTERN = re.compile(r"^(19\d{2}|20\d{2})\s*[ _\-\.,;:]\s*")


def clean_literature_title(title: str) -> str:
    """清洗文献标题：去除文件后缀和年份前缀"""
    if not title:
        return title
    t = title.strip()
    # 1. 去除文件扩展名
    # 只去除末尾的扩展名，确保不是真正的标题中的点
    t = _EXTENSIONS_PATTERN.sub("", t).strip()
    # 2. 去除年份前缀
    # 重复应用以处理 "2025 2024 Title" 这种多重前缀
    while True:
        new_t = _YEAR_PREFIX_PATTERN.sub("", t).strip()
        if new_t == t:
            break
        t = new_t
    # 3. 去除末尾多余的空格/标点
    t = t.strip(" ._-,;:")
    return t if t else title  # 如果清洗后为空则保留原标题


# ── 请求体模型 ──────────────────────────────────────────

class DataPointReviewItem(BaseModel):
    id: str
    review_status: Optional[str] = None  # "approved" | "rejected" | None (仅编辑时不审核)
    review_note: Optional[str] = None
    review_comment: Optional[str] = None  # 审核意见
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
    note: Optional[str] = None  # 兼容历史字段
    comment: Optional[str] = None  # 审核意见（驳回时必填）


class ExtractionRequest(BaseModel):
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    clear_existing_data: bool = True
    # 是否使用 Redis 提取结果缓存；False 时强制重新提取（跳过 LLM 缓存）
    use_cache: bool = True


class BatchExtractionRequest(BaseModel):
    """批量重新提取请求"""
    literature_ids: list[str]
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    clear_existing_data: bool = True
    # 是否使用 Redis 提取结果缓存；False 时强制重新提取
    use_cache: bool = True


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

@router.post("/literatures/{literature_id}/extraction", response_model=ApiResponse, summary="触发AI提取", description="触发单篇文献的AI数据提取任务，可指定模型、API Key和Base URL，支持清空已有数据后重新提取")
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
        clear_existing = req.clear_existing_data if req else True
        use_cache = req.use_cache if req else True
        result = await trigger_extraction(db, literature_id, model, api_key, base_url, clear_existing, use_cache)
        return ApiResponse(message="提取任务已提交", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/literatures/extraction/batch", response_model=ApiResponse, summary="批量触发AI提取", description="批量触发多篇文献的AI数据提取任务：有 PDF 走全文提取，无 PDF 但有摘要的题录文献用摘要提取；仅无 PDF 且无摘要、或正在提取中的文献会被跳过")
async def start_batch_extraction(
    req: BatchExtractionRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量触发文献 AI 数据提取任务"""
    if not req.literature_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个文献")

    submitted: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for lit_id_str in req.literature_ids:
        try:
            lit_id = uuid.UUID(lit_id_str)
            # 检查文献存在且状态非 processing
            result = await db.execute(
                select(Literature).where(Literature.id == lit_id)
            )
            literature = result.scalar_one_or_none()
            if not literature:
                errors.append({"id": lit_id_str, "reason": "文献不存在"})
                continue
            # 有 PDF 走全文提取，无 PDF 但有摘要时用摘要提取；两者皆无才跳过
            if not literature.file_path and not literature.abstract:
                skipped.append({"id": lit_id_str, "title": literature.title, "reason": "既无 PDF 也无摘要，无法提取"})
                continue
            if literature.extraction_status == "processing":
                skipped.append({"id": lit_id_str, "title": literature.title, "reason": "正在提取中，跳过"})
                continue

            # 触发提取
            await trigger_extraction(
                db, lit_id,
                model=req.model,
                api_key=req.api_key,
                base_url=req.base_url,
                clear_existing_data=req.clear_existing_data,
                use_cache=req.use_cache,
            )
            submitted.append({
                "id": str(lit_id),
                "title": literature.title,
            })
        except ValueError as e:
            errors.append({"id": lit_id_str, "reason": str(e)})
        except Exception as e:
            logger.error(f"[BatchExtract] 提交文献 {lit_id_str} 失败: {e}", exc_info=True)
            errors.append({"id": lit_id_str, "reason": str(e)})

    logger.info(
        f"[BatchExtract] 批量提取提交完成: 提交{len(submitted)}篇, "
        f"跳过{len(skipped)}篇, 失败{len(errors)}篇"
    )

    return ApiResponse(
        message=f"批量提取提交完成：成功 {len(submitted)} 篇，跳过 {len(skipped)} 篇，失败 {len(errors)} 篇",
        data={
            "submitted": submitted,
            "skipped": skipped,
            "errors": errors,
            "submitted_count": len(submitted),
            "skipped_count": len(skipped),
            "error_count": len(errors),
        },
    )


@router.get("/literatures/{literature_id}/extraction/status", response_model=ApiResponse, summary="查询提取状态", description="查询指定文献的AI数据提取任务当前状态（pending/processing/done/failed等）")
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


@router.get("/literatures/{literature_id}/extraction", response_model=ApiResponse, summary="获取提取结果", description="获取指定文献的AI提取数据点列表及提取状态")
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


@router.get("/literatures/{literature_id}/extraction/export", summary="导出数据点CSV", description="将指定文献的所有数据点导出为CSV文件，便于查看和分析")
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


@router.get("/literatures/{literature_id}/extraction/export-word", summary="导出数据点Word报告", description="将指定文献的数据点导出为Word报告（.docx格式），包含文献元信息、数据摘要、数据点明细表格")
async def export_data_points_word(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """导出文献的数据点为 Word 报告（.docx）"""
    # 1. 文献信息
    lit_result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = lit_result.scalar_one_or_none()
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    data_points = await get_extraction_results(db, literature_id)

    doc = Document()

    # ── 标题 ──
    title_text = literature.title or f"文献 {literature_id}"
    doc.add_heading(title_text, level=0)

    # ── 文献元信息 ──
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    meta_info = []
    if literature.authors:
        meta_info.append(f"作者：{literature.authors}")
    if literature.journal:
        meta_info.append(f"期刊：{literature.journal}")
    if literature.pub_year:
        meta_info.append(f"发表年份：{literature.pub_year}")
    if literature.extraction_status:
        status_map = {"processing": "进行中", "done": "已完成", "done_no_data": "完成（无数据）", "failed": "失败", "pending": "待处理"}
        meta_info.append(f"提取状态：{status_map.get(literature.extraction_status, literature.extraction_status)}")
    p.add_run(" | ".join(meta_info)).font.size = Pt(10)

    # ── 分隔线 ──
    doc.add_paragraph("─" * 50)

    # ── 统计摘要 ──
    doc.add_heading("数据摘要", level=1)
    total = len(data_points)
    if total > 0:
        by_type = Counter(dp.get("data_type", "") for dp in data_points)
        by_status = Counter(dp.get("review_status", "") for dp in data_points)
        provinces = set(dp.get("province", "") for dp in data_points if dp.get("province"))
        diseases = set(dp.get("disease", "") for dp in data_points if dp.get("disease"))

        summary = doc.add_table(rows=7, cols=2, style="Light List Accent 1")
        summary.cell(0, 0).text = "统计项"
        summary.cell(0, 1).text = "数值"
        summary.cell(1, 0).text = "数据点总数"
        summary.cell(1, 1).text = str(total)
        summary.cell(2, 0).text = "血清阳性率"
        summary.cell(2, 1).text = str(by_type.get("seroprevalence", 0))
        summary.cell(3, 0).text = "GMC"
        summary.cell(3, 1).text = str(by_type.get("gmc", 0))
        summary.cell(4, 0).text = "覆盖省份"
        summary.cell(4, 1).text = f"{len(provinces)} 个（{', '.join(sorted(provinces))}）"
        summary.cell(5, 0).text = "涉及疾病"
        summary.cell(5, 1).text = f"{len(diseases)} 种（{', '.join(sorted(diseases))}）"
        summary.cell(6, 0).text = "审核状态"
        summary.cell(6, 1).text = f"已通过 {by_status.get('approved', 0)} | 待审核 {by_status.get('pending', 0)} | 已驳回 {by_status.get('rejected', 0)}"
    else:
        doc.add_paragraph("暂无数据点")

    # ── 数据点明细 ──
    doc.add_heading("数据点明细", level=1)
    if data_points:
        table = doc.add_table(rows=1 + len(data_points), cols=9, style="Light Grid Accent 1")
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        # 表头
        headers = ["疾病", "省份", "数据类型", "数值", "样本量", "年龄段", "采集年份", "置信度", "审核状态"]
        for i, h in enumerate(headers):
            cell = table.cell(0, i)
            cell.text = h
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in paragraph.runs:
                    run.bold = True
                    run.font.size = Pt(9)

        # 数据行
        for idx, dp in enumerate(data_points):
            row = table.rows[idx + 1]
            age_range = ""
            if dp.get("age_min") is not None or dp.get("age_max") is not None:
                age_min = dp.get("age_min") or ""
                age_max = dp.get("age_max") or ""
                age_range = f"{age_min}-{age_max}" if age_min and age_max else f"{age_min or ''}~{age_max or ''}"
            values = [
                dp.get("disease", ""),
                dp.get("province", ""),
                "阳性率" if dp.get("data_type") == "seroprevalence" else "GMC" if dp.get("data_type") == "gmc" else dp.get("data_type", ""),
                f"{dp.get('value', '')}{dp.get('unit', '')}",
                str(dp.get("sample_size", "") or ""),
                age_range,
                str(dp.get("collection_year", "") or ""),
                dp.get("confidence", ""),
                {"approved": "通过", "rejected": "驳回", "pending": "待审"}.get(dp.get("review_status", ""), dp.get("review_status", "")),
            ]
            for col, val in enumerate(values):
                cell = table.cell(idx + 1, col)
                cell.text = val
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(8.5)
    else:
        doc.add_paragraph("暂无数据点")

    # ── 生成时间 ──
    doc.add_paragraph("─" * 50)
    ts = doc.add_paragraph()
    ts_run = ts.add_run(f"报告生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    ts_run.font.size = Pt(9)
    ts_run.font.color.rgb = RGBColor(128, 128, 128)

    # ── 输出 ──
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    safe_title = "".join(c for c in title_text if c not in r'\/:*?"<>|').strip() or str(literature_id)
    filename = quote(f"{safe_title}_数据报告.docx")

    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/literatures/{literature_id}/extraction/traceability-html", summary="导出溯源HTML报告", description="导出自包含溯源HTML文件，高亮原文并附带侧边栏数据点列表，可离线打开查看")
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
    text_path = LOCAL_STORAGE_DIR / f"{literature_id}.txt"
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


@router.post("/literatures/{literature_id}/extraction/data-points", response_model=ApiResponse, summary="手动添加数据点", description="为指定文献手动添加一个数据点，可设置所有数据字段和溯源信息")
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

@router.put("/literatures/{literature_id}/extraction", response_model=ApiResponse, summary="更新数据点", description="批量更新数据点，可编辑任意字段和审核状态，支持编辑数据字段和审核状态")
async def update_data_points(
    literature_id: uuid.UUID,
    req: UpdateDataPointsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    now = datetime.now(timezone.utc)

    for item in req.data_points:
        # 构建要更新的字段
        values: dict[str, Any] = {}

        # 审核状态（写入审核人/审核时间）
        if item.review_status:
            if item.review_status not in ("approved", "rejected"):
                raise HTTPException(status_code=400, detail=f"无效的审核状态: {item.review_status}")
            values["review_status"] = item.review_status
            values["reviewer_id"] = current_user.id
            values["reviewed_at"] = now

        # 审核意见（仅当显式传入时更新，支持清空）
        if "review_comment" in item.model_dump(exclude_unset=True):
            values["review_comment"] = item.review_comment

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

    # 审核通过后异步质量打分（幂等，全文可用后精打覆盖）
    approved_ids = [
        item.id for item in req.data_points if item.review_status == "approved"
    ]
    for dp_id in approved_ids:
        score_data_point_task.delay(dp_id)

    return ApiResponse(message="数据点已更新", data={"updated": updated})


@router.post("/literatures/{literature_id}/extraction/confirm", response_model=ApiResponse, summary="批量审核通过", description="批量将多个数据点审核通过，写入审核人/审核时间，同步更新文献的已通过计数")
async def batch_confirm(
    literature_id: uuid.UUID,
    req: BatchReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量审核通过"""
    comment = req.comment if req.comment is not None else req.note
    result = await review_data_points(
        db, literature_id, req.ids, "approved", comment, current_user.id
    )

    await _sync_approved_count(db, literature_id)
    await db.commit()

    # 审核通过后异步质量打分（幂等，全文可用后精打覆盖）
    for dp_id in req.ids:
        score_data_point_task.delay(dp_id)

    return ApiResponse(message=f"已批量通过 {result} 个数据点")


@router.post("/literatures/{literature_id}/extraction/dispute", response_model=ApiResponse, summary="批量驳回", description="批量驳回多个数据点，驳回必须填写意见，写入审核人/审核时间，同步更新文献的已通过计数")
async def batch_dispute(
    literature_id: uuid.UUID,
    req: BatchReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量驳回"""
    comment = req.comment if req.comment is not None else req.note
    if not comment or not str(comment).strip():
        raise HTTPException(status_code=400, detail="驳回必须填写审核意见")

    result = await review_data_points(
        db, literature_id, req.ids, "rejected", comment, current_user.id
    )

    await _sync_approved_count(db, literature_id)
    await db.commit()

    return ApiResponse(message=f"已批量驳回 {result} 个数据点", data={"note": comment})


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


@router.post("/literatures/{literature_id}/sync-metadata", response_model=ApiResponse, summary="同步文献元数据", description="从数据点聚合同步文献的pub_year和province元数据，并清洗标题（去除文件后缀和年份前缀）")
async def sync_literature_metadata(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """从数据点聚合同步文献的 pub_year 和 province 元数据，并清洗标题"""
    lit_result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = lit_result.scalar_one_or_none()
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    # 清洗标题
    title_updated = False
    original_title = literature.title
    cleaned_title = clean_literature_title(original_title)
    if cleaned_title != original_title:
        literature.title = cleaned_title
        title_updated = True
        logger.info(f"[MetadataSync] 文献 {literature_id} 清洗标题: '{original_title}' -> '{cleaned_title}'")

    # 查询该文献的所有数据点
    dp_result = await db.execute(
        select(DataPoint).where(DataPoint.literature_id == literature_id)
    )
    all_data_points = dp_result.scalars().all()

    if not all_data_points:
        if title_updated:
            literature.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(literature)
        return ApiResponse(message="元数据同步完成（标题已清洗）" if title_updated else "无需同步：该文献暂无数据点", data={
            "title_updated": title_updated,
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

    if pub_year_updated or province_updated or title_updated:
        literature.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(literature)

    return ApiResponse(
        message="元数据同步完成",
        data={
            "id": str(literature.id),
            "title": literature.title,
            "title_updated": title_updated,
            "pub_year": literature.pub_year,
            "province": literature.province,
            "pub_year_updated": pub_year_updated,
            "province_updated": province_updated,
            "data_point_count": len(all_data_points),
        },
    )


@router.post("/literatures/sync-metadata-batch", response_model=ApiResponse, summary="批量同步文献元数据", description="批量同步所有提取完成的文献元数据，包括清洗标题和从数据点聚合pub_year和province")
async def sync_metadata_batch(db: AsyncSession = Depends(get_db)):
    """批量同步所有提取完成的文献元数据，包括：
    - 清洗标题：去除文件后缀（.pdf/.caj等）和年份前缀（2025、2024等）
    - 从数据点聚合 pub_year 和 province
    """
    # 查询所有 extraction_status='done' 的文献
    result = await db.execute(
        select(Literature).where(Literature.extraction_status == "done")
    )
    literatures = result.scalars().all()

    if not literatures:
        return ApiResponse(message="无需同步：没有已提取完成的文献", data={
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
        title_updated = False

        # 清洗标题：去除文件后缀和年份前缀
        original_title = literature.title
        cleaned_title = clean_literature_title(original_title)
        if cleaned_title != original_title:
            literature.title = cleaned_title
            title_updated = True
            logger.info(
                f"[MetadataSync-Batch] 文献 {literature.id} 清洗标题: "
                f"'{original_title}' -> '{cleaned_title}'"
            )

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

        if pub_year_updated or province_updated or title_updated:
            literature.updated_at = datetime.now(timezone.utc)
            synced_count += 1
            details.append({
                "id": str(literature.id),
                "title": literature.title,
                "title_updated": title_updated,
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


# ── 提取状态修复与手动停止 ──────────────────────────────────

@router.post("/literatures/{literature_id}/extraction/stop", response_model=ApiResponse, summary="停止提取", description="手动停止/重置文献提取状态，将extraction_status=processing的文献强制重置为failed，用于处理因服务器重启等导致的永久提取中状态")
async def stop_extraction(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """手动停止/重置文献提取状态。

    将 extraction_status='processing' 的文献强制重置为 'failed'，
    用于处理服务器重启或任务异常退出导致的永久「提取中」状态。
    """
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = result.scalar_one_or_none()
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    if literature.extraction_status != "processing":
        return ApiResponse(
            message=f"当前状态为 {literature.extraction_status}，无需停止",
            data={"literature_id": str(literature_id), "status": literature.extraction_status},
        )

    literature.extraction_status = "failed"
    literature.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.warning(f"文献 {literature_id} 提取已被手动停止，状态重置为 failed")
    return ApiResponse(
        message="提取已停止，状态重置为失败",
        data={"literature_id": str(literature_id), "status": "failed"},
    )


@router.get("/literatures/{literature_id}/extraction/history", response_model=ApiResponse, summary="获取提取历史", description="获取指定文献的历次AI提取历史记录")
async def get_history(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取文献的历次 AI 提取历史"""
    try:
        history = await get_extraction_history(db, literature_id)
        return ApiResponse(data=history)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/literatures/extraction/reset-stuck", response_model=ApiResponse, summary="批量重置卡住的提取", description="批量重置所有卡在processing状态的文献为failed，用于服务器重启后恢复状态")
async def reset_stuck_extractions(db: AsyncSession = Depends(get_db)):
    """批量重置所有卡在 'processing' 状态的文献为 'failed'。

    典型场景：服务器重启后，之前的异步提取任务已丢失但状态未更新。
    """
    result = await db.execute(
        select(Literature).where(Literature.extraction_status == "processing")
    )
    stuck_list = result.scalars().all()

    if not stuck_list:
        return ApiResponse(message="没有卡住的提取任务", data={"reset_count": 0})

    reset_ids = []
    for lit in stuck_list:
        lit.extraction_status = "failed"
        lit.updated_at = datetime.now(timezone.utc)
        reset_ids.append(str(lit.id))

    await db.commit()

    logger.warning(
        f"[ResetStuck] 批量重置 {len(stuck_list)} 篇卡住的提取状态为 failed: {reset_ids}"
    )
    return ApiResponse(
        message=f"已重置 {len(stuck_list)} 篇卡住的提取状态为失败",
        data={"reset_count": len(stuck_list), "literature_ids": reset_ids},
    )

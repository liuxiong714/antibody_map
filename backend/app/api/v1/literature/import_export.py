"""导入/导出 端点 —— 导出、导入JSON、题录导入、批量文件夹/浏览器上传。"""


from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.literature._common import create_import_log
from app.services.literature.import_export import (
    batch_import_files_from_folder,
    batch_import_uploaded_files,
    build_literatures_export,
    import_literatures_from_json,
    import_references_from_text,
    preview_import_references,
)

router = APIRouter()


@router.get("/literatures/export", summary="导出文献列表", description="导出文献列表，支持CSV/Excel/JSON格式，可选包含数据点，支持按条件筛选或指定文献ID列表导出")
async def export_literatures(
    keyword: str | None = Query(None, description="标题/作者/期刊关键词搜索"),
    disease: str | None = Query(None, description="疾病筛选"),
    province: str | None = Query(None, description="省份筛选"),
    year_start: int | None = Query(None, description="起始年份"),
    year_end: int | None = Query(None, description="结束年份"),
    journal: str | None = Query(None, description="期刊名称"),
    review_status: str | None = Query(None, description="审核状态: none, pending, partial, approved"),
    file_format: str | None = Query(None, description="文档格式筛选: PDF, CAJ, EPUB, DOCX, PPTX, XLSX, TXT, HTML, URL"),
    format: str = Query("csv", description="导出格式: csv, xlsx, json"),
    include_data_points: bool = Query(False, description="是否包含数据点（JSON/Excel有效）"),
    literature_ids: str | None = Query(None, description="逗号分隔的文献ID列表，指定时仅导出这些文献"),
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = await build_literatures_export(
            db=db, format=format, include_data_points=include_data_points,
            keyword=keyword, disease=disease, province=province,
            year_start=year_start, year_end=year_end, journal=journal,
            review_status=review_status, file_format=file_format,
            literature_ids=literature_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Response(
        content=payload["content"],
        media_type=payload["media_type"],
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{payload['filename']}"},
    )


@router.post("/literatures/import", response_model=ApiResponse, summary="导入文献数据", description="从JSON导出文件导入文献及数据点，自动检测重复文献，支持跳过重复或创建新记录，保留原有的审核状态")
async def import_literatures(
    file: UploadFile = File(..., description="导入文件（JSON 格式）"),
    skip_duplicates: bool = Form(True, description="跳过重复文献"),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="请上传 JSON 格式的导入文件")
    try:
        content = await file.read()
        result = await import_literatures_from_json(db, content, skip_duplicates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(
        message=f"导入完成：成功 {result['imported_count']} 篇文献，{result['data_point_count']} 个数据点，跳过 {result['skipped_count']} 篇重复",
        data={
            "imported_count": result["imported_count"],
            "skipped_count": result["skipped_count"],
            "data_point_count": result["data_point_count"],
            "error_count": result["error_count"],
            "errors": result["errors"],
            "imported_titles": result["imported_titles"],
        },
    )


class ImportReferencesBody(BaseModel):
    """题录导入的请求体（前端读取文件后传全文文本）。"""
    ref_text: str
    fmt: str = "auto"
    file_name: str = ""
    start: int = 0
    limit: int = 0
    indices: list[int] | None = None
    skip_log: bool = False


@router.post("/literatures/import-references/preview", response_model=ApiResponse, summary="预览题录导入", description="解析题录文本并统计总条数、重复条数、可导入条数，不写入数据库")
async def import_references_preview(
    body: ImportReferencesBody,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await preview_import_references(db, body.ref_text, body.fmt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(
        message=f"解析完成：共 {result['total']} 条，重复/跳过 {result['skipped']} 条，可导入 {result['imported']} 条",
        data=result,
    )


@router.post("/literatures/import-references", response_model=ApiResponse, summary="导入题录文件", description="解析 RIS / EndNote(.enw) / PubMed 文本 / WoS 纯文本 / WoS CSV / 读秀超星 题录并批量导入文献库，自动跳过标题为空与已存在的重复记录")
async def import_references(
    body: ImportReferencesBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        result = await import_references_from_text(db, body.ref_text, body.fmt, body.start, body.limit, indices=body.indices)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if current_user and not body.skip_log:
        await create_import_log(
            db,
            file_name=body.file_name or "unknown",
            total_count=result["total"],
            skipped_count=result["skipped"],
            imported_count=result["imported"],
            operator_name=current_user.username,
            operator_id=str(current_user.id) if current_user.id else None,
            fmt=body.fmt,
        )
    return ApiResponse(
        message=f"导入完成：成功 {result['imported']} 篇，跳过 {result['skipped']} 篇（重复或标题为空）",
        data={
            "imported": result["imported"],
            "skipped": result["skipped"],
            "total": result["total"],
            "errors": result["errors"],
        },
    )


class ImportReferencesLogBody(BaseModel):
    """题录导入日志的请求体（前端分批导入完成后汇总调用）。"""
    file_name: str = ""
    total_count: int
    skipped_count: int
    imported_count: int
    fmt: str = "auto"


@router.post("/literatures/import-references/log", response_model=ApiResponse, summary="题录导入日志", description="前端分批导入完成后，汇总调用一次记录导入日志")
async def import_references_log(
    body: ImportReferencesLogBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await create_import_log(
        db,
        file_name=body.file_name or "unknown",
        total_count=body.total_count,
        skipped_count=body.skipped_count,
        imported_count=body.imported_count,
        operator_name=current_user.username,
        operator_id=str(current_user.id) if current_user.id else None,
        fmt=body.fmt,
    )
    return ApiResponse(message="导入日志已记录")


@router.post("/literatures/batch-import-from-folder", response_model=ApiResponse, summary="从文件夹批量导入", description="从服务器本地文件夹批量导入文件，自动匹配已有文献或新建文献记录，支持导入后自动触发AI提取")
async def batch_import_from_folder(
    folder_path: str = Form(..., description="服务器上的文件夹路径，包含要导入的 PDF 等文件"),
    trigger_extraction_after: bool = Form(True, description="新导入的文献是否自动触发 AI 提取"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await batch_import_files_from_folder(db, folder_path, trigger_extraction_after, owner_id=current_user.id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    parts = []
    if result["matched"]:
        parts.append(f"关联 {result['matched']} 篇")
    if result["imported"]:
        parts.append(f"新建 {result['imported']} 篇")
    if result["skipped"]:
        parts.append(f"跳过 {result['skipped']} 篇（已有文件）")
    if result["failed"]:
        parts.append(f"失败 {result['failed']} 个")
    message = "批量导入完成：" + "，".join(parts)
    if result["extraction_triggered"]:
        message += f"，已触发 {result['extraction_triggered']} 篇 AI 提取"
    return ApiResponse(message=message, data=result)


@router.post("/literatures/batch-upload-files", response_model=ApiResponse, summary="批量上传文件", description="从浏览器上传多个文件批量导入，自动匹配已有文献或新建文献记录，与文件夹导入逻辑相同但文件从浏览器上传")
async def batch_upload_files(
    files: list[UploadFile] = File(..., description="从浏览器上传的文件列表"),
    trigger_extraction_after: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await batch_import_uploaded_files(db, files, trigger_extraction_after, owner_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    parts = []
    if result["matched"]:
        parts.append(f"关联 {result['matched']} 篇")
    if result["imported"]:
        parts.append(f"新建 {result['imported']} 篇")
    if result["skipped"]:
        parts.append(f"跳过 {result['skipped']} 篇（已有文件）")
    if result["failed"]:
        parts.append(f"失败 {result['failed']} 个")
    message = "批量导入完成：" + "，".join(parts)
    if result["extraction_triggered"]:
        message += f"，已触发 {result['extraction_triggered']} 篇 AI 提取"
    return ApiResponse(message=message, data=result)
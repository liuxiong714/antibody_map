import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger("uvicorn")

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.config import settings
from app.models.user import User
from app.schemas.common import ApiResponse, PagedResponse
from app.schemas.literature import (
    LiteratureResponse, LiteratureUpdate,
    CheckDuplicateRequest, MergePreviewRequest, MergeRequest,
)
from app.core.document_parser import ALLOWED_EXTS, get_mime_type
from app.core.url_fetcher import fetch_url, guess_title_from_html
from app.services.literature_service import (
    list_literature,
    get_literature,
    update_literature,
    delete_literature,
    upload_literature,
    upload_literature_file,
    check_duplicates,
    scan_duplicates,
    preview_merge,
    merge_literatures,
    batch_delete_literatures,
    import_references_from_text,
    preview_import_references,
    cleanup_empty_literatures,
    batch_import_files_from_folder,
    batch_import_uploaded_files,
    import_literatures_from_json,
    build_literatures_export,
    reveal_in_host_file_manager,
    LOCAL_STORAGE_DIR,
    list_trash_literatures,
    restore_literature,
    permanently_delete_literature,
    empty_trash,
    permanently_delete_all_trash,
)
from app.services.file_cleanup_service import cleanup_orphan_files, scan_orphan_files

router = APIRouter()


def _resolve_literature_file(literature) -> Optional[Path]:
    """解析文献文件在磁盘上的真实路径。

    数据库中存储的 file_path 可能是 Windows 绝对路径（E:\\...），
    当后端运行在 Docker 容器（Linux）中时无法直接访问该路径。
    此处依次尝试：原始路径 → 与 backend/data/pdfs 目录相对的本地路径。
    """
    raw = (literature.file_path or "").strip()
    if not raw:
        return None

    candidates: list[Path] = []
    # 候选1：原始路径（Windows 主机运行时直接命中）
    candidates.append(Path(raw))
    # 候选2：与 LOCAL_STORAGE_DIR 相对的路径（容器/路径迁移时命中）
    # 去除可能的 Windows 盘符前缀与目录前缀，仅保留相对部分
    rel = raw.replace("\\", "/")
    rel = re.sub(r"^[A-Za-z]:", "", rel)
    # 取 data/pdfs 之后的相对路径，兼容绝对/相对两种写法
    if "/data/pdfs/" in rel:
        rel = rel.split("/data/pdfs/", 1)[1]
    elif rel.startswith("/backend/data/pdfs/"):
        rel = rel.split("/backend/data/pdfs/", 1)[1]
    elif rel.startswith("/app/backend/data/pdfs/"):
        rel = rel.split("/app/backend/data/pdfs/", 1)[1]
    else:
        rel = rel.lstrip("/")
    if rel:
        candidates.append(LOCAL_STORAGE_DIR / rel)

    for p in candidates:
        try:
            if p.exists() and p.is_file():
                return p
        except OSError:
            continue
    return None


def _build_safe_filename(title: Optional[str], ext: str, literature_id: uuid.UUID) -> str:
    """构建下载文件名：去除标题已含的已知后缀，清理非法字符，附加真实扩展名。"""
    raw = title or str(literature_id)
    raw_lower = raw.lower()
    for known in ALLOWED_EXTS:
        if raw_lower.endswith(known):
            raw = raw[: -len(known)]
            break
    safe = "".join(c for c in raw if c not in r'\/:*?"<>|').strip() or str(literature_id)
    return quote(f"{safe}{ext}")


@router.post("/literatures/upload", response_model=ApiResponse, summary="上传文献文件", description="上传单个文献文件（PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML），并自动创建文献记录，支持指定标题、DOI和省份信息")
async def upload(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    doi: Optional[str] = Form(None),
    province: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    # 按扩展名白名单校验（支持 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML）
    ext = Path(file.filename or "").suffix.lower() if file.filename else ""
    logger.info(
        f"[上传] 收到文件: filename={file.filename}, ext={ext or '(未知)'}, "
        f"title={title or '(无)'}, doi={doi or '(无)'}, province={province or '(无)'}"
    )
    if ext not in ALLOWED_EXTS:
        logger.warning(f"[上传] 格式被拒绝: filename={file.filename}, ext={ext}")
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext or '未知'}，支持 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML",
        )

    file_bytes = await file.read()
    file_size = len(file_bytes)
    logger.info(f"[上传] 读取完成: filename={file.filename}, size={file_size} bytes")
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
        logger.warning(f"[上传] 文件超限: filename={file.filename}, size={file_size}, limit={settings.MAX_UPLOAD_SIZE}")
        raise HTTPException(status_code=400, detail="文件大小超过限制")

    try:
        literature, _action = await upload_literature(db, file_bytes, file.filename, title, doi, province)
    except Exception as e:
        logger.error(f"[上传] upload_literature 抛出异常: filename={file.filename}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)[:200]}")

    if literature is None:
        logger.error(f"[上传] upload_literature 返回 None: filename={file.filename}")
        raise HTTPException(status_code=500, detail="文件上传失败")

    logger.info(f"[上传] 成功: id={literature.id}, title={literature.title}, path={literature.file_path}")
    return ApiResponse(
        message="上传成功",
        data=LiteratureResponse.model_validate(literature).model_dump(),
    )


@router.post("/literatures/from-url", response_model=ApiResponse, summary="从URL导入文献", description="从指定URL抓取HTML内容并创建文献记录，自动提取页面标题，保存为HTML文件，后续可通过AI提取功能从HTML文本中提取数据点")
async def create_from_url(
    url: str = Form(..., description="要抓取的网页 URL"),
    title: Optional[str] = Form(None, description="文献标题（留空则从 HTML <title> 自动提取）"),
    province: Optional[str] = Form(None, description="关联省份"),
    db: AsyncSession = Depends(get_db),
):
    """从 URL 抓取 HTML 内容并创建文献记录。

    自动提取页面标题（如未提供），保存为 .html 文件，
    后续可通过 AI 提取功能从 HTML 文本中提取数据点。
    """
    logger.info(f"[URL 导入] 收到请求: url={url}, title={title or '(自动提取)'}, province={province or '(无)'}")

    if not url.startswith(("http://", "https://")):
        logger.warning(f"[URL 导入] URL 格式无效: {url}")
        raise HTTPException(status_code=400, detail="URL 必须以 http:// 或 https:// 开头")

    try:
        content = await fetch_url(url)
        logger.info(f"[URL 导入] 抓取成功: {len(content)} 字节")
    except Exception as e:
        logger.error(f"[URL 导入] 抓取失败: {url} - {e}")
        raise HTTPException(status_code=400, detail=f"URL 抓取失败: {str(e)[:200]}")

    # 自动提取标题
    lit_title = title
    if not lit_title:
        lit_title = guess_title_from_html(content) or url
        logger.info(f"[URL 导入] 自动提取标题: {lit_title[:80]}{'...' if len(lit_title) > 80 else ''}")

    # 从 URL 中提取域名作为文件名
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc or "webpage"
    filename = f"{domain}.html"
    logger.info(f"[URL 导入] 准备保存: filename={filename}, title={lit_title[:80]}{'...' if len(lit_title) > 80 else ''}")

    literature, _action = await upload_literature(db, content, filename, lit_title, province=province)
    if literature is None:
        logger.error(f"[URL 导入] 创建文献记录失败: {url}")
        raise HTTPException(status_code=500, detail="创建文献失败")

    logger.info(f"[URL 导入] 成功创建文献: id={literature.id}, title={literature.title}")
    return ApiResponse(
        message="URL 导入成功",
        data=LiteratureResponse.model_validate(literature).model_dump(),
    )


@router.get("/literatures", response_model=PagedResponse, summary="获取文献列表", description="分页获取文献列表，支持关键词、疾病、省份、年份、期刊、审核状态、提取状态、标签等多维度筛选和排序")
async def list_literatures(
    keyword: Optional[str] = Query(None, description="标题/作者/期刊关键词搜索"),
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    journal: Optional[str] = Query(None, description="期刊名称"),
    title: Optional[str] = Query(None, description="标题筛选（模糊匹配）"),
    authors: Optional[str] = Query(None, description="作者筛选（模糊匹配）"),
    created_start: Optional[datetime] = Query(None, description="创建时间起（含当日）"),
    created_end: Optional[datetime] = Query(None, description="创建时间止（含当日）"),
    sort_by: Optional[str] = Query(None, description="排序字段: title, authors, journal, year, province, created, status, file_format"),
    sort_order: Optional[str] = Query(None, description="排序方向: asc, desc"),
    review_status: Optional[str] = Query(None, description="审核状态: none, pending, partial, approved"),
    extraction_status: Optional[str] = Query(None, description="提取状态: pending, processing, done, done_no_data, failed"),
    file_format: Optional[str] = Query(None, description="文档格式筛选: PDF, CAJ, EPUB, DOCX, PPTX, XLSX, TXT, HTML, URL"),
    tag_id: Optional[uuid.UUID] = Query(None, description="标签筛选：只显示有该标签的文献"),
    has_abstract: Optional[bool] = Query(None, description="摘要筛选：true=有摘要，false=无摘要"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_literature(
        db=db, keyword=keyword, disease=disease, province=province,
        year_start=year_start, year_end=year_end, journal=journal,
        title=title, authors=authors, created_start=created_start, created_end=created_end,
        sort_by=sort_by, sort_order=sort_order, review_status=review_status,
        extraction_status=extraction_status, file_format=file_format, tag_id=tag_id,
        has_abstract=has_abstract, page=page, page_size=page_size,
    )

    def _derive_file_format(lit) -> Optional[str]:
        """根据 file_path / title / source_db 推导文献文件格式，大写后缀，None 表示无本地文件。"""
        path = getattr(lit, "file_path", None) or ""
        if path:
            low = path.lower()
            # query string 带 ?att=xxx 情况（from-URL 存的是网页 URL）
            if low.startswith("http://") or low.startswith("https://"):
                if ".pdf" in low:
                    return "PDF"
                if ".caj" in low:
                    return "CAJ"
                if ".epub" in low:
                    return "EPUB"
                if ".docx" in low:
                    return "DOCX"
                if ".pptx" in low:
                    return "PPTX"
                if ".xlsx" in low:
                    return "XLSX"
                # URL 不带后缀，默认是 HTML (网页) 来源
                if low.endswith(".html") or low.endswith(".htm"):
                    return "HTML"
                return "URL"
            # 本地文件路径：按扩展名
            ext = low.rsplit(".", 1)[-1] if "." in low else ""
            ext = ext.split("?", 1)[0]
            if ext in {"pdf", "caj", "epub", "docx", "pptx", "xlsx", "txt", "html", "htm"}:
                return ext.upper() if ext != "htm" else "HTML"
        # 没有本地文件：根据 source_db 判断是否是纯元数据（PubMed/CNKI等）
        if getattr(lit, "source_db", None):
            return None
        return None

    serialized = []
    for item in items:
        data = LiteratureResponse.model_validate(item).model_dump()
        data["file_format"] = _derive_file_format(item)
        # 添加标签信息
        try:
            data["tags"] = [{"id": str(t.id), "name": t.name, "color": t.color} for t in (item.tags or [])]
        except Exception:
            data["tags"] = []
        serialized.append(data)

    return PagedResponse(
        items=serialized,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/literatures/export", summary="导出文献列表", description="导出文献列表，支持CSV/Excel/JSON格式，可选包含数据点，支持按条件筛选或指定文献ID列表导出")
async def export_literatures(
    keyword: Optional[str] = Query(None, description="标题/作者/期刊关键词搜索"),
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    journal: Optional[str] = Query(None, description="期刊名称"),
    review_status: Optional[str] = Query(None, description="审核状态: none, pending, partial, approved"),
    file_format: Optional[str] = Query(None, description="文档格式筛选: PDF, CAJ, EPUB, DOCX, PPTX, XLSX, TXT, HTML, URL"),
    format: str = Query("csv", description="导出格式: csv, xlsx, json"),
    include_data_points: bool = Query(False, description="是否包含数据点（JSON/Excel有效）"),
    literature_ids: Optional[str] = Query(None, description="逗号分隔的文献ID列表，指定时仅导出这些文献"),
    db: AsyncSession = Depends(get_db),
):
    """导出文献列表，支持 CSV / Excel / JSON 格式，可选包含数据点

    当 literature_ids 参数提供时，仅导出指定的文献及其数据点（忽略筛选条件）。
    """
    try:
        payload = await build_literatures_export(
            db=db, format=format, include_data_points=include_data_points,
            keyword=keyword, disease=disease, province=province,
            year_start=year_start, year_end=year_end, journal=journal,
            review_status=review_status, file_format=file_format,
            literature_ids=literature_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    """导入文献及数据点（从 JSON 导出文件）

    支持从 export?format=json&include_data_points=true 导出的 JSON 文件导入。
    会自动检测重复文献（按 DOI/标题匹配），可选择跳过或创建。
    导入的文献和数据点会保留原有的审核状态，确保在地图、分析等模块正常展示。
    """
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="请上传 JSON 格式的导入文件")

    try:
        content = await file.read()
        result = await import_literatures_from_json(db, content, skip_duplicates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    fmt: str = "auto"  # 格式：auto / ris / enw / pubmed / wos / woscsv / duxiu，auto 时自动探测


@router.post("/literatures/import-references/preview", response_model=ApiResponse, summary="预览题录导入", description="解析题录文本并统计总条数、重复条数、可导入条数，不写入数据库")
async def import_references_preview(
    body: ImportReferencesBody,
    db: AsyncSession = Depends(get_db),
):
    """预览题录导入：解析文本并统计，不写入数据库。"""
    try:
        result = await preview_import_references(db, body.ref_text, body.fmt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(
        message=f"解析完成：共 {result['total']} 条，重复/跳过 {result['skipped']} 条，可导入 {result['imported']} 条",
        data=result,
    )


@router.post("/literatures/import-references", response_model=ApiResponse, summary="导入题录文件", description="解析 RIS / EndNote(.enw) / PubMed 文本 / WoS 纯文本 / WoS CSV / 读秀超星 题录并批量导入文献库，自动跳过标题为空与已存在的重复记录")
async def import_references(
    body: ImportReferencesBody,
    db: AsyncSession = Depends(get_db),
):
    """解析题录文本并入库。

    - 格式自动探测（reference_parser.parse_references，支持 fmt 显式指定）
    - source_db 取解析 source，source_id 取 pmid（为空则用 doi）
    - 跳过条件：标题为空；source_id（pmid，兜底 doi）或归一化标题已存在
    - 复用 service 层 create_literature 入库
    """
    try:
        result = await import_references_from_text(db, body.ref_text, body.fmt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(
        message=f"导入完成：成功 {result['imported']} 篇，跳过 {result['skipped']} 篇（重复或标题为空）",
        data={
            "imported": result["imported"],
            "skipped": result["skipped"],
            "total": result["total"],
            "errors": result["errors"],
        },
    )


@router.post("/literatures/batch-import-from-folder", response_model=ApiResponse, summary="从文件夹批量导入", description="从服务器本地文件夹批量导入文件，自动匹配已有文献或新建文献记录，支持导入后自动触发AI提取")
async def batch_import_from_folder(
    folder_path: str = Form(..., description="服务器上的文件夹路径，包含要导入的 PDF 等文件"),
    trigger_extraction_after: bool = Form(True, description="新导入的文献是否自动触发 AI 提取"),
    db: AsyncSession = Depends(get_db),
):
    """从服务器本地文件夹批量导入文件，自动匹配已有文献或新建文献记录。

    - 匹配策略：按文件名清洗后精确/模糊匹配已有文献标题
    - 已存在且无文件的文献 → 关联文件（不新建）
    - 已存在且有文件的文献 → 跳过
    - 不存在的文献 → 新建记录 + 可选 AI 提取
    """
    try:
        result = await batch_import_files_from_folder(db, folder_path, trigger_extraction_after)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
):
    """从浏览器上传文件批量导入，自动匹配已有文献或新建文献记录。

    与 batch_import_from_folder 逻辑相同，但文件从浏览器上传而非服务器本地路径。
    """
    try:
        result = await batch_import_uploaded_files(db, files, trigger_extraction_after)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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


# ===== 回收站管理（必须放在 /literatures/{literature_id} 之前，避免 "trash" 被匹配为 literature_id）=====


@router.get("/literatures/trash", response_model=ApiResponse, summary="回收站列表", description="列出回收站中的文献（已软删除的），支持分页和关键词搜索")
async def list_trash(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, description="关键词搜索标题/作者/期刊"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    items, total = await list_trash_literatures(db, page=page, page_size=page_size, keyword=keyword)
    data = [LiteratureResponse.model_validate(item).model_dump() for item in items]
    return ApiResponse(data=PagedResponse(items=data, total=total, page=page, page_size=page_size))


@router.post("/literatures/trash/{literature_id}/restore", response_model=ApiResponse, summary="还原文献", description="从回收站还原文献")
async def restore(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    success = await restore_literature(db, literature_id)
    if not success:
        raise HTTPException(status_code=404, detail="文献不在回收站中")
    return ApiResponse(message="还原成功")


@router.delete("/literatures/trash/{literature_id}", response_model=ApiResponse, summary="永久删除文献", description="从回收站中永久删除单篇文献（含文件，不可恢复）")
async def permanent_delete(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    success = await permanently_delete_literature(db, literature_id)
    if not success:
        raise HTTPException(status_code=404, detail="文献不在回收站中")
    return ApiResponse(message="已永久删除")


@router.post("/literatures/trash/empty", response_model=ApiResponse, summary="清空回收站", description="永久删除回收站中超过30天的文献（含文件）；指定 older_than_days=0 永久删除回收站中所有文献")
async def empty_trash_endpoint(
    older_than_days: int = Query(30, ge=0, description="删除超过此天数的文献，0=全部"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if older_than_days == 0:
        result = await permanently_delete_all_trash(db)
        return ApiResponse(message=f"已永久删除回收站中所有 {result['permanently_deleted']} 篇文献", data=result)
    result = await empty_trash(db, older_than_days=older_than_days)
    return ApiResponse(
        message=f"已永久删除 {result['permanently_deleted']} 篇超过 {older_than_days} 天的文献，回收站剩余 {result['remaining']} 篇",
        data=result,
    )


@router.get("/literatures/{literature_id}", response_model=ApiResponse, summary="获取文献详情", description="根据文献ID获取单篇文献的详细信息")
async def get_one(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    return ApiResponse(data=LiteratureResponse.model_validate(literature).model_dump())


@router.put("/literatures/{literature_id}", response_model=ApiResponse, summary="更新文献信息", description="根据文献ID更新文献的元数据信息，如标题、作者、期刊等")
async def update(
    literature_id: uuid.UUID,
    data: LiteratureUpdate,
    db: AsyncSession = Depends(get_db),
):
    literature = await update_literature(db, literature_id, data.model_dump(exclude_unset=True))
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    return ApiResponse(message="更新成功", data=LiteratureResponse.model_validate(literature).model_dump())


@router.post("/literatures/{literature_id}/file", response_model=ApiResponse, summary="关联文献文件", description="为已有文献关联上传文件（替换原有文件），支持PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML格式")
async def upload_file(
    literature_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """为已有文献关联上传文件（替换原有文件）。"""
    ext = Path(file.filename or "").suffix.lower() if file.filename else ""
    logger.info(f"[关联文件] 收到文件: literature_id={literature_id}, filename={file.filename}, ext={ext or '(未知)'}")
    if ext not in ALLOWED_EXTS:
        logger.warning(f"[关联文件] 格式被拒绝: filename={file.filename}, ext={ext}")
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext or '未知'}，支持 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML",
        )

    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
        logger.warning(f"[关联文件] 文件超限: filename={file.filename}, size={len(file_bytes)}, limit={settings.MAX_UPLOAD_SIZE}")
        raise HTTPException(status_code=400, detail="文件大小超过限制")

    try:
        literature = await upload_literature_file(db, literature_id, file_bytes, file.filename)
    except Exception as e:
        logger.error(f"[关联文件] upload_literature_file 抛出异常: id={literature_id}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件关联失败: {str(e)[:200]}")

    if literature is None:
        raise HTTPException(status_code=404, detail="文献不存在")

    logger.info(f"[关联文件] 成功: id={literature.id}, path={literature.file_path}")
    return ApiResponse(
        message="文件关联成功",
        data=LiteratureResponse.model_validate(literature).model_dump(),
    )


@router.delete("/literatures/{literature_id}", response_model=ApiResponse, summary="删除文献", description="根据文献ID将文献移入回收站（软删除），30天内可还原")
async def delete(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    success = await delete_literature(db, literature_id, deleted_by=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="文献不存在或已在回收站中")
    return ApiResponse(message="已移入回收站")


class BatchDeleteRequest(BaseModel):
    """批量删除文献请求体"""
    literature_ids: list[uuid.UUID]


@router.post("/literatures/batch-delete", response_model=ApiResponse, summary="批量删除文献", description="根据文献ID列表批量将文献移入回收站（软删除），30天内可还原，自动跳过已在回收站中的记录")
async def batch_delete(
    req: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if not req.literature_ids:
        raise HTTPException(status_code=400, detail="未提供要删除的文献ID")
    deleted = await batch_delete_literatures(db, req.literature_ids, deleted_by=current_user.id)
    return ApiResponse(message=f"成功将 {deleted} 篇文献移入回收站")


@router.post("/literatures/cleanup-empty", response_model=ApiResponse, summary="清理无文档无摘要文献", description="将既无文档文件又无摘要内容的文献移入回收站，支持 dry_run 预览")
async def cleanup_empty(
    dry_run: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """清理既无文档又无摘要的文献记录。

    - dry_run=true（默认）：只统计不删除
    - dry_run=false：执行删除（移入回收站）
    """
    result = await cleanup_empty_literatures(db, dry_run=dry_run)
    if dry_run:
        count = result["preview_count"]
        if count == 0:
            return ApiResponse(message="没有需要清理的文献（所有文献均有文档或摘要）", data=result)
        return ApiResponse(message=f"发现 {count} 篇既无文档又无摘要的文献，可清理删除", data=result)
    deleted = result["deleted_count"]
    return ApiResponse(message=f"成功将 {deleted} 篇既无文档又无摘要的文献移入回收站", data=result)


@router.get("/literatures/{literature_id}/file", summary="预览文献文件", description="返回文件流供前端预览（仅PDF支持浏览器内预览，其余格式前端会禁用预览按钮）")
async def get_pdf_file(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """返回文件流供前端预览（仅 PDF 支持浏览器内预览，其余格式前端会禁用预览按钮）"""
    logger.info(f"[预览] 请求文件: literature_id={literature_id}")
    literature = await get_literature(db, literature_id)
    if not literature:
        logger.warning(f"[预览] 文献不存在: id={literature_id}")
        raise HTTPException(status_code=404, detail="文献不存在")

    file_path = _resolve_literature_file(literature)
    if not file_path:
        logger.error(f"[预览] 文件在磁盘上不存在: id={literature_id}, path={literature.file_path}")
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = file_path.suffix.lower()
    safe_filename = _build_safe_filename(literature.title, ext, literature_id)
    mime_type = get_mime_type(ext)
    logger.info(f"[预览] 返回文件流: id={literature_id}, ext={ext}, mime={mime_type}, size={file_path.stat().st_size} bytes")
    return FileResponse(
        path=str(file_path),
        media_type=mime_type,
        filename=safe_filename,
        content_disposition_type="inline",
    )


@router.get("/literatures/{literature_id}/download", summary="下载文献文件", description="下载文献文件（attachment模式），触发浏览器下载，用本地阅读器打开")
async def download_pdf_file(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """下载文件（attachment 模式，触发浏览器下载，用本地阅读器打开）"""
    logger.info(f"[下载] 请求下载: literature_id={literature_id}")
    literature = await get_literature(db, literature_id)
    if not literature:
        logger.warning(f"[下载] 文献不存在: id={literature_id}")
        raise HTTPException(status_code=404, detail="文献不存在")

    file_path = _resolve_literature_file(literature)
    if not file_path:
        logger.error(f"[下载] 文件在磁盘上不存在: id={literature_id}, path={literature.file_path}")
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = file_path.suffix.lower()
    safe_filename = _build_safe_filename(literature.title, ext, literature_id)
    mime_type = get_mime_type(ext)
    logger.info(f"[下载] 返回文件流: id={literature_id}, ext={ext}, mime={mime_type}, size={file_path.stat().st_size} bytes")
    return FileResponse(
        path=str(file_path),
        media_type=mime_type,
        filename=safe_filename,
        content_disposition_type="attachment",
    )


@router.post("/literatures/{literature_id}/open-folder", response_model=ApiResponse, summary="打开所在文件夹", description="在服务器（宿主机）上打开该文献文件所在的文件夹并选中文件，仅当文件存在时可用")
async def open_literature_folder(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """在宿主机上打开文件所在文件夹并选中该文件（Windows 资源管理器）"""
    logger.info(f"[打开文件夹] 请求: literature_id={literature_id}")
    # 仅开发环境启用：生产环境拒绝该宿主机操作
    if settings.APP_ENV != "development":
        raise HTTPException(status_code=403, detail="该功能仅在开发环境可用")
    literature = await get_literature(db, literature_id)
    if not literature:
        logger.warning(f"[打开文件夹] 文献不存在: id={literature_id}")
        raise HTTPException(status_code=404, detail="文献不存在")

    # 解析文件真实路径（与预览/下载共用同一套回退逻辑）
    file_path = _resolve_literature_file(literature)
    if not file_path:
        logger.error(f"[打开文件夹] 文件在磁盘上不存在: id={literature_id}, path={literature.file_path}")
        raise HTTPException(status_code=404, detail="文件不存在，无法打开所在文件夹")

    try:
        resolved = str(file_path.resolve())
        folder = str(file_path.parent)
    except Exception as e:  # pragma: no cover
        logger.error(f"[打开文件夹] 解析路径失败: id={literature_id}, path={file_path}, err={e}")
        raise HTTPException(status_code=500, detail=f"文件路径解析失败: {e}")

    try:
        reveal_in_host_file_manager(resolved, folder)
    except Exception as e:
        logger.error(f"[打开文件夹] 打开文件夹失败: id={literature_id}, path={resolved}, err={e}")
        raise HTTPException(status_code=500, detail=f"打开文件夹失败: {e}")

    logger.info(f"[打开文件夹] 已发起打开请求: id={literature_id}, path={resolved}")
    return ApiResponse(data={
        "opened": True,
        "path": resolved,
        "folder": folder,
    })


@router.get("/literatures/{literature_id}/source-text", response_model=ApiResponse, summary="获取文献溯源文本", description="返回文献的提取文本，支持按字符区间截取，供溯源查看高亮使用，可以获取全文或指定区间的片段")
async def get_source_text(
    literature_id: uuid.UUID,
    start: Optional[int] = Query(None, description="字符起始位置（0-based，含）"),
    end: Optional[int] = Query(None, description="字符结束位置（0-based，不含）"),
    context: int = Query(200, description="前后扩展的上下文字符数", ge=0, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """P2：返回文献的提取文本，支持按字符区间截取（供溯源查看高亮使用）"""
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    # 优先读取缓存的 clean_text 文件
    text_path = LOCAL_STORAGE_DIR / f"{literature_id}.txt"
    if not text_path.exists():
        raise HTTPException(status_code=404, detail="溯源文本未缓存，请重新提取该文献")

    try:
        full_text = text_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取溯源文本失败: {e}")

    total_len = len(full_text)

    # 如果指定了区间，截取并扩展上下文
    if start is not None and end is not None:
        s = max(0, start - context)
        e = min(total_len, end + context)
        snippet = full_text[s:e]
        return ApiResponse(data={
            "full_text": None,
            "snippet": snippet,
            "snippet_start": s,
            "snippet_end": e,
            "highlight_start": start,
            "highlight_end": min(end, total_len),
            "total_length": total_len,
        })

    # 未指定区间，返回全文（大文本时前端自行处理）
    # 限制最大返回 50000 字符，避免响应过大
    if total_len > 50000:
        return ApiResponse(data={
            "full_text": full_text[:50000],
            "snippet": None,
            "total_length": total_len,
            "truncated": True,
        })

    return ApiResponse(data={
        "full_text": full_text,
        "snippet": None,
        "total_length": total_len,
        "truncated": False,
    })


# ===== 查重与合并 API =====

@router.post("/literatures/check-duplicate", response_model=ApiResponse, summary="检查文献重复", description="检查指定文献是否存在重复，支持按文献ID、标题、DOI、作者、PDF哈希值进行匹配检测")
async def check_duplicate(
    req: CheckDuplicateRequest,
    db: AsyncSession = Depends(get_db),
):
    """检查重复文献（按文献ID或字段）"""
    try:
        result = await check_duplicates(
            db, req.literature_id,
            title=req.title, doi=req.doi, authors=req.authors, pdf_hash=req.pdf_hash,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ApiResponse(data={
        "literature_id": result["literature_id"],
        "total": result["total"],
        "duplicates": [
            {
                "literature": LiteratureResponse.model_validate(d["literature"]).model_dump(),
                "match_reasons": d["match_reasons"],
                "match_values": d["match_values"],
            }
            for d in result["duplicates"]
        ],
    })


@router.post("/literatures/scan-duplicates", response_model=ApiResponse, summary="全库扫描重复文献", description="扫描整个文献库，识别所有重复文献并分组返回，用于批量管理重复记录")
async def scan_duplicates_endpoint(
    db: AsyncSession = Depends(get_db),
):
    """全库扫描重复文献"""
    result = await scan_duplicates(db)
    # 将 UUID 转为字符串以便 JSON 序列化
    serializable_groups = []
    for g in result["groups"]:
        serializable_groups.append({
            "literature_ids": [str(uid) for uid in g["literature_ids"]],
            "match_reasons": g["match_reasons"],
            "representative_id": str(g["representative_id"]),
        })
    return ApiResponse(data={
        "groups": serializable_groups,
        "total_groups": result["total_groups"],
        "total_duplicates": result["total_duplicates"],
    })


@router.post("/literatures/merge/preview", response_model=ApiResponse, summary="预览文献合并", description="预览合并结果：展示两篇文献的字段对比及数据点冲突检测，供用户确认合并策略")
async def merge_preview(
    req: MergePreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """预览合并：字段对比 + 数据点冲突检测"""
    try:
        result = await preview_merge(db, req.source_id, req.target_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ApiResponse(data=result)


@router.post("/literatures/merge", response_model=ApiResponse, summary="执行文献合并", description="执行合并操作：将源文献合并进目标文献，根据用户选择的字段和冲突策略处理数据点，删除源文献")
async def merge(
    req: MergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """执行合并：将 source 合并进 target，删除 source"""
    try:
        result = await merge_literatures(
            db, req.source_id, req.target_id,
            req.field_choices,
            req.dp_conflict_strategy,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(
        message="合并成功",
        data={
            "merged_literature": LiteratureResponse.model_validate(result["merged_literature"]).model_dump(),
            "moved_data_points": result["moved_data_points"],
            "deleted_conflict_data_points": result["deleted_conflict_data_points"],
            "deleted_source_id": result["deleted_source_id"],
        },
    )


# ===== 孤儿文件清理 API =====

@router.get("/literatures/cleanup-orphan-files/preview", response_model=ApiResponse, summary="预览孤儿文件清理", description="（管理员）扫描 backend/data/pdfs，列出已不在数据库中的孤儿文件，不执行任何移动/删除")
async def preview_orphan_files_cleanup(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员：预览孤儿文件（dry-run），列出待清理文件而不移动。"""
    scan = await scan_orphan_files(db)
    return ApiResponse(
        message=f"扫描完成：共 {scan['total']} 个文件，其中孤儿文件 {len(scan['orphan'])} 个",
        data={
            "scanned": scan["total"],
            "orphan_count": len(scan["orphan"]),
            "orphan_files": scan["orphan"],
        },
    )


@router.post("/literatures/cleanup-orphan-files", response_model=ApiResponse, summary="清理孤儿文件", description="（管理员）将 backend/data/pdfs 中已不在数据库的孤儿文件移入回收目录（默认保留 30 天后自动删除），可配合 preview 接口先预览")
async def cleanup_orphan_files_endpoint(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员：执行孤儿文件清理（移入回收目录 + 清理过期回收）。"""
    try:
        result = await cleanup_orphan_files(db, dry_run=False)
    except Exception as e:
        logger.error(f"[清理孤儿文件] 执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清理失败: {e}")
    return ApiResponse(
        message=f"清理完成：扫描 {result['scanned']} 个文件，孤儿 {result['orphan_count']} 个，"
                f"移入回收 {result['moved']} 个，失败 {result['failed']} 个",
        data=result,
    )

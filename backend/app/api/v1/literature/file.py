"""文件操作端点 —— 上传、从URL导入、关联文件、预览、下载、打开文件夹、溯源文本。"""

import asyncio
import contextlib
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.config import settings
from app.core.document_parser import ALLOWED_EXTS, _caj_to_pdf_bytes, get_mime_type
from app.core.url_fetcher import fetch_url, guess_title_from_html
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.literature import LiteratureResponse
from app.services.literature._common import LOCAL_STORAGE_DIR, compute_pdf_hash
from app.services.literature.crud import (
    get_file_history,
    get_literature,
    log_file_action,
)
from app.services.literature.import_export import (
    reveal_in_host_file_manager,
    upload_literature,
    upload_literature_file,
)

from ._helpers import (
    _build_file_response,
    _build_pdf_bytes_response,
    _build_safe_filename,
    _caj_pdf_cache,
    _caj_pdf_key,
    _format_file_history,
    _resolve_literature_file,
    _validate_file_magic,
    logger,
)

router = APIRouter()


@router.post("/literatures/upload", response_model=ApiResponse, summary="上传文献文件", description="上传单个文献文件（PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT），并自动创建文献记录，支持指定标题、DOI和省份信息")
async def upload(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    doi: str | None = Form(None),
    province: str | None = Form(None),
    confirm: str | None = Form(None, description="当检测到该文件曾被删除时，传 'true' 表示确认再次导入"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ext = Path(file.filename or "").suffix.lower() if file.filename else ""
    logger.info(
        f"[上传] 收到文件: filename={file.filename}, ext={ext or '(未知)'}, "
        f"title={title or '(无)'}, doi={doi or '(无)'}, province={province or '(无)'}"
    )
    if ext not in ALLOWED_EXTS:
        logger.warning(f"[上传] 格式被拒绝: filename={file.filename}, ext={ext}")
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext or '未知'}，支持 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT",
        )

    content_length = request.headers.get("content-length") if request else None
    if content_length:
        try:
            if int(content_length) > settings.MAX_UPLOAD_SIZE:
                logger.warning(f"[上传] Content-Length 超限: filename={file.filename}, content-length={content_length}")
                raise HTTPException(status_code=413, detail="文件大小超过限制")
        except ValueError:
            pass
    if file.size is not None and file.size > settings.MAX_UPLOAD_SIZE:
        logger.warning(f"[上传] file.size 超限: filename={file.filename}, size={file.size}")
        raise HTTPException(status_code=413, detail="文件大小超过限制")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
        first_chunk = None
        _CHUNK_SIZE = 1024 * 1024
        try:
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                if first_chunk is None:
                    first_chunk = chunk
                tmp.write(chunk)
            tmp.close()
            if first_chunk is not None and not _validate_file_magic(ext, first_chunk):
                logger.warning(f"[上传] 魔数校验失败: filename={file.filename}, ext={ext}, first_bytes={first_chunk[:8].hex()}")
                raise HTTPException(status_code=400, detail="文件内容与扩展名不匹配，请检查文件是否损坏")

            file_bytes = Path(tmp_path).read_bytes()
            file_size = len(file_bytes)
            logger.info(f"[上传] 读取完成: filename={file.filename}, size={file_size} bytes")
            if file_size > settings.MAX_UPLOAD_SIZE:
                raise HTTPException(status_code=400, detail="文件大小超过限制")

            pdf_hash = compute_pdf_hash(file_bytes)
            history = await get_file_history(db, pdf_hash)
            if history and history[0].action == "deleted" and confirm != "true":
                hist_list = _format_file_history(history)
                return ApiResponse(
                    message="该文献此前曾被删除，需确认后再次导入",
                    data={
                        "need_confirm": True,
                        "file_name": file.filename,
                        "pdf_hash": pdf_hash,
                        "history": hist_list,
                    },
                )

            try:
                literature, _action = await upload_literature(db, file_bytes, file.filename, title, doi, province, owner_id=current_user.id)
            except Exception as e:
                logger.error(f"[上传] upload_literature 抛出异常: filename={file.filename}, error={e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)[:200]}") from e

            if literature is None:
                raise HTTPException(status_code=500, detail="文件上传失败")

            if literature.pdf_hash:
                await log_file_action(
                    db,
                    pdf_hash=literature.pdf_hash,
                    file_name=file.filename,
                    action="imported",
                    operator_id=current_user.id,
                    operator_name=getattr(current_user, "display_name", None) or current_user.username,
                    literature_id=literature.id,
                )
            return ApiResponse(
                message="上传成功",
                data=LiteratureResponse.model_validate(literature).model_dump(),
            )
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


@router.post("/literatures/from-url", response_model=ApiResponse, summary="从URL导入文献", description="从指定URL抓取HTML内容并创建文献记录，自动提取页面标题，保存为HTML文件，后续可通过AI提取功能从HTML文本中提取数据点")
async def create_from_url(
    url: str = Form(..., description="要抓取的网页 URL"),
    title: str | None = Form(None, description="文献标题（留空则从 HTML <title> 自动提取）"),
    province: str | None = Form(None, description="关联省份"),
    db: AsyncSession = Depends(get_db),
):
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL 必须以 http:// 或 https:// 开头")
    try:
        content = await fetch_url(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"URL 抓取失败: {str(e)[:200]}") from e
    lit_title = title
    if not lit_title:
        lit_title = guess_title_from_html(content) or url
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc or "webpage"
    filename = f"{domain}.html"
    literature, _action = await upload_literature(db, content, filename, lit_title, province=province)
    if literature is None:
        raise HTTPException(status_code=500, detail="创建文献失败")
    return ApiResponse(
        message="URL 导入成功",
        data=LiteratureResponse.model_validate(literature).model_dump(),
    )


@router.post("/literatures/{literature_id}/file", response_model=ApiResponse, summary="关联文献文件", description="为已有文献关联上传文件（替换原有文件），支持PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML格式")
async def upload_file(
    literature_id: uuid.UUID,
    file: UploadFile = File(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower() if file.filename else ""
    logger.info(f"[关联文件] 收到文件: literature_id={literature_id}, filename={file.filename}, ext={ext or '(未知)'}")
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext or '未知'}")
    content_length = request.headers.get("content-length") if request else None
    if content_length:
        try:
            if int(content_length) > settings.MAX_UPLOAD_SIZE:
                raise HTTPException(status_code=413, detail="文件大小超过限制")
        except ValueError:
            pass
    if file.size is not None and file.size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="文件大小超过限制")
    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制")
    try:
        literature = await upload_literature_file(db, literature_id, file_bytes, file.filename)
    except Exception as e:
        logger.error(f"[关联文件] upload_literature_file 抛出异常: id={literature_id}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件关联失败: {str(e)[:200]}") from e
    if literature is None:
        raise HTTPException(status_code=404, detail="文献不存在")
    return ApiResponse(
        message="文件关联成功",
        data=LiteratureResponse.model_validate(literature).model_dump(),
    )


@router.get("/literatures/{literature_id}/file", summary="预览文献文件", description="返回文件流供前端预览（仅PDF支持浏览器内预览，其余格式前端会禁用预览按钮）")
async def get_pdf_file(
    literature_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    file_path = _resolve_literature_file(literature)
    if not file_path:
        raise HTTPException(status_code=404, detail="文件不存在")
    ext = file_path.suffix.lower()
    safe_filename = _build_safe_filename(literature.title, ext, literature_id)
    mime_type = get_mime_type(ext)
    unsafe_inline = ext in (".html", ".htm", ".svg")
    disposition = "attachment" if unsafe_inline else "inline"
    if ext == ".caj":
        key = _caj_pdf_key(file_path)
        pdf_bytes = _caj_pdf_cache.get(key)
        if pdf_bytes is None:
            logger.info(f"[预览CAJ] 缓存缺失，开始转换: id={literature_id}, size={file_path.stat().st_size} bytes")
            pdf_bytes = await asyncio.to_thread(_caj_to_pdf_bytes, file_path.read_bytes())
            _caj_pdf_cache[key] = pdf_bytes
        return _build_pdf_bytes_response(
            pdf_bytes=pdf_bytes,
            mime_type="application/pdf",
            disposition="inline",
            filename=_build_safe_filename(literature.title, ".pdf", literature_id),
            range_header=request.headers.get("range"),
        )
    return _build_file_response(
        file_path=file_path,
        mime_type=mime_type,
        disposition=disposition,
        filename=safe_filename,
        range_header=request.headers.get("range"),
    )


@router.get("/literatures/{literature_id}/download", summary="下载文献文件", description="下载文献文件（attachment模式），触发浏览器下载，用本地阅读器打开")
async def download_pdf_file(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    file_path = _resolve_literature_file(literature)
    if not file_path:
        raise HTTPException(status_code=404, detail="文件不存在")
    ext = file_path.suffix.lower()
    safe_filename = _build_safe_filename(literature.title, ext, literature_id)
    mime_type = get_mime_type(ext)
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
    if settings.APP_ENV != "development":
        raise HTTPException(status_code=403, detail="该功能仅在开发环境可用")
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    file_path = _resolve_literature_file(literature)
    if not file_path:
        raise HTTPException(status_code=404, detail="文件不存在，无法打开所在文件夹")
    try:
        resolved = str(file_path.resolve())
        folder = str(file_path.parent)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件路径解析失败: {e}") from e
    try:
        reveal_in_host_file_manager(resolved, folder)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败: {e}") from e
    return ApiResponse(data={
        "opened": True,
        "path": resolved,
        "folder": folder,
    })


@router.get("/literatures/{literature_id}/source-text", response_model=ApiResponse, summary="获取文献溯源文本", description="返回文献的提取文本，支持按字符区间截取，供溯源查看高亮使用，可以获取全文或指定区间的片段")
async def get_source_text(
    literature_id: uuid.UUID,
    start: int | None = Query(None, description="字符起始位置（0-based，含）"),
    end: int | None = Query(None, description="字符结束位置（0-based，不含）"),
    context: int = Query(200, description="前后扩展的上下文字符数", ge=0, le=2000),
    db: AsyncSession = Depends(get_db),
):
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    text_path = LOCAL_STORAGE_DIR / f"{literature_id}.txt"
    if not text_path.exists():
        raise HTTPException(status_code=404, detail="溯源文本未缓存，请重新提取该文献")
    try:
        full_text = text_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取溯源文本失败: {e}") from e
    total_len = len(full_text)
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
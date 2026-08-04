import csv
import io
import logging
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger("uvicorn")

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.schemas.common import ApiResponse, PagedResponse
from app.schemas.literature import (
    LiteratureCreate, LiteratureResponse, LiteratureUpdate,
    CheckDuplicateRequest, MergePreviewRequest, MergeRequest,
)
from app.core.document_parser import ALLOWED_EXTS, get_mime_type
from app.core.url_fetcher import fetch_url, guess_title_from_html
from app.services.literature_service import (
    list_literature,
    get_literature,
    create_literature,
    update_literature,
    delete_literature,
    upload_literature,
    check_duplicates,
    scan_duplicates,
    preview_merge,
    merge_literatures,
)

router = APIRouter()


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


@router.post("/literatures/upload", response_model=ApiResponse)
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
        literature = await upload_literature(db, file_bytes, file.filename, title, doi, province)
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


@router.post("/literatures/from-url", response_model=ApiResponse)
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

    literature = await upload_literature(db, content, filename, lit_title, province=province)
    if literature is None:
        logger.error(f"[URL 导入] 创建文献记录失败: {url}")
        raise HTTPException(status_code=500, detail="创建文献失败")

    logger.info(f"[URL 导入] 成功创建文献: id={literature.id}, title={literature.title}")
    return ApiResponse(
        message="URL 导入成功",
        data=LiteratureResponse.model_validate(literature).model_dump(),
    )


@router.get("/literatures", response_model=PagedResponse)
async def list_literatures(
    keyword: Optional[str] = Query(None, description="标题/作者/期刊关键词搜索"),
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    journal: Optional[str] = Query(None, description="期刊名称"),
    sort_by: Optional[str] = Query(None, description="排序字段: title, authors, journal, year, province, created, status"),
    sort_order: Optional[str] = Query(None, description="排序方向: asc, desc"),
    review_status: Optional[str] = Query(None, description="审核状态: none, pending, partial, approved"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_literature(
        db, keyword, disease, province, year_start, year_end, journal, sort_by, sort_order, review_status, page, page_size
    )
    return PagedResponse(
        items=[LiteratureResponse.model_validate(item).model_dump() for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/literatures/export")
async def export_literatures(
    keyword: Optional[str] = Query(None, description="标题/作者/期刊关键词搜索"),
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    journal: Optional[str] = Query(None, description="期刊名称"),
    review_status: Optional[str] = Query(None, description="审核状态: none, pending, partial, approved"),
    db: AsyncSession = Depends(get_db),
):
    """导出文献列表为 CSV"""
    items, _ = await list_literature(
        db, keyword, disease, province, year_start, year_end, journal,
        sort_by=None, sort_order=None, review_status=review_status,
        page=1, page_size=10000,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "标题", "英文标题", "作者", "期刊", "出版年份", "DOI", "PMID",
        "省份", "提取状态", "审核通过数", "数据点总数", "创建时间",
    ])
    for lit in items:
        writer.writerow([
            lit.title, lit.title_en, lit.authors, lit.journal, lit.pub_year,
            lit.doi, lit.pmid, lit.province, lit.extraction_status,
            lit.approved_count, lit.extracted_count, lit.created_at,
        ])

    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''literatures.csv"},
    )


@router.get("/literatures/{literature_id}", response_model=ApiResponse)
async def get_one(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    return ApiResponse(data=LiteratureResponse.model_validate(literature).model_dump())


@router.put("/literatures/{literature_id}", response_model=ApiResponse)
async def update(
    literature_id: uuid.UUID,
    data: LiteratureUpdate,
    db: AsyncSession = Depends(get_db),
):
    literature = await update_literature(db, literature_id, data.model_dump(exclude_unset=True))
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    return ApiResponse(message="更新成功", data=LiteratureResponse.model_validate(literature).model_dump())


@router.delete("/literatures/{literature_id}", response_model=ApiResponse)
async def delete(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    success = await delete_literature(db, literature_id)
    if not success:
        raise HTTPException(status_code=404, detail="文献不存在")
    return ApiResponse(message="删除成功")


@router.get("/literatures/{literature_id}/file")
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

    file_path = Path(literature.file_path) if literature.file_path else None
    if not file_path or not file_path.exists():
        logger.error(f"[预览] 文件在磁盘上不存在: id={literature_id}, path={file_path}")
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


@router.get("/literatures/{literature_id}/download")
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

    file_path = Path(literature.file_path) if literature.file_path else None
    if not file_path or not file_path.exists():
        logger.error(f"[下载] 文件在磁盘上不存在: id={literature_id}, path={file_path}")
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


@router.get("/literatures/{literature_id}/source-text", response_model=ApiResponse)
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
    text_path = Path("data/pdfs") / f"{literature_id}.txt"
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

@router.post("/literatures/check-duplicate", response_model=ApiResponse)
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


@router.post("/literatures/scan-duplicates", response_model=ApiResponse)
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


@router.post("/literatures/merge/preview", response_model=ApiResponse)
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


@router.post("/literatures/merge", response_model=ApiResponse)
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

import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

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
    # 按扩展名白名单校验（支持 PDF/CAJ/EPUB/DOCX/TXT/HTML）
    ext = Path(file.filename or "").suffix.lower() if file.filename else ""
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext or '未知'}，支持 PDF/CAJ/EPUB/DOCX/TXT/HTML",
        )

    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制")

    literature = await upload_literature(db, file_bytes, file.filename, title, doi, province)
    if literature is None:
        raise HTTPException(status_code=500, detail="文件上传失败")

    return ApiResponse(
        message="上传成功",
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
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    file_path = Path(literature.file_path) if literature.file_path else None
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = file_path.suffix.lower()
    safe_filename = _build_safe_filename(literature.title, ext, literature_id)
    return FileResponse(
        path=str(file_path),
        media_type=get_mime_type(ext),
        filename=safe_filename,
        content_disposition_type="inline",
    )


@router.get("/literatures/{literature_id}/download")
async def download_pdf_file(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """下载文件（attachment 模式，触发浏览器下载，用本地阅读器打开）"""
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    file_path = Path(literature.file_path) if literature.file_path else None
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = file_path.suffix.lower()
    safe_filename = _build_safe_filename(literature.title, ext, literature_id)
    return FileResponse(
        path=str(file_path),
        media_type=get_mime_type(ext),
        filename=safe_filename,
        content_disposition_type="attachment",
    )


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

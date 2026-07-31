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
from app.schemas.literature import LiteratureCreate, LiteratureResponse, LiteratureUpdate
from app.services.literature_service import (
    list_literature,
    get_literature,
    create_literature,
    update_literature,
    delete_literature,
    upload_literature,
)

router = APIRouter()


@router.post("/literatures/upload", response_model=ApiResponse)
async def upload(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    doi: Optional[str] = Form(None),
    province: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="只支持 PDF 文件")

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
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_literature(
        db, keyword, disease, province, year_start, year_end, journal, sort_by, sort_order, page, page_size
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
    """返回 PDF 文件流供前端预览"""
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    file_path = Path(literature.file_path) if literature.file_path else None
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在")

    safe_filename = quote(f"{literature.title or literature_id}.pdf")
    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=safe_filename,
        content_disposition_type="inline",
    )

"""CRUD 端点 —— 文献列表/详情/更新/删除/回收站/导入日志/清理无文档/标题修正/AI验证。"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.kg_triple import KGTriple
from app.models.user import User
from app.schemas.common import ApiResponse, PagedResponse
from app.schemas.literature import LiteratureResponse, LiteratureUpdate
from app.services.literature._common import list_import_logs
from app.services.literature.cleanup import (
    batch_delete_literatures,
    cleanup_empty_literatures,
)
from app.services.literature.crud import (
    delete_literature,
    empty_trash,
    get_literature,
    list_literature,
    list_trash_literatures,
    log_file_action,
    permanently_delete_all_trash,
    permanently_delete_literature,
    restore_literature,
    update_literature,
)
from app.services.literature.metadata import (
    ai_verify_titles,
    fix_titles,
)

router = APIRouter()


# ===== 文献列表 / 详情 / 更新 =====


@router.get("/literatures", response_model=PagedResponse, summary="获取文献列表", description="分页获取文献列表，支持关键词、疾病、省份、年份、期刊、审核状态、提取状态、标签等多维度筛选和排序")
async def list_literatures(
    keyword: str | None = Query(None, description="标题/作者/期刊关键词搜索"),
    disease: str | None = Query(None, description="疾病筛选"),
    province: str | None = Query(None, description="省份筛选"),
    year_start: int | None = Query(None, description="起始年份"),
    year_end: int | None = Query(None, description="结束年份"),
    journal: str | None = Query(None, description="期刊名称"),
    title: str | None = Query(None, description="标题筛选（模糊匹配）"),
    authors: str | None = Query(None, description="作者筛选（模糊匹配）"),
    created_start: datetime | None = Query(None, description="创建时间起（含当日）"),
    created_end: datetime | None = Query(None, description="创建时间止（含当日）"),
    sort_by: str | None = Query(None, description="排序字段: title, authors, journal, year, province, created, status, file_format"),
    sort_order: str | None = Query(None, description="排序方向: asc, desc"),
    review_status: str | None = Query(None, description="审核状态: none, pending, partial, approved"),
    extraction_status: str | None = Query(None, description="提取状态: pending, processing, done, done_no_data, failed"),
    file_format: str | None = Query(None, description="文档格式筛选: PDF, CAJ, EPUB, DOCX, PPTX, XLSX, TXT, HTML, URL"),
    tag_id: uuid.UUID | None = Query(None, description="标签筛选：只显示有该标签的文献"),
    has_abstract: bool | None = Query(None, description="摘要筛选：true=有摘要，false=无摘要"),
    kg_extracted: bool | None = Query(None, description="知识库(KG)抽取状态筛选：true=已抽取，false=未抽取"),
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
        has_abstract=has_abstract, kg_extracted=kg_extracted, page=page, page_size=page_size,
    )

    def _derive_file_format(lit) -> str | None:
        """根据 file_path / title / source_db 推导文献文件格式，大写后缀，None 表示无本地文件。"""
        path = getattr(lit, "file_path", None) or ""
        if path:
            low = path.lower()
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
                if low.endswith(".html") or low.endswith(".htm"):
                    return "HTML"
                return "URL"
            ext = low.rsplit(".", 1)[-1] if "." in low else ""
            ext = ext.split("?", 1)[0]
            if ext in {"pdf", "caj", "epub", "docx", "pptx", "xlsx", "txt", "html", "htm"}:
                return ext.upper() if ext != "htm" else "HTML"
        if getattr(lit, "source_db", None):
            return None
        return None

    # 知识库(KG)三元组抽取状态：按当前页文献批量聚合三元组数量，避免每篇一次查询
    lit_ids = [getattr(item, "id", None) for item in items]
    kg_counts: dict[str, int] = {}
    if lit_ids:
        triples_res = await db.execute(
            select(KGTriple.literature_id, func.count(KGTriple.id))
            .where(KGTriple.literature_id.in_(lit_ids))
            .group_by(KGTriple.literature_id)
        )
        for lid, cnt in triples_res.all():
            kg_counts[str(lid)] = cnt

    serialized = []
    for item in items:
        data = LiteratureResponse.model_validate(item).model_dump()
        data["file_format"] = _derive_file_format(item)
        try:
            data["tags"] = [{"id": str(t.id), "name": t.name, "color": t.color} for t in (item.tags or [])]
        except Exception:
            data["tags"] = []
        _lid = str(getattr(item, "id", ""))
        data["kg_extracted"] = _lid in kg_counts
        data["kg_triple_count"] = kg_counts.get(_lid, 0)
        serialized.append(data)

    return PagedResponse(
        items=serialized,
        total=total,
        page=page,
        page_size=page_size,
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


@router.delete("/literatures/{literature_id}", response_model=ApiResponse, summary="删除文献", description="根据文献ID将文献移入回收站（软删除），30天内可还原")
async def delete(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    lit = await get_literature(db, literature_id)
    if lit and lit.pdf_hash:
        await log_file_action(
            db,
            pdf_hash=lit.pdf_hash,
            file_name=lit.file_path,
            action="deleted",
            operator_id=current_user.id,
            operator_name=getattr(current_user, "display_name", None) or current_user.username,
            literature_id=lit.id,
        )
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
    for lid in req.literature_ids:
        lit = await get_literature(db, lid)
        if lit and lit.pdf_hash:
            await log_file_action(
                db,
                pdf_hash=lit.pdf_hash,
                file_name=lit.file_path,
                action="deleted",
                operator_id=current_user.id,
                operator_name=getattr(current_user, "display_name", None) or current_user.username,
                literature_id=lit.id,
            )
    deleted = await batch_delete_literatures(db, req.literature_ids, deleted_by=current_user.id)
    return ApiResponse(message=f"成功将 {deleted} 篇文献移入回收站")


# ===== 回收站（必须放在 /literatures/{literature_id} 之前，避免 "trash" 被匹配为 literature_id）=====


@router.get("/literatures/trash", response_model=ApiResponse, summary="回收站列表", description="列出回收站中的文献（已软删除的），支持分页和关键词搜索")
async def list_trash(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, description="关键词搜索标题/作者/期刊"),
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


# ===== 导入日志 =====


@router.get("/literatures/import-logs", response_model=PagedResponse, summary="查询题录导入日志", description="分页查询题录导入工作日志，按时间倒序")
async def get_import_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await list_import_logs(db, page=page, page_size=page_size)
    return PagedResponse(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        message=f"共 {result['total']} 条导入日志",
    )


# ===== 清理无文档无摘要 =====


@router.post("/literatures/cleanup-empty", response_model=ApiResponse, summary="清理无文档无摘要文献", description="将既无文档文件又无摘要内容的文献移入回收站，支持 dry_run 预览")
async def cleanup_empty(
    dry_run: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await cleanup_empty_literatures(db, dry_run=dry_run)
    if dry_run:
        count = result["preview_count"]
        if count == 0:
            return ApiResponse(message="没有需要清理的文献（所有文献均有文档或摘要）", data=result)
        return ApiResponse(message=f"发现 {count} 篇既无文档又无摘要的文献，可清理删除", data=result)
    deleted = result["deleted_count"]
    return ApiResponse(message=f"成功将 {deleted} 篇既无文档又无摘要的文献移入回收站", data=result)


# ===== 标题修正 =====


class FixTitleItem(BaseModel):
    """单条标题修正项"""
    id: str
    new_title: str


class ApplyFixTitlesRequest(BaseModel):
    """选择性应用标题修正的请求体"""
    fixes: list[FixTitleItem]


@router.post("/literatures/fix-titles", response_model=ApiResponse, summary="修正文件名来源的文献标题", description="扫描并修正文件名来源的文献标题（年份前缀、中文字符间下划线等），支持 dry_run 预览，或选择性提交修正项")
async def fix_titles_endpoint(
    body: ApplyFixTitlesRequest | None = None,
    dry_run: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if body and body.fixes:
        fixed = await fix_titles(db, fixes=[(f.id, f.new_title) for f in body.fixes])
        return ApiResponse(message=f"成功修正 {fixed} 条文献标题", data={"fixed_count": fixed})
    result = await fix_titles(db, dry_run=dry_run)
    count = result["preview_count"]
    if dry_run:
        if count == 0:
            return ApiResponse(message="所有文献标题均无需修正", data=result)
        return ApiResponse(message=f"发现 {count} 条文献标题可修正，请确认后执行", data=result)
    return ApiResponse(message=f"成功修正 {result['fixed_count']} 条文献标题", data=result)


@router.post("/literatures/ai-verify-titles", response_model=ApiResponse, summary="AI 验证文献标题", description="从文献文档中用 LLM 提取真实标题，与数据库存储标题比对，标记差异较大的标题")
async def ai_verify_titles_endpoint(
    limit: int = 50,
    model: str | None = Query(None, description="LLM 模型名称"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await ai_verify_titles(db, limit=limit, model=model)
    dc = result["mismatches"]
    if dc:
        msg = f"已扫描 {result['verified']} 篇文献，发现 {len(dc)} 篇标题与文档内容不一致"
    else:
        msg = f"已扫描 {result['verified']} 篇文献，所有标题均与文档内容一致"
    return ApiResponse(message=msg, data=result)
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
import uuid

from sqlalchemy import and_, case, or_, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.models.literature_file_history import LiteratureFileHistory
from app.schemas.literature import LiteratureCreate
from app.core.minio_client import delete_file
from app.config import settings
from app.services.literature._common import (
    logger,
    LOCAL_STORAGE_DIR,
    _is_safe_local_path,
    _build_file_format_expr,
    FILE_FORMATS,
    TRASH_RETENTION_DAYS,
)


async def list_literature(
    db: AsyncSession,
    keyword: Optional[str] = None,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    journal: Optional[str] = None,
    title: Optional[str] = None,
    authors: Optional[str] = None,
    created_start: Optional[datetime] = None,
    created_end: Optional[datetime] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    review_status: Optional[str] = None,
    extraction_status: Optional[str] = None,
    file_format: Optional[str] = None,
    tag_id: Optional[uuid.UUID] = None,
    has_abstract: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Literature], int]:
    query = select(Literature).where(Literature.deleted_at.is_(None))
    count_query = select(func.count(Literature.id)).where(Literature.deleted_at.is_(None))

    # 卡死检测：将 processing/queued 超过阈值的记录自动重置为 failed
    # F14：心跳感知——worker 心跳持续刷新的任务视为存活，不误判；
    #   - worker_heartbeat 非空：仅当心跳本身超过阈值才回收（worker 崩溃后心跳停止）
    #   - worker_heartbeat 为空（历史记录/未启用心跳）：回退用 extraction_started_at 判活
    stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=settings.EXTRACTION_STALE_MINUTES)
    stale_stmt = (
        update(Literature)
        .where(
            Literature.extraction_status.in_(["processing", "queued"]),
            or_(
                and_(
                    Literature.worker_heartbeat.isnot(None),
                    Literature.worker_heartbeat < stale_threshold,
                ),
                and_(
                    Literature.worker_heartbeat.is_(None),
                    Literature.extraction_started_at.isnot(None),
                    Literature.extraction_started_at < stale_threshold,
                ),
            ),
        )
        .values(
            extraction_status="failed",
            extraction_started_at=None,
            worker_heartbeat=None,
        )
    )
    result = await db.execute(stale_stmt)
    if result.rowcount > 0:
        logger.info(f"自动重置了 {result.rowcount} 条卡死提取状态为 failed")

    if tag_id:
        from app.models.literature_tag import literature_tag
        query = query.join(literature_tag).where(literature_tag.c.tag_id == tag_id)
        count_query = count_query.join(literature_tag).where(literature_tag.c.tag_id == tag_id)

    if keyword:
        like = f"%{keyword}%"
        query = query.where(
            Literature.title.ilike(like)
            | Literature.authors.ilike(like)
            | Literature.journal.ilike(like)
            | Literature.abstract.ilike(like)
            | func.array_to_string(Literature.keywords, " ").ilike(like)
        )
        count_query = count_query.where(
            Literature.title.ilike(like)
            | Literature.authors.ilike(like)
            | Literature.journal.ilike(like)
            | Literature.abstract.ilike(like)
            | func.array_to_string(Literature.keywords, " ").ilike(like)
        )

    if province:
        query = query.where(Literature.province == province)
        count_query = count_query.where(Literature.province == province)

    if year_start:
        query = query.where(Literature.pub_year >= year_start)
        count_query = count_query.where(Literature.pub_year >= year_start)

    if year_end:
        query = query.where(Literature.pub_year <= year_end)
        count_query = count_query.where(Literature.pub_year <= year_end)

    if journal:
        query = query.where(Literature.journal.ilike(f"%{journal}%"))
        count_query = count_query.where(Literature.journal.ilike(f"%{journal}%"))

    # 列级筛选：标题 / 作者（模糊匹配）
    if title:
        query = query.where(Literature.title.ilike(f"%{title}%"))
        count_query = count_query.where(Literature.title.ilike(f"%{title}%"))

    if authors:
        query = query.where(Literature.authors.ilike(f"%{authors}%"))
        count_query = count_query.where(Literature.authors.ilike(f"%{authors}%"))

    # 创建时间范围筛选（created_end 视为当天 23:59:59 截止，含当日）
    if created_start:
        query = query.where(Literature.created_at >= created_start)
        count_query = count_query.where(Literature.created_at >= created_start)

    if created_end:
        _end = created_end + timedelta(days=1)
        query = query.where(Literature.created_at < _end)
        count_query = count_query.where(Literature.created_at < _end)

    # 审核状态筛选
    if review_status:
        if review_status == "none":
            # 无数据：extracted_count == 0
            query = query.where(Literature.extracted_count == 0)
            count_query = count_query.where(Literature.extracted_count == 0)
        elif review_status == "pending":
            # 未审核：有数据但 approved_count == 0
            query = query.where(Literature.extracted_count > 0, Literature.approved_count == 0)
            count_query = count_query.where(Literature.extracted_count > 0, Literature.approved_count == 0)
        elif review_status == "partial":
            # 部分审核：0 < approved_count < extracted_count
            query = query.where(Literature.approved_count > 0, Literature.approved_count < Literature.extracted_count)
            count_query = count_query.where(Literature.approved_count > 0, Literature.approved_count < Literature.extracted_count)
        elif review_status == "approved":
            # 已完成：approved_count == extracted_count AND extracted_count > 0
            query = query.where(Literature.extracted_count > 0, Literature.approved_count == Literature.extracted_count)
            count_query = count_query.where(Literature.extracted_count > 0, Literature.approved_count == Literature.extracted_count)

    # 提取状态筛选
    if extraction_status:
        query = query.where(Literature.extraction_status == extraction_status)
        count_query = count_query.where(Literature.extraction_status == extraction_status)

    # 文档格式筛选（PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML/URL）
    if file_format:
        fmt = file_format.strip().upper()
        if fmt == "__NONE__":
            query = query.where(Literature.file_path.is_(None))
            count_query = count_query.where(Literature.file_path.is_(None))
        elif fmt in FILE_FORMATS:
            fexpr = _build_file_format_expr(Literature.file_path)
            query = query.where(fexpr == fmt)
            count_query = count_query.where(fexpr == fmt)

    # 摘要筛选
    if has_abstract is not None:
        if has_abstract:
            query = query.where(Literature.abstract != None, Literature.abstract != "")
            count_query = count_query.where(Literature.abstract != None, Literature.abstract != "")
        else:
            query = query.where((Literature.abstract == None) | (Literature.abstract == ""))
            count_query = count_query.where((Literature.abstract == None) | (Literature.abstract == ""))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    sort_column: Any = Literature.created_at
    sort_desc = True

    if sort_by:
        # 文档格式排序：按派生的格式名（CAJ/PDF/...）分组排序，而不是按完整 file_path
        if sort_by == "file_format":
            sort_column = _build_file_format_expr(Literature.file_path)
        else:
            sort_map: dict[str, Any] = {
                "title": Literature.title,
                "authors": Literature.authors,
                "journal": Literature.journal,
                "year": Literature.pub_year,
                "province": Literature.province,
                "created": Literature.created_at,
                "status": Literature.extraction_status,
                "abstract": Literature.abstract,
            }
            if sort_by == "review_status":
                # 审核状态排序：提取总数为 0 → 排最后；按审核比例 approved/extracted 从小到大；
                # 使用 case when 计算一个排序键：0(无数据) < 1(部分审核)，而区间内部用比例区分
                ratio = case(
                    (Literature.extracted_count == None, 0),
                    (Literature.extracted_count == 0, 0),
                    else_=func.coalesce(Literature.approved_count, 0) * 1.0 / Literature.extracted_count,
                )
                sort_column = ratio
            else:
                sort_column = sort_map.get(sort_by, Literature.created_at)
            sort_html = False

    if sort_order:
        sort_desc = sort_order.lower() == "desc"

    # 文档格式排序时，无文件（NULL）始终排在最后，无论升降序
    if sort_by == "file_format":
        query = query.order_by(
            sort_column.desc().nulls_last() if sort_desc else sort_column.asc().nulls_last()
        )
    else:
        query = query.order_by(sort_column.desc() if sort_desc else sort_column.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def get_literature(db: AsyncSession, literature_id: uuid.UUID) -> Optional[Literature]:
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id, Literature.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_literature(db: AsyncSession, data: LiteratureCreate) -> Literature:
    literature = Literature(
        title=data.title,
        title_en=data.title_en,
        authors=data.authors,
        journal=data.journal,
        pub_year=data.pub_year,
        doi=data.doi,
        pmid=data.pmid,
        abstract=data.abstract,
        keywords=data.keywords,
        region=data.region,
        province=data.province,
        publication_types=data.publication_types,
        source_db=data.source_db,
        file_path=data.file_path,
        has_fulltext=data.has_fulltext,
    )
    db.add(literature)
    await db.commit()
    await db.refresh(literature)
    return literature


async def update_literature(
    db: AsyncSession,
    literature_id: uuid.UUID,
    data: dict,
) -> Optional[Literature]:
    literature = await get_literature(db, literature_id)
    if not literature:
        return None

    updatable_fields = [
        "title", "title_en", "authors", "journal", "pub_year", "doi", "pmid",
        "abstract", "keywords", "region", "province", "publication_types",
        "source_db", "has_fulltext", "extraction_status",
        "extracted_count", "approved_count",
    ]
    for field in updatable_fields:
        if field in data and data[field] is not None:
            setattr(literature, field, data[field])

    literature.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(literature)
    return literature


async def get_file_history(
    db: AsyncSession,
    pdf_hash: str,
) -> list[LiteratureFileHistory]:
    """按文件指纹查询该文件的导入/删除历史，按时间倒序返回。"""
    result = await db.execute(
        select(LiteratureFileHistory)
        .where(LiteratureFileHistory.pdf_hash == pdf_hash)
        .order_by(LiteratureFileHistory.operated_at.desc())
    )
    return list(result.scalars().all())


async def log_file_action(
    db: AsyncSession,
    *,
    pdf_hash: str,
    file_name: Optional[str],
    action: str,
    operator_id: Optional[uuid.UUID] = None,
    operator_name: Optional[str] = None,
    literature_id: Optional[uuid.UUID] = None,
) -> LiteratureFileHistory:
    """记录一次文献文件动作（imported=导入 / deleted=软删除）。"""
    record = LiteratureFileHistory(
        pdf_hash=pdf_hash,
        file_name=file_name,
        literature_id=literature_id,
        action=action,
        operator_id=operator_id,
        operator_name=operator_name,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info(
        f"[文件历史] 记录动作: action={action}, pdf_hash={pdf_hash[:12]}..., operator={operator_name or '未知'}"
    )
    return record


async def delete_literature(
    db: AsyncSession,
    literature_id: uuid.UUID,
    deleted_by: Optional[uuid.UUID] = None,
) -> bool:
    """软删除文献：设置 deleted_at 时间戳，将文献移入回收站。
    保留文件，30天内可还原。
    """
    literature = await get_literature(db, literature_id)
    if not literature:
        return False
    if literature.deleted_at is not None:
        return False  # 已在回收站中，不再重复删除

    literature.deleted_at = datetime.now(timezone.utc)
    literature.deleted_by = deleted_by
    await db.commit()
    return True


async def get_literature_from_trash(db: AsyncSession, literature_id: uuid.UUID) -> Optional[Literature]:
    """从回收站获取文献（不过滤 deleted_at）。"""
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    return result.scalar_one_or_none()


async def list_trash_literatures(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
) -> tuple[list[Literature], int]:
    """列出回收站中的文献（已软删除的）。"""
    query = select(Literature).where(Literature.deleted_at.is_not(None))
    count_query = select(func.count(Literature.id)).where(Literature.deleted_at.is_not(None))

    if keyword:
        like = f"%{keyword}%"
        query = query.where(
            Literature.title.ilike(like)
            | Literature.authors.ilike(like)
            | Literature.journal.ilike(like)
        )
        count_query = count_query.where(
            Literature.title.ilike(like)
            | Literature.authors.ilike(like)
            | Literature.journal.ilike(like)
        )

    query = query.order_by(Literature.deleted_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    return items, total


async def restore_literature(db: AsyncSession, literature_id: uuid.UUID) -> bool:
    """从回收站还原文献：清除 deleted_at 和 deleted_by。"""
    literature = await get_literature_from_trash(db, literature_id)
    if not literature or literature.deleted_at is None:
        return False
    literature.deleted_at = None
    literature.deleted_by = None
    await db.commit()
    return True


async def permanently_delete_literature(db: AsyncSession, literature_id: uuid.UUID) -> bool:
    """永久删除文献（从回收站中彻底删除，含文件）。"""
    literature = await get_literature_from_trash(db, literature_id)
    if not literature or literature.deleted_at is None:
        return False

    # 删除文件（MinIO 或本地）
    if literature.file_path:
        local_path = _is_safe_local_path(literature.file_path)
        if local_path and local_path.exists():
            try:
                os.remove(local_path)
                logger.info(f"Local file permanently deleted: {local_path}")
            except Exception as e:
                logger.warning(f"Failed to delete local file: {e}")
        elif not local_path:
            logger.error(f"[安全] 文件路径越界，跳过删除: {literature.file_path}")
            delete_file(literature.file_path)

    await db.delete(literature)
    await db.commit()
    return True


async def empty_trash(db: AsyncSession, older_than_days: int = TRASH_RETENTION_DAYS) -> dict:
    """清空回收站中超过指定天数的文献（永久删除，含文件）。
    返回 {"permanently_deleted": int, "remaining": int}。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    query = select(Literature).where(
        Literature.deleted_at.is_not(None),
        Literature.deleted_at < cutoff,
    )
    result = await db.execute(query)
    items = list(result.scalars().all())

    count = 0
    for lit in items:
        try:
            if lit.file_path:
                local_path = _is_safe_local_path(lit.file_path)
                if local_path and local_path.exists():
                    os.remove(local_path)
                else:
                    if local_path is None:
                        logger.error(f"[安全] 文件路径越界，跳过删除: id={lit.id}, path={lit.file_path}")
                    delete_file(lit.file_path)
            await db.delete(lit)
            count += 1
        except Exception as e:
            logger.warning(f"[回收站] 永久删除失败: id={lit.id}, err={e}")
    await db.commit()

    # 统计剩余
    remaining_query = select(func.count(Literature.id)).where(Literature.deleted_at.is_not(None))
    remaining_result = await db.execute(remaining_query)
    remaining = remaining_result.scalar() or 0
    return {"permanently_deleted": count, "remaining": remaining}


async def permanently_delete_all_trash(db: AsyncSession) -> dict:
    """永久删除回收站中所有文献（含文件）。
    返回 {"permanently_deleted": int}。
    """
    query = select(Literature).where(Literature.deleted_at.is_not(None))
    result = await db.execute(query)
    items = list(result.scalars().all())

    count = 0
    for lit in items:
        try:
            if lit.file_path:
                local_path = _is_safe_local_path(lit.file_path)
                if local_path and local_path.exists():
                    os.remove(local_path)
                else:
                    if local_path is None:
                        logger.error(f"[安全] 文件路径越界，跳过删除: id={lit.id}, path={lit.file_path}")
                    delete_file(lit.file_path)
            await db.delete(lit)
            count += 1
        except Exception as e:
            logger.warning(f"[回收站] 永久删除全部失败: id={lit.id}, err={e}")
    await db.commit()
    return {"permanently_deleted": count}
import logging
import os
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.schemas.literature import LiteratureCreate
from app.core.minio_client import upload_file, delete_file

logger = logging.getLogger("uvicorn")

LOCAL_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "pdfs"


async def list_literature(
    db: AsyncSession,
    keyword: Optional[str] = None,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    journal: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Literature], int]:
    query = select(Literature)
    count_query = select(func.count(Literature.id))

    if keyword:
        like = f"%{keyword}%"
        query = query.where(Literature.title.ilike(like) | Literature.authors.ilike(like) | Literature.journal.ilike(like))
        count_query = count_query.where(Literature.title.ilike(like) | Literature.authors.ilike(like) | Literature.journal.ilike(like))

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

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    sort_column = Literature.created_at
    sort_desc = True

    if sort_by:
        sort_map = {
            "title": Literature.title,
            "authors": Literature.authors,
            "journal": Literature.journal,
            "year": Literature.pub_year,
            "province": Literature.province,
            "created": Literature.created_at,
            "status": Literature.extraction_status,
        }
        sort_column = sort_map.get(sort_by, Literature.created_at)

    if sort_order:
        sort_desc = sort_order.lower() == "desc"

    query = query.order_by(sort_column.desc() if sort_desc else sort_column.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def get_literature(db: AsyncSession, literature_id: uuid.UUID) -> Optional[Literature]:
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
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
        "source_db", "file_path", "has_fulltext", "extraction_status",
        "extracted_count", "approved_count",
    ]
    for field in updatable_fields:
        if field in data and data[field] is not None:
            setattr(literature, field, data[field])

    literature.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(literature)
    return literature


async def delete_literature(db: AsyncSession, literature_id: uuid.UUID) -> bool:
    literature = await get_literature(db, literature_id)
    if not literature:
        return False

    # 删除文件（MinIO 或本地）
    if literature.file_path:
        # 如果是本地文件路径
        local_path = Path(literature.file_path)
        if local_path.exists():
            try:
                os.remove(local_path)
                logger.info(f"Local file deleted: {local_path}")
            except Exception as e:
                logger.warning(f"Failed to delete local file: {e}")
        else:
            # 尝试从 MinIO 删除
            delete_file(literature.file_path)

    await db.delete(literature)
    await db.commit()
    return True


async def upload_literature(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
    title: Optional[str] = None,
    doi: Optional[str] = None,
    province: Optional[str] = None,
) -> Optional[Literature]:
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"

    # 1. 始终保存到本地文件系统（确保提取时能找到文件）
    LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    local_filename = f"{uuid.uuid4()}.{ext}"
    local_path = LOCAL_STORAGE_DIR / local_filename
    with open(local_path, "wb") as f:
        f.write(file_bytes)
    logger.info(f"PDF saved locally: {local_path}")

    # 2. 尝试上传到 MinIO（仅用于分布式/备份场景，失败不阻塞）
    object_name = f"literature/{uuid.uuid4()}.{ext}"
    minio_path = upload_file(file_bytes, object_name, content_type="application/pdf")
    if minio_path is None:
        logger.warning("MinIO 不可用，仅保存本地副本")

    # 3. 数据库记录使用本地路径（_download_pdf 会优先匹配本地文件）
    stored_path = str(local_path)

    # 创建文献记录
    literature = Literature(
        title=title or filename,
        doi=doi,
        province=province,
        file_path=stored_path,
        has_fulltext=True,
        source_db="upload",
    )
    db.add(literature)
    await db.commit()
    await db.refresh(literature)
    return literature

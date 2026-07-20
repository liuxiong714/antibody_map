import logging
import uuid
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.schemas.literature import LiteratureCreate
from app.core.minio_client import upload_file, delete_file

logger = logging.getLogger("uvicorn")


async def list_literature(
    db: AsyncSession,
    keyword: Optional[str] = None,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Literature], int]:
    query = select(Literature)
    count_query = select(func.count(Literature.id))

    if keyword:
        like = f"%{keyword}%"
        query = query.where(Literature.title.ilike(like))
        count_query = count_query.where(Literature.title.ilike(like))

    if province:
        query = query.where(Literature.province == province)
        count_query = count_query.where(Literature.province == province)

    # disease filter uses data_point join — for now do simple filter if needed
    # Can be extended via a subquery on data_point table

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    query = query.order_by(Literature.created_at.desc())
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

    # 删除 MinIO 中的文件
    if literature.file_path:
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
    # 上传到 MinIO
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"
    object_name = f"literature/{uuid.uuid4()}.{ext}"
    stored_path = upload_file(file_bytes, object_name, content_type="application/pdf")

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

import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import re
import subprocess  # 打开宿主机文件夹使用
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.models.data_point import DataPoint
from app.schemas.literature import LiteratureCreate
from app.config import settings
from app.core.document_parser import get_mime_type
from app.core.minio_client import upload_file, delete_file
from app.services.reference_parser import parse_references

logger = logging.getLogger("uvicorn")

LOCAL_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "pdfs"


# ===== 查重辅助函数 =====

def compute_pdf_hash(file_bytes: bytes) -> str:
    """计算文件内容的 SHA-256 哈希"""
    return hashlib.sha256(file_bytes).hexdigest()


def normalize_title(title: Optional[str]) -> str:
    """标题归一化：小写 + 替换连字符为空格 + 去标点 + 压缩空格"""
    if not title:
        return ""
    t = title.lower().strip()
    t = re.sub(r"[-–—]", " ", t)  # 连字符统一替换为空格
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _first_author_surname(authors: Optional[str]) -> str:
    """取第一作者姓氏（归一化）"""
    if not authors:
        return ""
    first = authors.split(",")[0].split(";")[0].strip()
    parts = re.split(r"[\s,]+", first)
    return parts[-1].lower() if parts else ""


def _title_similarity(a: str, b: str) -> float:
    """Jaccard 词集相似度"""
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _is_dp_conflict(a: "DataPoint", b: "DataPoint") -> bool:
    """判断两个数据点是否冲突：disease + province + collection_year + data_type 全同"""
    return (
        (a.disease or None) == (b.disease or None)
        and (a.province or None) == (b.province or None)
        and (a.collection_year or None) == (b.collection_year or None)
        and (a.data_type or None) == (b.data_type or None)
    )


def _dp_to_dict(dp: "DataPoint") -> dict:
    """将 DataPoint 序列化为字典"""
    return {
        "id": str(dp.id),
        "disease": dp.disease,
        "province": dp.province,
        "city": dp.city,
        "data_type": dp.data_type,
        "value": float(dp.value) if dp.value is not None else None,
        "unit": dp.unit,
        "sample_size": dp.sample_size,
        "collection_year": dp.collection_year,
        "age_min": dp.age_min,
        "age_max": dp.age_max,
        "review_status": dp.review_status,
    }


# 文档格式筛选/排序使用的已知格式集合（与派生逻辑 _derive_file_format 保持一致）
FILE_FORMATS = ["PDF", "CAJ", "EPUB", "DOCX", "PPTX", "XLSX", "TXT", "HTML", "URL"]


def _build_file_format_expr(file_path_expr):
    """将 file_path 列映射为可排序/可筛选的文档格式 CASE 表达式（大写格式名）。

    与列表接口的 _derive_file_format 保持逻辑一致：
    - 本地文件路径按扩展名（.pdf/.caj/.docx...）判定；
    - URL：带 .pdf 等后缀的按扩展名判定，否则视为 URL/HTML。
    无文件（file_path 为空）时结果为 NULL。
    """
    low = func.lower(file_path_expr)
    return case(
        (low.like("%.pdf"), "PDF"),
        (low.like("%.caj"), "CAJ"),
        (low.like("%.epub"), "EPUB"),
        (low.like("%.docx"), "DOCX"),
        (low.like("%.pptx"), "PPTX"),
        (low.like("%.xlsx"), "XLSX"),
        (low.like("%.txt"), "TXT"),
        (low.like("%.htm"), "HTML"),
        (low.like("http://%"), "URL"),
        (low.like("https://%"), "URL"),
        else_=None,
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


# ===== 回收站管理 =====

TRASH_RETENTION_DAYS: int = 30


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
        local_path = Path(literature.file_path)
        if local_path.exists():
            try:
                os.remove(local_path)
                logger.info(f"Local file permanently deleted: {local_path}")
            except Exception as e:
                logger.warning(f"Failed to delete local file: {e}")
        else:
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
                local_path = Path(lit.file_path)
                if local_path.exists():
                    os.remove(local_path)
                else:
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
                local_path = Path(lit.file_path)
                if local_path.exists():
                    os.remove(local_path)
                else:
                    delete_file(lit.file_path)
            await db.delete(lit)
            count += 1
        except Exception as e:
            logger.warning(f"[回收站] 永久删除全部失败: id={lit.id}, err={e}")
    await db.commit()
    return {"permanently_deleted": count}


# 文件扩展名正则，用于从文件名中提取标题
_TITLE_EXT_PATTERN = re.compile(r"\.(pdf|caj|doc|docx|txt|epub|pptx|xlsx|ps|wps|md)$", re.IGNORECASE)
# 年份前缀正则，用于从文件名中去除年份前缀（含 YYYY_、YYYY-MM-DD_ 等格式）
_TITLE_YEAR_PREFIX = re.compile(
    r"^("
    r"(?:19\d{2}|20\d{2})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"  # YYYY-MM-DD
    r"|"
    r"(?:19\d{2}|20\d{2})"  # YYYY
    r")\s*[ _\-\.,;:]\s*"
)
# 序号后缀如 (1)、_副本 等
_TITLE_SUFFIX = re.compile(r"\s*\([0-9]+\)\s*$|_副本\s*$")


def _clean_filename_title(filename: str) -> str:
    """从文件名中提取干净标题：去除路径前缀、文件后缀、年份/日期前缀和序号后缀"""
    t = filename.strip()
    # 防御性路径净化：取 basename，兼容 / 和 \ 两种分隔符
    if "/" in t or "\\" in t:
        t = t.replace("\\", "/").rsplit("/", 1)[-1]
    t = _TITLE_EXT_PATTERN.sub("", t).strip()
    # 去除序号后缀
    t = _TITLE_SUFFIX.sub("", t).strip()
    # 循环去除年份/日期前缀（处理 YYYY_MM_DD_ 等复合前缀）
    while True:
        new_t = _TITLE_YEAR_PREFIX.sub("", t).strip()
        if new_t == t:
            break
        t = new_t
    t = t.strip(" ._-,;:")
    return t if t else filename


async def _find_existing_by_title(db: AsyncSession, clean_title: str) -> Optional[Literature]:
    """按归一化标题查找已存在的文献。
    先精确匹配，失败时用模糊匹配（Jaccard 相似度 >= 0.7）作为回退。
    """
    if not clean_title:
        return None
    norm = normalize_title(clean_title)
    if not norm:
        return None
    result = await db.execute(select(Literature))
    all_lits = list(result.scalars())

    # 1. 精确匹配
    for lit in all_lits:
        if normalize_title(lit.title) == norm:
            return lit

    # 2. 模糊匹配回退
    norm_words = set(norm.split())
    if not norm_words:
        return None
    best_match = None
    best_score = 0.0
    for lit in all_lits:
        nm = normalize_title(lit.title)
        if not nm:
            continue
        words = set(nm.split())
        score = len(norm_words & words) / len(norm_words | words) if (norm_words | words) else 0.0
        if score > best_score:
            best_score = score
            best_match = lit
    if best_score >= 0.7:
        logger.info(f"[_find_existing_by_title] 模糊匹配命中: clean_title='{clean_title}' -> id={best_match.id}, title='{best_match.title}', score={best_score:.2f}")
        return best_match
    return None


async def upload_literature(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
    title: Optional[str] = None,
    doi: Optional[str] = None,
    province: Optional[str] = None,
) -> tuple[Optional[Literature], str]:
    """上传/导入文献文件。

    返回值: (Literature 对象 or None, 状态标记)
        - "new": 新建文献记录
        - "matched": 匹配到已有文献并关联文件
        - "skipped": 匹配到已有文献且已有文件，跳过
        - "error": 处理失败
    """
    logger.info(f"[upload_literature] 开始: filename={filename}, size={len(file_bytes)} bytes, title={title or '(无)'}")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"
    logger.info(f"[upload_literature] 解析扩展名: ext={ext}")

    # 1. 提取干净标题，查找是否已存在该标题的文献
    clean_title = title or _clean_filename_title(filename)
    existing = await _find_existing_by_title(db, clean_title)
    if existing:
        if existing.has_fulltext:
            logger.info(f"[upload_literature] 文献已存在且已有文件: id={existing.id}, title={existing.title}，跳过导入")
            return existing, "skipped"
        else:
            logger.info(f"[upload_literature] 找到已存在文献（无文件）: id={existing.id}, title={existing.title}，关联文件")
            # 保存文件，直接关联到已有文献
            lit = await _save_and_associate(db, existing, file_bytes, filename, ext, doi, province, clean_title)
            return lit, "matched"

    # 2. 始终保存到本地文件系统（确保提取时能找到文件）
    LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    local_filename = f"{uuid.uuid4()}.{ext}"
    local_path = LOCAL_STORAGE_DIR / local_filename
    try:
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"[upload_literature] 本地保存成功: path={local_path}")
    except Exception as e:
        logger.error(f"[upload_literature] 本地保存失败: path={local_path}, error={e}", exc_info=True)
        return None

    # 3. 尝试上传到 MinIO（仅用于分布式/备份场景，失败不阻塞）
    object_name = f"literature/{uuid.uuid4()}.{ext}"
    minio_path = upload_file(file_bytes, object_name, content_type=get_mime_type(ext))
    if minio_path is None:
        logger.warning(f"[upload_literature] MinIO 不可用，仅保存本地副本: filename={filename}")
    else:
        logger.info(f"[upload_literature] MinIO 上传成功: object_name={object_name}")

    # 4. 数据库记录使用本地路径（_download_pdf 会优先匹配本地文件）
    stored_path = str(local_path)

    # 5. 计算文件哈希用于查重
    pdf_hash = compute_pdf_hash(file_bytes)
    logger.info(f"[upload_literature] 哈希计算完成: hash={pdf_hash[:16]}..., filename={filename}")

    # 创建文献记录
    literature = Literature(
        title=clean_title,
        doi=doi,
        province=province,
        file_path=stored_path,
        pdf_hash=pdf_hash,
        has_fulltext=True,
        source_db="upload",
    )
    db.add(literature)
    try:
        await db.commit()
        await db.refresh(literature)
        logger.info(f"[upload_literature] 数据库记录创建成功: id={literature.id}, title={literature.title}")
    except Exception as e:
        logger.error(f"[upload_literature] 数据库提交失败: filename={filename}, error={e}", exc_info=True)
        # 回滚本地文件以避免脏文件残留
        try:
            os.remove(local_path)
            logger.info(f"[upload_literature] 已清理本地文件: {local_path}")
        except Exception as cleanup_err:
            logger.warning(f"[upload_literature] 清理本地文件失败: {local_path}, {cleanup_err}")
        return None, "error"
    return literature, "new"


async def _save_and_associate(
    db: AsyncSession,
    literature: Literature,
    file_bytes: bytes,
    filename: str,
    ext: str,
    doi: Optional[str] = None,
    province: Optional[str] = None,
    clean_title: Optional[str] = None,
) -> Literature:
    """保存文件并关联到已有文献（仅替换文件，不新建记录）。"""
    # 保存文件
    LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    local_filename = f"{uuid.uuid4()}.{ext}"
    local_path = LOCAL_STORAGE_DIR / local_filename
    try:
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"[upload_literature] 关联文件保存成功: path={local_path}")
    except Exception as e:
        logger.error(f"[upload_literature] 关联文件保存失败: path={local_path}, error={e}", exc_info=True)
        return literature

    # 尝试上传 MinIO
    object_name = f"literature/{uuid.uuid4()}.{ext}"
    minio_path = upload_file(file_bytes, object_name, content_type=get_mime_type(ext))
    if minio_path is None:
        logger.warning(f"[upload_literature] 关联文件 MinIO 不可用，仅保存本地副本: filename={filename}")
    else:
        logger.info(f"[upload_literature] 关联文件 MinIO 上传成功: object_name={object_name}")

    stored_path = str(local_path)
    pdf_hash = compute_pdf_hash(file_bytes)

    # 更新已有文献的文件关联
    if clean_title and literature.title != clean_title:
        literature.title = clean_title
    literature.file_path = stored_path
    literature.pdf_hash = pdf_hash
    literature.has_fulltext = True
    if doi:
        literature.doi = doi
    if province:
        literature.province = province
    literature.updated_at = datetime.now(timezone.utc)

    try:
        await db.commit()
        await db.refresh(literature)
        logger.info(f"[upload_literature] 文献文件关联更新成功: id={literature.id}, title={literature.title}, path={stored_path}")
    except Exception as e:
        logger.error(f"[upload_literature] 关联文件数据库提交失败: id={literature.id}, error={e}", exc_info=True)
        try:
            os.remove(local_path)
        except Exception:
            pass
    return literature


async def upload_literature_file(
    db: AsyncSession,
    literature_id: uuid.UUID,
    file_bytes: bytes,
    filename: str,
) -> Optional[Literature]:
    """为已有文献关联上传文件（替换原有文件）。"""
    logger.info(f"[upload_literature_file] 开始: literature_id={literature_id}, filename={filename}, size={len(file_bytes)} bytes")

    literature = await get_literature(db, literature_id)
    if not literature:
        logger.warning(f"[upload_literature_file] 文献不存在: id={literature_id}")
        return None

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"

    # 1. 保存到本地文件系统
    LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    local_filename = f"{uuid.uuid4()}.{ext}"
    local_path = LOCAL_STORAGE_DIR / local_filename
    try:
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"[upload_literature_file] 本地保存成功: path={local_path}")
    except Exception as e:
        logger.error(f"[upload_literature_file] 本地保存失败: path={local_path}, error={e}", exc_info=True)
        return None

    # 2. 尝试上传到 MinIO
    object_name = f"literature/{uuid.uuid4()}.{ext}"
    minio_path = upload_file(file_bytes, object_name, content_type=get_mime_type(ext))
    if minio_path is None:
        logger.warning(f"[upload_literature_file] MinIO 不可用，仅保存本地副本: filename={filename}")
    else:
        logger.info(f"[upload_literature_file] MinIO 上传成功: object_name={object_name}")

    stored_path = str(local_path)
    pdf_hash = compute_pdf_hash(file_bytes)

    # 3. 删除旧文件（如果存在）
    if literature.file_path:
        old_path = Path(literature.file_path)
        if old_path.exists():
            try:
                os.remove(old_path)
                logger.info(f"[upload_literature_file] 已删除旧文件: {old_path}")
            except Exception as e:
                logger.warning(f"[upload_literature_file] 删除旧文件失败: {old_path}, {e}")

    # 4. 更新文献记录
    literature.file_path = stored_path
    literature.pdf_hash = pdf_hash
    literature.has_fulltext = True
    try:
        await db.commit()
        await db.refresh(literature)
        logger.info(f"[upload_literature_file] 文献文件关联成功: id={literature.id}, path={stored_path}")
    except Exception as e:
        logger.error(f"[upload_literature_file] 数据库提交失败: id={literature_id}, error={e}", exc_info=True)
        try:
            os.remove(local_path)
        except Exception:
            pass
        return None
    return literature


# ===== 查重与合并核心函数 =====

async def check_duplicates(
    db: AsyncSession,
    literature_id: Optional[uuid.UUID] = None,
    *,
    title: Optional[str] = None,
    doi: Optional[str] = None,
    authors: Optional[str] = None,
    pdf_hash: Optional[str] = None,
) -> dict:
    """检查重复文献。
    两种模式：
      - 传 literature_id：以该记录为基准查重
      - 传 title/doi/authors/pdf_hash：预检（未落库时）
    返回 {"literature_id": str|None, "duplicates": [...], "total": int}
    """
    if literature_id:
        r = await db.execute(select(Literature).where(Literature.id == literature_id))
        base = r.scalar_one_or_none()
        if not base:
            raise ValueError("文献不存在")
        title = base.title
        doi = base.doi
        authors = base.authors
        pdf_hash = base.pdf_hash

    norm_title = normalize_title(title)
    first_author = _first_author_surname(authors)

    # 候选集：用 DOI / pdf_hash 走索引预筛 + 全表扫标题
    candidates: dict[uuid.UUID, Literature] = {}

    if doi:
        r = await db.execute(select(Literature).where(Literature.doi == doi))
        for m in r.scalars():
            if literature_id and m.id == literature_id:
                continue
            candidates[m.id] = m
    if pdf_hash:
        r = await db.execute(select(Literature).where(Literature.pdf_hash == pdf_hash))
        for m in r.scalars():
            if literature_id and m.id == literature_id:
                continue
            candidates[m.id] = m

    # 标题/标题+作者需逐条归一化比对
    r = await db.execute(select(Literature))
    for m in r.scalars():
        if literature_id and m.id == literature_id:
            continue
        nm = normalize_title(m.title)
        if norm_title and nm == norm_title:
            candidates.setdefault(m.id, m)
        elif norm_title and nm and _title_similarity(norm_title, nm) >= 0.7 \
                and first_author and first_author == _first_author_surname(m.authors):
            candidates.setdefault(m.id, m)

    # 逐候选项判定命中原因
    duplicates = []
    for m in candidates.values():
        reasons: list[str] = []
        values: dict[str, str] = {}
        if doi and m.doi and m.doi.lower() == doi.lower():
            reasons.append("doi")
            values["doi"] = m.doi
        nm = normalize_title(m.title)
        if norm_title and nm == norm_title:
            reasons.append("title")
            values["title"] = norm_title
        elif norm_title and nm and _title_similarity(norm_title, nm) >= 0.7 \
                and first_author == _first_author_surname(m.authors):
            reasons.append("title+authors")
            values["title"] = norm_title
        if pdf_hash and m.pdf_hash == pdf_hash:
            reasons.append("pdf_hash")
            values["pdf_hash"] = pdf_hash
        if reasons:
            duplicates.append({
                "literature": m,
                "match_reasons": reasons,
                "match_values": values,
            })
    return {
        "literature_id": str(literature_id) if literature_id else None,
        "duplicates": duplicates,
        "total": len(duplicates),
    }


async def scan_duplicates(db: AsyncSession) -> dict:
    """全表扫描，使用并查集（union-find）合并重叠的重复对。
    返回 {"groups": [...], "total_groups": N, "total_duplicates": M}
    """
    r = await db.execute(select(Literature))
    all_lits = list(r.scalars())
    parent = {l.id: l.id for l in all_lits}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pair_reasons: dict[tuple, set[str]] = defaultdict(set)

    # 1. DOI / pdf_hash 分组
    by_doi: dict[str, list] = defaultdict(list)
    by_hash: dict[str, list] = defaultdict(list)
    for l in all_lits:
        if l.doi:
            by_doi[l.doi.lower()].append(l)
        if l.pdf_hash:
            by_hash[l.pdf_hash].append(l)
    for grp in by_doi.values():
        for i in range(1, len(grp)):
            union(grp[0].id, grp[i].id)
            pair_reasons[(grp[0].id, grp[i].id)].add("doi")
    for grp in by_hash.values():
        for i in range(1, len(grp)):
            union(grp[0].id, grp[i].id)
            pair_reasons[(grp[0].id, grp[i].id)].add("pdf_hash")

    # 2. 标题/标题+作者 O(n^2)
    norm_map = {l.id: normalize_title(l.title) for l in all_lits}
    for i, a in enumerate(all_lits):
        na = norm_map[a.id]
        if not na:
            continue
        for b in all_lits[i + 1:]:
            nb = norm_map[b.id]
            if not nb:
                continue
            if na == nb:
                union(a.id, b.id)
                pair_reasons[(a.id, b.id)].add("title")
            elif _title_similarity(na, nb) >= 0.7 \
                    and _first_author_surname(a.authors) == _first_author_surname(b.authors):
                union(a.id, b.id)
                pair_reasons[(a.id, b.id)].add("title+authors")

    # 3. 聚合
    groups_map: dict[uuid.UUID, list] = defaultdict(list)
    for l in all_lits:
        groups_map[find(l.id)].append(l)

    groups = []
    for root, members in groups_map.items():
        if len(members) < 2:
            continue
        reasons: set[str] = set()
        for (a, b), rs in pair_reasons.items():
            if find(a) == root:
                reasons |= rs
        representative = min(members, key=lambda x: x.created_at)
        groups.append({
            "literature_ids": [m.id for m in members],
            "match_reasons": sorted(reasons),
            "representative_id": representative.id,
        })
    total_dup = sum(len(g["literature_ids"]) for g in groups)
    return {
        "groups": groups,
        "total_groups": len(groups),
        "total_duplicates": total_dup,
    }


# 合并时可逐字段选择的字段列表
_MERGE_FIELDS = [
    "title", "title_en", "authors", "journal", "pub_year", "doi", "pmid",
    "abstract", "keywords", "region", "province", "publication_types",
    "source_db", "file_path",
]
_ARRAY_FIELDS = {"keywords", "publication_types"}


async def preview_merge(db: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID) -> dict:
    """预览合并：逐字段对比 + 数据点冲突检测"""
    source = await get_literature(db, source_id)
    target = await get_literature(db, target_id)
    if not source or not target:
        raise ValueError("源或目标文献不存在")

    field_comparison = []
    for f in _MERGE_FIELDS:
        sv = getattr(source, f, None)
        tv = getattr(target, f, None)
        field_comparison.append({
            "field": f,
            "source_value": sv,
            "target_value": tv,
            "differs": sv != tv,
        })

    s_dps = (await db.execute(
        select(DataPoint).where(DataPoint.literature_id == source_id))).scalars().all()
    t_dps = (await db.execute(
        select(DataPoint).where(DataPoint.literature_id == target_id))).scalars().all()

    conflicts = []
    total_conflicts = 0
    MAX_CONFLICTS = 50
    for s in s_dps:
        for t in t_dps:
            if _is_dp_conflict(s, t):
                total_conflicts += 1
                if len(conflicts) < MAX_CONFLICTS:
                    key = f"{s.disease}|{s.province}|{s.collection_year}|{s.data_type}"
                    conflicts.append({
                        "source_dp": _dp_to_dict(s),
                        "target_dp": _dp_to_dict(t),
                        "key": key,
                    })

    return {
        "field_comparison": field_comparison,
        "source_data_point_count": len(s_dps),
        "target_data_point_count": len(t_dps),
        "conflicts": conflicts,
        "total_conflicts": total_conflicts,
    }


async def merge_literatures(
    db: AsyncSession,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    field_choices: dict,
    dp_conflict_strategy: str = "keep_both",
) -> dict:
    """执行合并：将 source 合并进 target，删除 source。
    field_choices: {字段名: "source"|"target"|"merge"}
    dp_conflict_strategy: "keep_both"|"prefer_target"|"prefer_source"
    """
    if source_id == target_id:
        raise ValueError("不能与自身合并")
    source = await get_literature(db, source_id)
    target = await get_literature(db, target_id)
    if not source or not target:
        raise ValueError("源或目标文献不存在")

    valid_strategies = {"keep_both", "prefer_target", "prefer_source"}
    if dp_conflict_strategy not in valid_strategies:
        raise ValueError(f"未知冲突策略: {dp_conflict_strategy}")

    # 1. 按 field_choices 更新 target 字段
    for f in _MERGE_FIELDS:
        if f not in field_choices:
            continue
        c = field_choices[f]
        if c == "source":
            setattr(target, f, getattr(source, f))
        elif c == "merge" and f in _ARRAY_FIELDS:
            tgt = list(getattr(target, f) or [])
            src = list(getattr(source, f) or [])
            merged = list(dict.fromkeys(tgt + src))  # 保序去重
            setattr(target, f, merged)
        # c == "target"：保持不变

    # 2. 迁移 DataPoint
    s_dps = (await db.execute(
        select(DataPoint).where(DataPoint.literature_id == source_id))).scalars().all()
    t_dps = (await db.execute(
        select(DataPoint).where(DataPoint.literature_id == target_id))).scalars().all()

    moved = 0
    deleted_conflicts = 0
    for s_dp in s_dps:
        conflict_tgts = [t for t in t_dps if _is_dp_conflict(s_dp, t)]
        if not conflict_tgts:
            s_dp.literature_id = target_id
            moved += 1
            continue
        if dp_conflict_strategy == "keep_both":
            s_dp.literature_id = target_id
            moved += 1
        elif dp_conflict_strategy == "prefer_target":
            await db.delete(s_dp)
            deleted_conflicts += 1
        elif dp_conflict_strategy == "prefer_source":
            for t in conflict_tgts:
                await db.delete(t)
                t_dps.remove(t)
            s_dp.literature_id = target_id
            moved += 1
            deleted_conflicts += len(conflict_tgts)

    # 3. 重算 target 计数
    total_dp = (await db.execute(
        select(func.count(DataPoint.id)).where(DataPoint.literature_id == target_id))).scalar() or 0
    approved = (await db.execute(
        select(func.count(DataPoint.id))
        .where(DataPoint.literature_id == target_id)
        .where(DataPoint.review_status == "approved"))).scalar() or 0
    target.extracted_count = total_dp
    target.approved_count = approved
    target.updated_at = datetime.now(timezone.utc)

    # 4. 文件处理：若选择保留 source 的文件，target.file_path 已被设为 source.file_path
    #    需要清理原 target 文件；删除 source 前置空 file_path 防误删
    source_file_to_delete = None
    if field_choices.get("file_path") != "source":
        source_file_to_delete = source.file_path

    source.file_path = None  # 避免 db.delete 触发文件删除逻辑
    await db.delete(source)
    await db.commit()

    # 删除源文件（仅当与 target 文件不同时）
    if source_file_to_delete and source_file_to_delete != target.file_path:
        p = Path(source_file_to_delete)
        if p.exists():
            try:
                os.remove(p)
            except Exception as e:
                logger.warning(f"删除源文件失败: {e}")
        else:
            delete_file(source_file_to_delete)

    await db.refresh(target)
    return {
        "merged_literature": target,
        "moved_data_points": moved,
        "deleted_conflict_data_points": deleted_conflicts,
        "deleted_source_id": str(source_id),
    }


# ===== 批量操作、题录导入、批量导入服务（从 API 路由下沉）=====

async def batch_delete_literatures(
    db: AsyncSession,
    literature_ids: list[uuid.UUID],
    deleted_by: Optional[uuid.UUID] = None,
) -> int:
    """批量软删除文献：逐篇设置 deleted_at，跳过已在回收站中的记录，返回实际删除数。"""
    if not literature_ids:
        return 0
    deleted = 0
    for lit_id in literature_ids:
        try:
            if await delete_literature(db, lit_id, deleted_by=deleted_by):
                deleted += 1
        except Exception as e:
            logger.warning(f"[文献] 批量软删除失败跳过: id={lit_id}, err={e}")
    return deleted


async def cleanup_empty_literatures(
    db: AsyncSession,
    dry_run: bool = True,
) -> dict:
    """清理既无文档又无摘要的文献记录。

    返回 {"preview_count": int, "deleted_count": int}。
    - dry_run=True: 只统计不删除
    - dry_run=False: 执行删除
    """
    stmt = select(Literature).where(
        and_(
            Literature.file_path.is_(None),
            func.coalesce(Literature.abstract, '') == '',
        )
    )
    result = await db.execute(stmt)
    lits = result.scalars().all()
    preview_count = len(lits)

    if dry_run:
        return {"preview_count": preview_count, "deleted_count": 0}

    if not lits:
        return {"preview_count": 0, "deleted_count": 0}

    ids = [lit.id for lit in lits]
    deleted = await batch_delete_literatures(db, ids)
    return {"preview_count": preview_count, "deleted_count": deleted}


# 中文字符间下划线 → 斜杠（如 麻疹_风疹 → 麻疹/风疹）
_TITLE_UNDERSCORE_TO_SLASH = re.compile(r"([\u4e00-\u9fff])_([\u4e00-\u9fff])")
# 末尾 _作者姓名（2-4 个中文字，如 血清学调查_苏中华 → 血清学调查）
_TITLE_AUTHOR_SUFFIX = re.compile(r"_([\u4e00-\u9fff]{2,4})$")


def _propose_title_fix(raw: str) -> str:
    """对一条疑似文件名来源的标题提出修正建议。

    依次应用：
    1. _clean_filename_title 的已有逻辑（路径、扩展名、年份前缀、序号后缀）
    2. 末尾 `_作者姓名` 删除（如 血清学调查_苏中华 → 血清学调查）
    3. 中文字符间 `_` → `/`（如 麻疹_风疹 → 麻疹/风疹）
    4. 首尾多余空白/标点清理
    """
    t = _clean_filename_title(raw)
    # 循环去除末尾 _作者姓名（处理 标题_作者1_作者2 → 标题）
    while True:
        new_t = _TITLE_AUTHOR_SUFFIX.sub("", t).strip()
        if new_t == t:
            break
        t = new_t
    # 中文字符间下划线 → 斜杠
    t = _TITLE_UNDERSCORE_TO_SLASH.sub(r"\1/\2", t)
    t = t.strip(" ._-,;:")
    return t if t else raw


async def fix_titles(
    db: AsyncSession,
    dry_run: bool = True,
) -> dict:
    """扫描并修正文件名来源的文献标题（年份前缀、中文字符间 `_` 等）。

    返回 {"preview_count": int, "fixed_count": int, "changes": list[dict]}。
    """
    from sqlalchemy import select, update

    stmt = select(Literature).order_by(Literature.created_at)
    result = await db.execute(stmt)
    lits = result.scalars().all()

    changes = []
    for lit in lits:
        proposed = _propose_title_fix(lit.title)
        if proposed == lit.title:
            continue
        changes.append({
            "id": str(lit.id),
            "old_title": lit.title,
            "new_title": proposed,
        })

    if not dry_run and changes:
        for c in changes:
            await db.execute(
                update(Literature)
                .where(Literature.id == c["id"])
                .values(title=c["new_title"])
            )
        await db.commit()

    return {
        "preview_count": len(changes),
        "fixed_count": 0 if dry_run else len(changes),
        "changes": changes,
    }


_TITLE_VERIFY_SYSTEM_PROMPT = (
    "你是一个文献标题提取助手。给定一段学术文献文本内容，提取该文献的真实标题。"
    "只返回标题文本本身，不要附加任何解释、引号或标点。"
    "如果文本中无法确定标题，返回空字符串。"
)

_TITLE_VERIFY_USER_PROMPT = (
    "以下是某篇文献的文本内容片段（开头部分）。请提取该文献的标题：\n\n{text}"
)


async def ai_verify_titles(
    db: AsyncSession,
    limit: int = 50,
    model: Optional[str] = None,
) -> dict:
    """用 LLM 从文献文档内容中提取真实标题，与数据库存储标题比对找出差异。

    只处理有文档文件的文献（file_path 非空），从文档中提取开头文本后调用 LLM
    提取标题，与数据库存储的 title 字段比对。

    返回 {"total": int, "verified": int, "mismatches": list[dict]}。
    """
    from difflib import SequenceMatcher
    from openai import AsyncOpenAI

    from app.core.document_parser import extract_text

    # 查询有文档文件的文献
    stmt = (
        select(Literature)
        .where(
            and_(
                Literature.file_path.isnot(None),
                Literature.deleted_at.is_(None),
            )
        )
        .order_by(Literature.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    lits = result.scalars().all()

    if not lits:
        return {"total": 0, "verified": 0, "mismatches": []}

    # 初始化 LLM 客户端
    effective_model = model or settings.LLM_MODEL
    # 解析 API 配置
    api_key = settings.LLM_API_KEY
    base_url = settings.LLM_BASE_URL
    # 处理 vendor 前缀
    api_model = effective_model
    if ":" in effective_model:
        parts = effective_model.split(":")
        if parts[0] in ("ollama", "deepseek", "qwen", "openai"):
            api_model = ":".join(parts[1:])
    # 处理 Ollama 本地地址
    _url = (base_url or "").rstrip("/")
    if "localhost" in _url or "127.0.0.1" in _url:
        _url = getattr(settings, "OLLAMA_BASE_URL", _url)
    client = AsyncOpenAI(
        api_key=api_key or "ollama",
        base_url=_url or "http://localhost:11434/v1",
        timeout=30,
    )

    mismatches = []
    verified = 0

    for lit in lits:
        # 读取文件内容
        try:
            file_bytes = _read_literature_file_bytes(lit.file_path)
            if not file_bytes:
                continue
            ext = (
                "." + str(lit.file_path).replace("\\", "/").split("/")[-1].split(".")[-1]
            ).lower() if "." in str(lit.file_path).replace("\\", "/").split("/")[-1] else ""
            doc_text = extract_text(file_bytes, ext)
            if not doc_text or len(doc_text.strip()) < 200:
                continue
        except Exception as e:
            logger.debug(f"[AI标题验证] 读取文献 {lit.id} 文件失败: {e}")
            continue

        # 调用 LLM 提取标题
        try:
            resp = await client.chat.completions.create(
                model=api_model,
                messages=[
                    {"role": "system", "content": _TITLE_VERIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": _TITLE_VERIFY_USER_PROMPT.format(
                        text=doc_text[:2000]
                    )},
                ],
                temperature=0.1,
                max_tokens=200,
            )
            ai_title = (resp.choices[0].message.content or "").strip().strip("\"'").strip()
        except Exception as e:
            logger.debug(f"[AI标题验证] LLM 调用失败 {lit.id}: {e}")
            continue

        verified += 1
        if not ai_title:
            continue

        # 比对相似度
        stored = (lit.title or "").strip()
        # 简单归一化后比较
        _norm = lambda s: re.sub(r"\s+", "", s).lower()
        sim = SequenceMatcher(None, _norm(stored), _norm(ai_title)).ratio()
        if sim < 0.6:
            mismatches.append({
                "id": str(lit.id),
                "stored_title": stored,
                "ai_title": ai_title,
                "similarity": round(sim, 4),
            })

    return {
        "total": len(lits),
        "verified": verified,
        "mismatches": mismatches,
    }


def _read_literature_file_bytes(file_path: str) -> Optional[bytes]:
    """读取文献文件字节（兼容本地路径和 MinIO 名称）。"""
    # 策略1: 直接作为本地路径读取
    p = Path(file_path)
    if p.exists() and p.is_file():
        return p.read_bytes()
    # 策略2: 从文件名在本地存储目录查找
    fname = str(file_path).replace("\\", "/").split("/")[-1]
    local = LOCAL_STORAGE_DIR / fname
    if local.exists() and local.is_file():
        return local.read_bytes()
    return None


async def preview_import_references(
    db: AsyncSession,
    ref_text: str,
    fmt: str = "auto",
) -> dict:
    """预览题录导入：解析文本并统计总条数、重复条数、可导入条数，不写入数据库。

    返回 {"total", "skipped", "imported"}。
    """
    text = (ref_text or "").strip()
    if not text:
        raise ValueError("题录文本为空")

    refs = parse_references(text, fmt)
    if not refs:
        raise ValueError("未解析到有效题录（支持 RIS / EndNote / PubMed / WoS / 读秀超星 格式）")

    total = len(refs)
    skipped = 0
    for ref in refs:
        title = (ref.get("title") or "").strip()
        if not title:
            skipped += 1
            continue
        pmid = (ref.get("pmid") or "").strip() or None
        doi = (ref.get("doi") or "").strip() or None
        source_id = pmid or doi
        existing = None
        if source_id:
            if pmid:
                r = await db.execute(select(Literature).where(Literature.pmid == pmid))
                existing = r.scalar_one_or_none()
            if not existing and doi:
                r = await db.execute(select(Literature).where(Literature.doi == doi))
                existing = r.scalar_one_or_none()
        if not existing:
            existing = await _find_existing_by_title(db, title)
        if existing:
            skipped += 1
            continue

    imported = total - skipped
    return {"total": total, "skipped": skipped, "imported": imported}


async def import_references_from_text(
    db: AsyncSession,
    ref_text: str,
    fmt: str = "auto",
) -> dict:
    """解析题录文本并入库（RIS / EndNote(.enw) / PubMed / WoS / 读秀超星）。

    - 格式自动探测（reference_parser.parse_references，fmt 显式指定可跳过探测）
    - source_db 取解析 source，source_id 取 pmid（为空则用 doi）
    - 跳过条件：标题为空；source_id（pmid，兜底 doi）或归一化标题已存在
    - 复用 create_literature 入库
    返回 {"imported", "skipped", "total", "errors"}。
    """
    text = (ref_text or "").strip()
    if not text:
        raise ValueError("题录文本为空")

    refs = parse_references(text, fmt)
    if not refs:
        raise ValueError("未解析到有效题录（支持 RIS / EndNote / PubMed / WoS / 读秀超星 格式）")

    imported = 0
    skipped = 0
    errors: list[dict] = []
    for idx, ref in enumerate(refs):
        title = (ref.get("title") or "").strip()
        if not title:
            skipped += 1
            errors.append({"index": idx, "reason": "标题为空"})
            continue
        try:
            # 来源标识：source_id = pmid（为空则用 doi），用于查重
            pmid = (ref.get("pmid") or "").strip() or None
            doi = (ref.get("doi") or "").strip() or None
            source_id = pmid or doi
            existing = None
            if source_id:
                if pmid:
                    r = await db.execute(select(Literature).where(Literature.pmid == pmid))
                    existing = r.scalar_one_or_none()
                if not existing and doi:
                    r = await db.execute(select(Literature).where(Literature.doi == doi))
                    existing = r.scalar_one_or_none()
            if not existing:
                existing = await _find_existing_by_title(db, title)
            if existing:
                skipped += 1
                logger.info(f"[ImportReferences] 跳过重复文献: title={title}, source_id={source_id}")
                continue

            year_str = (ref.get("year") or "").strip()
            pub_year = int(year_str) if year_str.isdigit() else None
            # 关键词：分号分隔的字符串 → 列表
            kw_str = (ref.get("keywords") or "").strip()
            keywords_list = [k.strip() for k in re.split(r"[;；]", kw_str) if k.strip()] if kw_str else None
            await create_literature(
                db,
                LiteratureCreate(
                    title=title,
                    authors=(ref.get("authors") or "").strip() or None,
                    journal=(ref.get("journal") or "").strip() or None,
                    pub_year=pub_year,
                    doi=doi,
                    pmid=pmid,
                    abstract=(ref.get("abstract") or "").strip() or None,
                    keywords=keywords_list,
                    source_db=(ref.get("source") or "cnki"),
                ),
            )
            imported += 1
        except Exception as e:
            logger.error(f"[ImportReferences] 第 {idx} 条入库失败: {e}", exc_info=True)
            errors.append({"index": idx, "title": title, "reason": str(e)[:200]})

    logger.info(
        f"[ImportReferences] 导入完成: 解析 {len(refs)} 条, "
        f"导入 {imported} 条, 跳过 {skipped} 条, 失败 {len(errors)} 条"
    )
    return {
        "imported": imported,
        "skipped": skipped,
        "total": len(refs),
        "errors": errors[:20],
    }


# 批量导入支持的文件扩展名集合
_BATCH_SUPPORTED_EXTS = {".pdf", ".caj", ".doc", ".docx", ".txt", ".epub", ".pptx", ".xlsx", ".ps", ".wps", ".md"}


async def _batch_import_files_core(
    db: AsyncSession,
    entries: list[dict],
    trigger_extraction_after: bool = True,
    max_size_bytes: Optional[int] = None,
) -> dict:
    """通用批量导入核心：遍历 entries 调用 upload_literature 自动匹配/新建。

    entries: 每个元素为 {"filename": str, "bytes": bytes|None, "read_error": str|None}
      - bytes=None 且 read_error 非空 → 记为读取失败
      - max_size_bytes 给定时，超限文件记为 file_too_large
    新建文献时可选触发 AI 提取。
    返回 {"matched", "imported", "skipped", "failed", "extraction_triggered", "total", "details"}。
    """
    matched = imported = skipped = failed = extraction_triggered = 0
    details: list[dict] = []

    for entry in entries:
        filename = entry["filename"]
        file_bytes = entry.get("bytes")
        read_error = entry.get("read_error")

        if file_bytes is None:
            failed += 1
            details.append({
                "filename": filename, "status": "read_error",
                "error": read_error or "读取文件失败",
            })
            continue

        if max_size_bytes is not None and len(file_bytes) > max_size_bytes:
            failed += 1
            details.append({
                "filename": filename, "status": "file_too_large", "error": "文件超过大小限制",
            })
            continue

        # 判断是否已匹配——upload_literature 内部处理标题匹配与文件关联
        try:
            lit, action = await upload_literature(db, file_bytes, filename)
        except Exception as e:
            logger.error(f"[batch-import] 导入出错: {filename}, error={e}", exc_info=True)
            failed += 1
            details.append({"filename": filename, "status": "import_error", "error": str(e)[:200]})
            continue

        if lit is None:
            failed += 1
            details.append({
                "filename": filename, "status": "import_failed",
                "reason": "upload_literature 返回 None",
            })
            continue

        if action == "new":
            imported += 1
            details.append({
                "filename": filename, "status": "imported",
                "literature_id": str(lit.id), "title": lit.title,
            })
            if trigger_extraction_after:
                try:
                    from app.services.extraction_service import trigger_extraction
                    await trigger_extraction(db, lit.id)
                    extraction_triggered += 1
                except Exception as e:
                    logger.warning(f"[batch-import] 触发提取失败: id={lit.id}, error={e}")
        elif action == "matched":
            matched += 1
            details.append({
                "filename": filename, "status": "matched",
                "literature_id": str(lit.id), "title": lit.title,
            })
        elif action == "skipped":
            skipped += 1
            details.append({
                "filename": filename, "status": "skipped_has_file",
                "literature_id": str(lit.id), "title": lit.title,
            })
        else:
            failed += 1
            details.append({
                "filename": filename, "status": "unknown",
                "literature_id": str(lit.id), "error": f"未知 action: {action}",
            })

    await db.commit()
    return {
        "matched": matched,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "extraction_triggered": extraction_triggered,
        "total": len(entries),
        "details": details[:100],
    }


async def batch_import_files_from_folder(
    db: AsyncSession,
    folder_path: str,
    trigger_extraction_after: bool = True,
) -> dict:
    """从服务器本地文件夹批量导入文件。

    自动匹配已有文献或新建文献记录；支持导入后自动触发 AI 提取。
    文件夹不存在 / 无支持文件时抛出异常，由调用方映射为 400。
    """
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"文件夹不存在: {folder_path}")

    all_files = [
        f for f in sorted(folder.iterdir())
        if f.is_file() and f.suffix.lower() in _BATCH_SUPPORTED_EXTS
    ]
    if not all_files:
        raise ValueError(f"文件夹中未找到支持的文件类型（{', '.join(sorted(_BATCH_SUPPORTED_EXTS))}）")

    entries: list[dict] = []
    for f in all_files:
        try:
            entries.append({"filename": f.name, "bytes": f.read_bytes()})
        except Exception as e:
            logger.error(f"[batch-import] 读取文件失败: {f.name}, error={e}")
            entries.append({"filename": f.name, "bytes": None, "read_error": str(e)})

    return await _batch_import_files_core(db, entries, trigger_extraction_after)


async def batch_import_uploaded_files(
    db: AsyncSession,
    files: list,
    trigger_extraction_after: bool = True,
) -> dict:
    """从浏览器上传的文件批量导入（与文件夹导入共用核心逻辑，但文件来自上传）。

    files: 浏览器上传的 UploadFile 列表；仅保留扩展名受支持且带有文件名的文件。
    单文件超过 settings.MAX_UPLOAD_SIZE 记为 file_too_large。
    """
    all_files = [f for f in files if f.filename]
    valid_files = [
        f for f in all_files
        if Path(f.filename or "").suffix.lower() in _BATCH_SUPPORTED_EXTS
    ]
    if not valid_files:
        raise ValueError("未找到支持的文件类型")

    entries: list[dict] = []
    for f in valid_files:
        filename = f.filename or "unknown"
        try:
            entries.append({"filename": filename, "bytes": await f.read()})
        except Exception as e:
            logger.error(f"[batch-upload-files] 读取文件失败: {filename}, error={e}")
            entries.append({"filename": filename, "bytes": None, "read_error": str(e)})

    return await _batch_import_files_core(
        db, entries, trigger_extraction_after, max_size_bytes=settings.MAX_UPLOAD_SIZE,
    )


# ===== JSON 导出文件导入、导出服务（从 API 路由下沉）=====

async def import_literatures_from_json(
    db: AsyncSession,
    content: bytes,
    skip_duplicates: bool = True,
) -> dict:
    """从 JSON 导出文件导入文献及数据点，自动检测重复文献。

    - 支持从 export?format=json&include_data_points=true 导出的 JSON 文件导入
    - 按 DOI/标题自动检测重复，可选择跳过或更新已有记录的元数据
    - 保留原有审核状态
    返回 {"imported_count", "skipped_count", "data_point_count", "error_count",
          "errors", "imported_titles"}。
    JSON 解析失败 / 未找到文献数据时抛 ValueError（由调用方映射为 400）。
    """
    try:
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {e}")
    except Exception as e:
        raise ValueError(f"文件读取失败: {e}")

    literatures = data.get("literatures", [])
    if not literatures:
        raise ValueError("文件中未找到文献数据")

    imported_count = 0
    skipped_count = 0
    dp_imported_count = 0
    errors: list[dict] = []
    imported_titles: list[str] = []

    for idx, lit_data in enumerate(literatures):
        try:
            title = lit_data.get("title", "").strip()
            if not title:
                errors.append({"index": idx, "reason": "标题为空"})
                continue

            doi = lit_data.get("doi") or None
            if doi:
                doi = doi.strip() or None

            # 重复检测
            existing = None
            if doi:
                result = await db.execute(
                    select(Literature).where(Literature.doi == doi)
                )
                existing = result.scalar_one_or_none()

            if not existing:
                result = await db.execute(
                    select(Literature).where(Literature.title == title)
                )
                existing = result.scalar_one_or_none()

            if existing:
                if skip_duplicates:
                    skipped_count += 1
                    logger.info(f"[Import] 跳过重复文献: title={title}")
                    continue
                # 不跳过则更新已有记录的元数据
                existing.pub_year = lit_data.get("pub_year") or existing.pub_year
                existing.province = lit_data.get("province") or existing.province
                existing.journal = lit_data.get("journal") or existing.journal
                existing.authors = lit_data.get("authors") or existing.authors
                existing.abstract = lit_data.get("abstract") or existing.abstract
                existing.extraction_status = lit_data.get("extraction_status") or existing.extraction_status
                existing.extracted_count = lit_data.get("extracted_count") or existing.extracted_count
                existing.approved_count = lit_data.get("approved_count") or existing.approved_count
                existing.updated_at = datetime.now(timezone.utc)
                await db.flush()
                lit_id = existing.id
                imported_count += 1
                imported_titles.append(title)
            else:
                # 创建新文献记录
                literature = Literature(
                    title=title,
                    title_en=lit_data.get("title_en"),
                    authors=lit_data.get("authors"),
                    journal=lit_data.get("journal"),
                    pub_year=lit_data.get("pub_year"),
                    doi=doi,
                    pmid=lit_data.get("pmid"),
                    abstract=lit_data.get("abstract"),
                    keywords=lit_data.get("keywords") if lit_data.get("keywords") else None,
                    region=lit_data.get("region"),
                    province=lit_data.get("province"),
                    publication_types=lit_data.get("publication_types") if lit_data.get("publication_types") else None,
                    source_db=lit_data.get("source_db") or "import",
                    file_path=None,
                    extraction_status=lit_data.get("extraction_status") or "done",
                    extracted_count=lit_data.get("extracted_count") or 0,
                    approved_count=lit_data.get("approved_count") or 0,
                )
                db.add(literature)
                await db.flush()
                lit_id = literature.id
                imported_count += 1
                imported_titles.append(title)

            # 导入数据点
            data_points = lit_data.get("data_points", [])
            for dp_data in data_points:
                dp = DataPoint(
                    literature_id=lit_id,
                    disease=dp_data.get("disease"),
                    region=dp_data.get("region"),
                    province=dp_data.get("province"),
                    city=dp_data.get("city"),
                    latitude=dp_data.get("latitude"),
                    longitude=dp_data.get("longitude"),
                    age_group=dp_data.get("age_group"),
                    age_min=dp_data.get("age_min"),
                    age_max=dp_data.get("age_max"),
                    sample_size=dp_data.get("sample_size"),
                    data_type=dp_data.get("data_type"),
                    value=dp_data.get("value"),
                    unit=dp_data.get("unit"),
                    ci_lower=dp_data.get("ci_lower"),
                    ci_upper=dp_data.get("ci_upper"),
                    method=dp_data.get("method"),
                    assay=dp_data.get("assay"),
                    population=dp_data.get("population"),
                    collection_year=dp_data.get("collection_year"),
                    source_page=dp_data.get("source_page"),
                    source_context=dp_data.get("source_context"),
                    source_char_start=dp_data.get("source_char_start"),
                    source_char_end=dp_data.get("source_char_end"),
                    is_grounded=dp_data.get("is_grounded", False),
                    estimate_type=dp_data.get("estimate_type") or "primary",
                    confidence=dp_data.get("confidence") or "medium",
                    review_status=dp_data.get("review_status") or "pending",
                )
                db.add(dp)
                dp_imported_count += 1

            await db.flush()

        except Exception as e:
            logger.error(f"[Import] 导入第 {idx} 条文献失败: {e}", exc_info=True)
            errors.append({"index": idx, "title": lit_data.get("title", ""), "reason": str(e)[:200]})
            await db.rollback()

    await db.commit()

    logger.info(
        f"[Import] 导入完成: 文献 {imported_count} 篇, 跳过 {skipped_count} 篇, "
        f"数据点 {dp_imported_count} 个, 失败 {len(errors)} 条"
    )

    return {
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "data_point_count": dp_imported_count,
        "error_count": len(errors),
        "errors": errors[:20],
        "imported_titles": imported_titles[:20],
    }


async def build_literatures_export(
    db: AsyncSession,
    format: str,
    include_data_points: bool,
    keyword: Optional[str] = None,
    disease: Optional[str] = None,
    province: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    journal: Optional[str] = None,
    review_status: Optional[str] = None,
    file_format: Optional[str] = None,
    literature_ids: Optional[str] = None,
) -> dict:
    """导出文献列表（CSV / Excel / JSON），返回字节内容与响应元信息。

    当 literature_ids 提供时，仅导出指定文献及其数据点（忽略筛选条件）。
    返回 {"content": bytes, "media_type": str, "filename": str}。
    不支持的格式抛 ValueError（由调用方映射为 400）。
    """
    if literature_ids:
        # 按指定 ID 查询
        ids = [uuid.UUID(s.strip()) for s in literature_ids.split(",") if s.strip()]
        result = await db.execute(
            select(Literature).where(Literature.id.in_(ids))
        )
        items = list(result.scalars().all())
    else:
        items, _ = await list_literature(
            db, keyword, disease, province, year_start, year_end, journal,
            sort_by=None, sort_order=None, review_status=review_status,
            file_format=file_format,
            page=1, page_size=10000,
        )

    # ── CSV 格式（仅文献元信息）──
    if format == "csv":
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

        return {
            "content": output.getvalue().encode("utf-8-sig"),
            "media_type": "text/csv; charset=utf-8",
            "filename": "literatures.csv",
        }

    # ── JSON 格式（可含数据点，用于 round-trip 导入）──
    if format == "json":
        # 如果需要数据点，批量查询
        dp_map: dict[str, list] = {}
        if include_data_points:
            lit_ids = [lit.id for lit in items]
            if lit_ids:
                dp_result = await db.execute(
                    select(DataPoint).where(DataPoint.literature_id.in_(lit_ids))
                    .order_by(DataPoint.created_at)
                )
                for dp in dp_result.scalars().all():
                    dp_map.setdefault(str(dp.literature_id), []).append({
                        "disease": dp.disease,
                        "region": dp.region,
                        "province": dp.province,
                        "city": dp.city,
                        "latitude": float(dp.latitude) if dp.latitude else None,
                        "longitude": float(dp.longitude) if dp.longitude else None,
                        "age_group": dp.age_group,
                        "age_min": dp.age_min,
                        "age_max": dp.age_max,
                        "sample_size": dp.sample_size,
                        "data_type": dp.data_type,
                        "value": float(dp.value) if dp.value is not None else None,
                        "unit": dp.unit,
                        "ci_lower": float(dp.ci_lower) if dp.ci_lower else None,
                        "ci_upper": float(dp.ci_upper) if dp.ci_upper else None,
                        "method": dp.method,
                        "assay": dp.assay,
                        "population": dp.population,
                        "collection_year": dp.collection_year,
                        "source_page": dp.source_page,
                        "source_context": dp.source_context,
                        "source_char_start": dp.source_char_start,
                        "source_char_end": dp.source_char_end,
                        "is_grounded": bool(dp.is_grounded) if dp.is_grounded else False,
                        "estimate_type": dp.estimate_type or "primary",
                        "confidence": dp.confidence or "medium",
                        "review_status": dp.review_status or "pending",
                    })

        literatures_json = []
        for lit in items:
            entry = {
                "title": lit.title,
                "title_en": lit.title_en,
                "authors": lit.authors,
                "journal": lit.journal,
                "pub_year": lit.pub_year,
                "doi": lit.doi,
                "pmid": lit.pmid,
                "abstract": lit.abstract,
                "keywords": lit.keywords if lit.keywords else [],
                "region": lit.region,
                "province": lit.province,
                "publication_types": lit.publication_types if lit.publication_types else [],
                "source_db": lit.source_db,
                "extraction_status": lit.extraction_status or "pending",
                "extracted_count": lit.extracted_count or 0,
                "approved_count": lit.approved_count or 0,
            }
            if include_data_points:
                entry["data_points"] = dp_map.get(str(lit.id), [])
            literatures_json.append(entry)

        export_data = {
            "export_version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "include_data_points": include_data_points,
            "literature_count": len(literatures_json),
            "data_point_count": sum(len(dps) for dps in dp_map.values()) if include_data_points else 0,
            "literatures": literatures_json,
        }

        content = json.dumps(export_data, ensure_ascii=False, indent=2, default=str)
        return {
            "content": content.encode("utf-8"),
            "media_type": "application/json; charset=utf-8",
            "filename": "literatures_export.json",
        }

    # ── Excel 格式（两个 sheet：文献 + 数据点）──
    if format == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()

        # Sheet 1: 文献列表
        ws1 = wb.active
        ws1.title = "文献列表"
        ws1.append([
            "标题", "英文标题", "作者", "期刊", "出版年份", "DOI", "PMID",
            "省份", "提取状态", "审核通过数", "数据点总数", "创建时间",
        ])
        for lit in items:
            ws1.append([
                lit.title, lit.title_en, lit.authors, lit.journal, lit.pub_year,
                lit.doi, lit.pmid, lit.province, lit.extraction_status,
                lit.approved_count, lit.extracted_count,
                lit.created_at.strftime("%Y-%m-%d %H:%M") if lit.created_at else "",
            ])

        # Sheet 2: 数据点（如果请求包含）
        if include_data_points:
            ws2 = wb.create_sheet("数据点")
            ws2.append([
                "文献标题", "疾病", "省份", "城市", "数据类型", "数值", "单位",
                "CI下限", "CI上限", "样本量", "年龄下限", "年龄上限", "采集年份",
                "人群", "检测方法", "assay", "置信度", "审核状态", "估计类型",
            ])
            lit_ids = [lit.id for lit in items]
            if lit_ids:
                dp_result = await db.execute(
                    select(DataPoint).where(DataPoint.literature_id.in_(lit_ids))
                    .order_by(DataPoint.created_at)
                )
                # 构建标题查找表
                title_map = {str(lit.id): lit.title for lit in items}
                for dp in dp_result.scalars().all():
                    ws2.append([
                        title_map.get(str(dp.literature_id), ""),
                        dp.disease, dp.province, dp.city, dp.data_type,
                        float(dp.value) if dp.value is not None else None,
                        dp.unit,
                        float(dp.ci_lower) if dp.ci_lower else None,
                        float(dp.ci_upper) if dp.ci_upper else None,
                        dp.sample_size, dp.age_min, dp.age_max,
                        dp.collection_year, dp.population, dp.method, dp.assay,
                        dp.confidence, dp.review_status, dp.estimate_type,
                    ])

        output = io.BytesIO()
        wb.save(output)
        return {
            "content": output.getvalue(),
            "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "filename": "literatures_export.xlsx",
        }

    raise ValueError(f"不支持的导出格式: {format}")


# ===== 宿主机文件管理器辅助函数（打开所在文件夹，从 API 路由下沉）=====

def reveal_in_host_file_manager(resolved: str, folder: str) -> None:
    """在宿主机上定位并选中文件（Windows 资源管理器 / macOS Finder / WSL 间调）。

    关键点：
    - Windows 资源管理器的 `/select,<路径>` 必须作为单个参数传入（中间不能有空格），
      否则 explorer 无法正确识别并选中目标文件；此处分三段尝试，任一成功即返回。
    - 后端可能运行在 WSL(Linux) 中：此时可通过 WSL 互操作将 Linux 路径转成 Windows
      路径并调用 explorer.exe，从而在 Windows 宿主机上打开资源管理器并选中该文件。
    - 若当前环境无法打开图形文件管理器（如无头服务器），不抛出未处理异常：
      直接返回，由调用方给出文件路径提示。
    """
    if sys.platform == "win32":
        # 原生 Windows：先 explorer /select 定位选中，失败则用关联程序打开所在目录
        try:
            subprocess.Popen(
                ["explorer", f"/select,{resolved}"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        except Exception as e:  # pragma: no cover
            logger.warning(f"[打开文件夹] explorer 选中失败({e})，回退为打开目录")
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
            return
        except Exception as e:  # pragma: no cover
            logger.warning(f"[打开文件夹] os.startfile 失败({e})，按环境处理")
    elif sys.platform == "darwin":
        # macOS：在 Finder 中显示
        subprocess.Popen(["open", "-R", resolved])
        return
    else:
        # 非 Windows / macOS：可能是 WSL(Linux) 或 Linux 桌面
        win_path = _to_windows_path(resolved)
        logger.info(f"[打开文件夹] WSL分支: sys.platform={sys.platform}, uid={os.getuid()}, resolved={resolved}, win_path={win_path}")
        if win_path:
            # WSL 环境下调用 explorer.exe 打开 Windows 资源管理器并选中文件
            #
            # 关键问题1：后端可能以 root 运行（sudo uvicorn），而 WSL interop 在 root 下
            #   调用 Windows GUI 程序时无法在交互式桌面会话中显示窗口。
            #   解决：若为 root，通过 runuser 切换到 WSL 默认非 root 用户再调用。
            #
            # 关键问题2：uvicorn 进程继承的 WSL_INTEROP socket 可能来自已失效的终端会话，
            #   虽然 socket 文件仍在、explorer.exe 能启动，但窗口不会在当前桌面显示。
            #   解决：优先使用 WSL 主会话的 interop socket（/run/WSL/1_interop 或 2_interop），
            #   该 socket 始终关联当前的 Windows 交互式桌面会话。
            interop_socket = _find_active_wsl_interop()
            logger.info(f"[打开文件夹] interop_socket={interop_socket or '(继承当前)'}")

            runuser = _get_wsl_runuser_prefix()
            username = runuser[2] if runuser else None
            if username:
                cmd = ["runuser", "-u", username, "--", "explorer.exe", f"/select,{win_path}"]
                logger.info(f"[打开文件夹] root用户，使用runuser({username})调用")
            else:
                cmd = ["explorer.exe", f"/select,{win_path}"]
                logger.info(f"[打开文件夹] 非root用户，直接调用explorer.exe")
            try:
                env = os.environ.copy()
                if interop_socket:
                    env["WSL_INTEROP"] = interop_socket
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
                logger.info(f"[打开文件夹] explorer.exe 已启动: pid={proc.pid}")
                return
            except Exception as e:
                logger.warning(f"[打开文件夹] explorer.exe 启动失败({e})")
        try:
            subprocess.Popen(["xdg-open", folder])
            return
        except Exception as e:  # pragma: no cover
            logger.warning(f"[打开文件夹] xdg-open 失败({e})，当前环境无可用文件管理器")


def _to_windows_path(path: str) -> str | None:
    """将 Linux/WSL 路径转换为 Windows 盘符路径（如 /mnt/e/... -> E:\\...）。

    仅在 WSL/Linux 且存在 wslpath 工具时返回 Windows 路径，否则返回 None。
    """
    try:
        out = subprocess.run(
            ["wslpath", "-w", path],
            capture_output=True, text=True, timeout=10,
        )
        win = (out.stdout or "").strip()
        return win if win else None
    except Exception:  # pragma: no cover
        return None


def _get_wsl_runuser_prefix() -> list[str] | None:
    """若当前进程以 root 运行且处于 WSL 环境，返回 runuser 命令前缀以切换到非 root 用户。

    WSL interop 在 root 用户下调用 Windows GUI 程序（如 explorer.exe）时，
    程序虽能启动但无法在交互式桌面会话中显示窗口。
    通过 runuser 切换到 WSL 默认用户即可解决此问题。

    返回示例: ["runuser", "-u", "liux", "--"]
    非 root 或找不到合适用户时返回 None。
    """
    if os.getuid() != 0:
        return None
    # 查找 WSL 默认非 root 用户：优先从 who 命令获取当前登录用户
    try:
        out = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
        for line in (out.stdout or "").strip().splitlines():
            username = line.split()[0] if line.split() else ""
            if username and username != "root":
                return ["runuser", "-u", username, "--"]
    except Exception:  # pragma: no cover
        pass
    # 回退：从 /run/user 目录查找 uid>=1000 的用户
    try:
        import glob
        for uid_dir in sorted(glob.glob("/run/user/*")):
            uid_str = uid_dir.split("/")[-1]
            if uid_str.isdigit() and int(uid_str) >= 1000:
                import pwd
                pw = pwd.getpwuid(int(uid_str))
                if pw and pw.pw_name != "root":
                    return ["runuser", "-u", pw.pw_name, "--"]
    except Exception:  # pragma: no cover
        pass
    return None


def _find_active_wsl_interop() -> str | None:
    """查找当前 WSL 主会话的 interop socket 路径。

    背景：每个 WSL 终端会话都会在 /run/WSL/ 下创建一个 <pid>_interop Unix socket，
    用于 Linux <-> Windows 互操作（调用 explorer.exe 等）。uvicorn 进程继承的
    WSL_INTEROP 可能来自一个已失效或非交互式的终端会话——socket 文件仍在、
    explorer.exe 能启动，但窗口不会在当前 Windows 桌面显示。

    WSL 主会话（PID 2 的 /init 进程）的 interop socket 始终关联当前的
    Windows 交互式桌面会话，因此优先使用它。

    查找顺序：
      1. /run/WSL/1_interop（WSL 主会话的标准符号链接）
      2. /run/WSL/2_interop（PID 2 的 /init 进程对应的 socket）
      3. /run/WSL/ 下数字最小且对应 /init 进程仍存活的 socket
      4. 返回 None（由调用方继承当前进程环境）
    """
    import glob as _glob

    candidates: list[str] = []

    # 优先1：标准符号链接 1_interop -> 2_interop
    link = "/run/WSL/1_interop"
    if os.path.islink(link):
        target = os.path.realpath(link)
        if os.path.exists(target):
            candidates.append(target)

    # 优先2：PID 2 的 /init 对应的 socket
    candidates.append("/run/WSL/2_interop")

    # 优先3：所有 <pid>_interop socket，按 pid 数字升序
    try:
        sockets = []
        for path in _glob.glob("/run/WSL/*_interop"):
            name = os.path.basename(path)
            pid_str = name.replace("_interop", "")
            if pid_str.isdigit():
                sockets.append((int(pid_str), path))
        sockets.sort(key=lambda x: x[0])
        for _, path in sockets:
            if path not in candidates:
                candidates.append(path)
    except Exception:  # pragma: no cover
        pass

    # 返回第一个存在且为 socket 的候选
    for path in candidates:
        try:
            if stat_is_socket(path):
                return path
        except Exception:
            continue
    return None


def stat_is_socket(path: str) -> bool:
    """判断路径是否为一个有效的 Unix socket 文件。"""
    import stat as _stat
    st = os.stat(path)
    return _stat.S_ISSOCK(st.st_mode)


# ===== 回收站后台自动清理 =====

TRASH_CLEANUP_INTERVAL: int = 86400  # 每天检查一次


async def _trash_cleanup_loop():
    """后台循环：每隔 TRASH_CLEANUP_INTERVAL 秒检查并永久删除回收站中超过 TRASH_RETENTION_DAYS 天的文献。"""
    from app.models.base import async_session

    logger.info("[回收站] 后台自动清理任务已启动，每 %d 秒检查一次", TRASH_CLEANUP_INTERVAL)
    while True:
        try:
            async with async_session() as db:
                result = await empty_trash(db, older_than_days=TRASH_RETENTION_DAYS)
                if result["permanently_deleted"] > 0:
                    logger.info(
                        "[回收站] 自动清理: 永久删除 %d 篇超过 %d 天的文献，剩余 %d 篇",
                        result["permanently_deleted"],
                        TRASH_RETENTION_DAYS,
                        result["remaining"],
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[回收站] 自动清理检查异常: %s", e)
        await asyncio.sleep(TRASH_CLEANUP_INTERVAL)

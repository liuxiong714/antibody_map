import hashlib
import logging
import os
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.models.data_point import DataPoint
from app.schemas.literature import LiteratureCreate
from app.core.document_parser import get_mime_type
from app.core.minio_client import upload_file, delete_file

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
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Literature], int]:
    query = select(Literature)
    count_query = select(func.count(Literature.id))

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
        if fmt in FILE_FORMATS:
            fexpr = _build_file_format_expr(Literature.file_path)
            query = query.where(fexpr == fmt)
            count_query = count_query.where(fexpr == fmt)

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
    """从文件名中提取干净标题：去除文件后缀、年份/日期前缀和序号后缀"""
    t = filename.strip()
    t = _TITLE_EXT_PATTERN.sub("", t).strip()
    # 去除序号后缀
    t = _TITLE_SUFFIX.sub("", t).strip()
    # 循环去除年份/日期前缀（处理 YYYY_MM_DD_ 等复合前缀）
    while True:
        new_t = _TITLE_YEAR_PREFIX.sub("", t).strip()
        if new_t == t:
            break
        t = new_t
    t = t.strip(" ._-,;:()")
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

import asyncio
import hashlib
import logging
import re
from pathlib import Path

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint
from app.models.literature import Literature

logger = logging.getLogger("uvicorn")

LOCAL_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "pdfs"


def _is_safe_local_path(file_path: str) -> Path | None:
    """校验文件路径是否在 LOCAL_STORAGE_DIR 范围内，越界返回 None。"""
    try:
        p = Path(file_path).resolve()
        if p.is_relative_to(LOCAL_STORAGE_DIR.resolve()):
            return p
    except (ValueError, OSError):
        pass
    return None


# ===== 查重辅助函数 =====

def compute_pdf_hash(file_bytes: bytes) -> str:
    """计算文件内容的 SHA-256 哈希"""
    return hashlib.sha256(file_bytes).hexdigest()


def normalize_title(title: str | None) -> str:
    """标题归一化：小写 + 替换连字符为空格 + 去标点 + 压缩空格"""
    if not title:
        return ""
    t = title.lower().strip()
    t = re.sub(r"[-–—]", " ", t)  # 连字符统一替换为空格
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _first_author_surname(authors: str | None) -> str:
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


# ===== 回收站管理 =====

TRASH_RETENTION_DAYS: int = 30


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


async def _find_existing_by_title(db: AsyncSession, clean_title: str) -> Literature | None:
    """按归一化标题查找已存在的文献。
    先走 title_norm 生成列索引做精确匹配（避免全表扫描），
    失败时用模糊匹配（Jaccard 相似度 >= 0.7）作为回退。
    """
    if not clean_title:
        return None
    norm = normalize_title(clean_title)
    if not norm:
        return None

    # 1. 精确匹配：title_norm 走索引
    r = await db.execute(
        select(Literature).where(Literature.title_norm == norm)
    )
    lit = r.scalars().first()
    if lit is not None:
        return lit

    # 2. 模糊匹配回退
    r = await db.execute(select(Literature))
    all_lits = list(r.scalars())
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


def _read_literature_file_bytes(file_path: str) -> bytes | None:
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


# ===== 回收站后台自动清理 =====

TRASH_CLEANUP_INTERVAL: int = 86400  # 每天检查一次


async def _trash_cleanup_loop():
    """后台循环：每隔 TRASH_CLEANUP_INTERVAL 秒检查并永久删除回收站中超过 TRASH_RETENTION_DAYS 天的文献。"""
    from app.models.base import async_session
    from app.services.literature.crud import empty_trash

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


# ===== 题录导入日志 =====

async def create_import_log(
    db: AsyncSession,
    file_name: str,
    total_count: int,
    skipped_count: int,
    imported_count: int,
    operator_name: str,
    operator_id: str | None = None,
    fmt: str = "auto",
) -> None:
    """记录题录导入日志"""
    from app.models.reference_import_log import ReferenceImportLog

    log = ReferenceImportLog(
        file_name=file_name,
        total_count=total_count,
        skipped_count=skipped_count,
        imported_count=imported_count,
        operator_name=operator_name,
        operator_id=operator_id,
        fmt=fmt,
    )
    db.add(log)
    await db.commit()


async def list_import_logs(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页查询题录导入日志"""
    from sqlalchemy import func, select

    from app.models.reference_import_log import ReferenceImportLog

    # 总条数
    count_stmt = select(func.count(ReferenceImportLog.id))
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # 分页查询，按时间倒序
    stmt = (
        select(ReferenceImportLog)
        .order_by(ReferenceImportLog.imported_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()

    items = []
    for log in logs:
        items.append({
            "id": str(log.id),
            "file_name": log.file_name,
            "imported_at": log.imported_at.isoformat() if log.imported_at else None,
            "total_count": log.total_count,
            "skipped_count": log.skipped_count,
            "imported_count": log.imported_count,
            "operator_name": log.operator_name,
            "fmt": log.fmt,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}
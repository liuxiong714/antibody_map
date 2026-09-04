"""孤儿文件清理服务：定期/手动清理 backend/data/pdfs 中已不在数据库的残留文件。

背景：
- 文献文件统一存储在 LOCAL_STORAGE_DIR（backend/data/pdfs），文件名形如 {uuid}.pdf；
  数据库 literature.file_path 记录完整路径；提取文本会生成 {文献id}.txt 也放在同目录。
- 某些场景会留下已无数据库引用的孤儿文件，导致目录持续膨胀：
    * 文献被删除/合并后文件未随之一并删除（如合并时保留 source 的 file_path，target
      原文件即成为孤儿；批量删除等路径也可能残留）；
    * 文献关联文件被替换后旧文件删除失败。

策略（安全优先）：
- 清理时先将孤儿文件移动到回收目录（默认 backend/data/pdf_orphan_trash），保留
  ORPHAN_TRASH_RETENTION_DAYS 天后自动物理删除，避免误删不可恢复。
- 触发方式：
    * 后台循环：backend 启动时随 lifespan 启动，按 ORPHAN_CLEANUP_INTERVAL 自动执行；
    * 手动接口：POST /literatures/cleanup-orphan-files（管理员，dry_run 可预览）。
"""

import asyncio
import logging
import re
import shutil
import time
from datetime import timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit import log_audit
from app.core.metrics import record_orphan_scan
from app.core.minio_client import delete_file, get_minio_client
from app.models.base import async_session
from app.models.literature import Literature
from app.services.literature_service import LOCAL_STORAGE_DIR

logger = logging.getLogger("uvicorn")

# 提取文本文件命名模式：{literature_id}.txt
_TXT_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.txt$"
)
# 文件名开头的文献 UUID 前缀（对应 extract_task._download_pdf 策略2/3 的归属判定标准）
_UUID_PREFIX_RE = re.compile(
    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def trash_dir() -> Path:
    """回收目录（默认 backend/data/pdf_orphan_trash，与 pdfs 同级）。"""
    custom = getattr(settings, "ORPHAN_TRASH_DIR", "")
    if custom:
        return Path(custom)
    return LOCAL_STORAGE_DIR.parent / "pdf_orphan_trash"


async def collect_referenced(db: AsyncSession) -> tuple[set[str], set[str]]:
    """收集数据库中的引用信息。

    返回 (引用文件名集合, 存在的文献 id 字符串集合)：
    - 引用文件名：由 literature.file_path 提取的 basename（UUID 文件名，全局唯一）；
    - 文献 id 集合：用于识别 {id}.txt 提取文本是否仍属于存在的文献。
    """
    r = await db.execute(select(Literature.id, Literature.file_path))
    referenced_files: set[str] = set()
    referenced_ids: set[str] = set()
    for lit_id, fp in r.all():
        referenced_ids.add(str(lit_id))
        if fp:
            fp_norm = str(fp).replace("\\", "/")
            referenced_files.add(fp_norm.split("/")[-1])
            referenced_files.add(str(fp))
    return referenced_files, referenced_ids


def _is_referenced(name: str, referenced_files: set[str]) -> bool:
    """判断文件是否被数据库引用（basename 精确命中或出现在任一 file_path 中）。"""
    if name in referenced_files:
        return True
    return any(name in fp for fp in referenced_files)


async def _collect_minio_object_names() -> set[str]:
    """列举 MinIO bucket 中所有对象名（含 basename），用于孤儿判定的反向交叉校验。

    档位三：只用于“扩大保护”（对象仍存在 = 文件仍在使用），绝不用于扩大删除。
    MinIO 不可用/异常时返回空集并告警，保持原有删除判定不变（安全降级）。
    """
    try:
        client = get_minio_client()
        if client is None:
            return set()
        bucket = settings.MINIO_BUCKET_LITERATURE
        names: set[str] = set()
        for obj in client.list_objects(bucket, recursive=True):
            if not obj.object_name:
                continue
            names.add(obj.object_name)
            names.add(str(obj.object_name).replace("\\", "/").split("/")[-1])
        return names
    except Exception as e:
        logger.warning(f"MinIO 对象列举失败，跳过 MinIO 交叉校验（安全降级）: {e}")
        return set()


def _is_protected_by_minio(base: str, minio_names: set[str], referenced_ids: set[str]) -> bool:
    """MinIO 反向交叉校验：文件是否仍在使用（即使 DB basename 未命中）。

    - 同名对象仍存在于 MinIO → 该文件被当作该对象使用中，不得判为孤儿；
    - 文件名以某个仍存在文献的 id 开头（本地被改名，如 {id}_v2.pdf）→
      与 extract_task._download_pdf 策略2/3 的归属判定一致，视为该文献仍在使用的本地副本。
    """
    if base in minio_names:
        return True
    m = _UUID_PREFIX_RE.match(base)
    return bool(m and m.group(1) in referenced_ids)


async def scan_orphan_files(db: AsyncSession) -> dict:
    """扫描目录，返回 {referenced, orphan, cooldown, minio_protected, total}（不执行移动）。

    三层保护（只扩大保护，不扩大删除）：
    1. 冷静期：文件 mtime 距今小于 ORPHAN_COOLING_DAYS（默认 7 天）的一律跳过，
       避免监控/上传/提取中的文件被误判为孤儿；
    2. MinIO 反向交叉校验：同名对象仍存在于 MinIO、或文件名以仍存在文献的 id 开头
       （本地改名场景）→ 视为仍在使用，归入 minio_protected 而非孤儿。
    """
    referenced_files, referenced_ids = await collect_referenced(db)
    referenced: list[str] = []
    orphan: list[str] = []
    cooldown: list[str] = []
    minio_protected: list[str] = []

    if not LOCAL_STORAGE_DIR.exists():
        return {
            "referenced": referenced,
            "orphan": orphan,
            "cooldown": cooldown,
            "minio_protected": minio_protected,
            "total": 0,
        }

    cooling_secs = int(getattr(settings, "ORPHAN_COOLING_DAYS", 7)) * 86400
    now = time.time()
    # 档位三：MinIO 反向交叉校验（对象列举失败时安全降级为空集）
    minio_names = await _collect_minio_object_names()

    for f in LOCAL_STORAGE_DIR.iterdir():
        if not f.is_file():
            continue
        base = f.name
        # 冷静期：近期被创建/修改的文件一律跳过
        try:
            if now - f.stat().st_mtime < cooling_secs:
                cooldown.append(base)
                continue
        except OSError:
            pass
        if _TXT_PATTERN.match(base):
            lit_id = base.rsplit(".", 1)[0]
            if lit_id in referenced_ids:
                referenced.append(base)
            else:
                orphan.append(base)
        elif _is_referenced(base, referenced_files):
            referenced.append(base)
        elif _is_protected_by_minio(base, minio_names, referenced_ids):
            # 档位三：MinIO 反向校验命中 → 仍在使用，仅归入保护，不判孤儿
            minio_protected.append(base)
            referenced.append(base)
        else:
            orphan.append(base)

    record_orphan_scan("local", len(orphan))
    return {
        "referenced": referenced,
        "orphan": orphan,
        "cooldown": cooldown,
        "minio_protected": minio_protected,
        "total": len(referenced) + len(orphan) + len(cooldown),
    }


def _minio_last_modified_ts(obj) -> float | None:
    """取 MinIO 对象的 last_modified 时间戳（秒）；缺失/异常返回 None。"""
    try:
        lm = getattr(obj, "last_modified", None)
        if lm is None:
            return None
        if lm.tzinfo is not None:
            return lm.timestamp()
        return lm.replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


async def scan_minio_orphans(db: AsyncSession) -> dict:
    """扫描 MinIO bucket，返回 {referenced, orphan, cooldown, protected, total, available}（不删除）。

    孤儿对象 = basename 不在 DB 引用集合、文件名不以仍存在文献 id 开头、且已过冷静期。
    - 冷静期：对象 last_modified 距今 < ORPHAN_COOLING_DAYS（默认 7 天）一律跳过，
      避免误删上传中/刚落库的对象；
    - 对称保护：对象名以仍存在文献的 id 开头（与本地档位三一致）→ 归入 protected 而非孤儿；
    - MinIO 不可用/异常 → available=False，安全降级，绝不产生删除。
    """
    referenced_files, referenced_ids = await collect_referenced(db)
    referenced: list[str] = []
    orphan: list[str] = []
    cooldown: list[str] = []
    protected: list[str] = []

    try:
        client = get_minio_client()
        if client is None:
            return {
                "referenced": [], "orphan": [], "cooldown": [], "protected": [],
                "total": 0, "available": False,
            }
        bucket = settings.MINIO_BUCKET_LITERATURE
        cooling_secs = int(getattr(settings, "ORPHAN_COOLING_DAYS", 7)) * 86400
        now = time.time()
        for obj in client.list_objects(bucket, recursive=True):
            object_name = obj.object_name
            if not object_name:
                continue
            base = str(object_name).replace("\\", "/").split("/")[-1]
            # 冷静期：近期上传/修改的对象一律跳过
            ts = _minio_last_modified_ts(obj)
            if ts is not None and now - ts < cooling_secs:
                cooldown.append(object_name)
                continue
            if _is_referenced(base, referenced_files):
                referenced.append(object_name)
            else:
                m = _UUID_PREFIX_RE.match(base)
                if m and m.group(1) in referenced_ids:
                    # 对称保护：对象名以仍存在文献 id 开头
                    protected.append(object_name)
                    referenced.append(object_name)
                else:
                    orphan.append(object_name)
    except Exception as e:
        logger.error(f"MinIO 孤儿扫描失败（安全降级，不删除）: {e}", exc_info=True)
        return {
            "referenced": [], "orphan": [], "cooldown": [], "protected": [],
            "total": 0, "available": False,
        }

    record_orphan_scan("minio", len(orphan))
    return {
        "referenced": referenced,
        "orphan": orphan,
        "cooldown": cooldown,
        "protected": protected,
        "total": len(referenced) + len(orphan) + len(cooldown),
        "available": True,
    }


async def delete_minio_orphan_objects(db: AsyncSession, dry_run: bool = False, operator: str = "system") -> dict:
    """清理 MinIO 孤儿对象（dry_run=True 仅报告不删除）。

    只删除 scan_minio_orphans 判定为孤儿、且 MinIO 可用时的对象；真删前审计留痕。
    注意：MinIO 无回收站概念，删除为物理删除，故默认 dry_run 先行（ORPHAN_AUTO_MOVE 门控）。
    """
    scan = await scan_minio_orphans(db)
    orphan_objects = scan["orphan"]
    scanned = scan["total"]
    available = scan.get("available", True)

    if not available:
        return {
            "scanned": scanned,
            "orphan_count": len(orphan_objects),
            "orphan_files": orphan_objects,
            "cooldown_files": scan["cooldown"],
            "protected_files": scan["protected"],
            "available": False,
            "dry_run": dry_run,
        }

    if dry_run:
        return {
            "scanned": scanned,
            "orphan_count": len(orphan_objects),
            "orphan_files": orphan_objects,
            "cooldown_files": scan["cooldown"],
            "protected_files": scan["protected"],
            "dry_run": True,
        }

    # 删除前审计留痕（审计内部自建会话提交，不影响主事务）
    try:
        await log_audit(
            db,
            "cleanup_minio_orphan_objects",
            username=operator,
            target=settings.MINIO_BUCKET_LITERATURE,
            detail={
                "scanned": scanned,
                "orphan_count": len(orphan_objects),
                "orphan_files": orphan_objects,
            },
        )
    except Exception as e:
        logger.error(f"MinIO 孤儿对象清理审计日志写入失败: {e}")

    deleted = 0
    failed = 0
    for object_name in orphan_objects:
        if delete_file(object_name):
            deleted += 1
        else:
            failed += 1
            logger.warning(f"MinIO 孤儿对象删除失败: {object_name}")

    logger.info(
        f"MinIO 孤儿对象清理完成: 扫描 {scanned}，孤儿 {len(orphan_objects)}，删除 {deleted}，失败 {failed}"
    )
    return {
        "scanned": scanned,
        "orphan_count": len(orphan_objects),
        "deleted": deleted,
        "failed": failed,
        "cooldown_files": scan["cooldown"],
        "protected_files": scan["protected"],
    }


def purge_trash(retention_days: int | None = None) -> dict:
    """物理删除回收目录中超过保留天数的文件，返回删除数量。"""
    retention_days = retention_days or int(getattr(settings, "ORPHAN_TRASH_RETENTION_DAYS", 30))
    trash = trash_dir()
    if not trash.exists():
        return {"purged": 0}
    cutoff = time.time() - retention_days * 86400
    purged = 0
    errors = 0
    for f in trash.iterdir():
        if not f.is_file():
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                purged += 1
        except Exception as e:
            errors += 1
            logger.warning(f"清理回收文件失败: {f}, {e}")
    return {"purged": purged, "errors": errors}


async def cleanup_orphan_files(db: AsyncSession, dry_run: bool = False, operator: str = "system") -> dict:
    """清理孤儿文件：将不在数据库中的文件移入回收目录（dry_run=True 仅预览不移动）。

    返回：
    - dry_run: {scanned, orphan_count, orphan_files, cooldown_files, dry_run: true}
    - 执行:   {scanned, orphan_count, moved, failed, purged, trash_dir, cooldown_files}
    """
    scan = await scan_orphan_files(db)
    orphan_files = scan["orphan"]
    scanned = scan["total"]

    if dry_run:
        return {
            "scanned": scanned,
            "orphan_count": len(orphan_files),
            "orphan_files": orphan_files,
            "cooldown_files": scan["cooldown"],
            "minio_protected_files": scan["minio_protected"],
            "dry_run": True,
        }

    trash = trash_dir()
    try:
        trash.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"创建回收目录失败: {trash}, {e}")
        return {"scanned": scanned, "orphan_count": len(orphan_files), "moved": 0, "failed": len(orphan_files), "cooldown_files": scan["cooldown"]}

    # 移动前审计留痕（审计内部自建会话提交，不影响主事务）
    try:
        await log_audit(
            db,
            "cleanup_orphan_files",
            username=operator,
            target="backend/data/pdfs",
            detail={
                "scanned": scanned,
                "orphan_count": len(orphan_files),
                "orphan_files": orphan_files,
            },
        )
    except Exception as e:
        logger.error(f"孤儿文件清理审计日志写入失败: {e}")

    moved = 0
    failed = 0
    for name in orphan_files:
        src = LOCAL_STORAGE_DIR / name
        dest = trash / name
        # 回收目录同名冲突时加时间戳前缀，避免覆盖
        if dest.exists():
            dest = trash / f"{int(time.time())}_{name}"
        try:
            src.rename(dest)  # 同文件系统内最廉价
        except OSError:
            try:
                shutil.move(str(src), str(dest))
            except Exception as e:
                failed += 1
                logger.warning(f"孤儿文件移动失败: {name}, {e}")
                continue
        except Exception as e:
            failed += 1
            logger.warning(f"孤儿文件移动失败: {name}, {e}")
            continue
        moved += 1

    purged = purge_trash()
    logger.info(
        f"孤儿文件清理完成: 扫描 {scanned}，孤儿 {len(orphan_files)}，"
        f"移入回收 {moved}，失败 {failed}，清理过期回收 {purged.get('purged', 0)}"
    )
    return {
        "scanned": scanned,
        "orphan_count": len(orphan_files),
        "moved": moved,
        "failed": failed,
        "purged": purged["purged"],
        "trash_dir": str(trash),
        "cooldown_files": scan["cooldown"],
        "minio_protected_files": scan["minio_protected"],
    }


async def _cleanup_loop():
    """后台循环：按配置间隔自动清理本地孤儿文件与 MinIO 孤儿对象（backend lifespan 启动）。

    默认仅 dry-run 报告（ORPHAN_AUTO_MOVE=False），显式开启后才真正移动/删除。
    """
    interval = int(getattr(settings, "ORPHAN_CLEANUP_INTERVAL", 86400))
    auto_move = bool(getattr(settings, "ORPHAN_AUTO_MOVE", False))
    logger.info(f"孤儿文件清理后台任务已启动，间隔 {interval}s，真移动={auto_move}")
    while True:
        try:
            await asyncio.sleep(interval)
            async with async_session() as db:
                local_result = await cleanup_orphan_files(db, dry_run=not auto_move, operator="system")
                minio_result = await delete_minio_orphan_objects(db, dry_run=not auto_move, operator="system")
                logger.info(
                    f"后台孤儿清理完成(dry_run={not auto_move}): 本地={local_result} MinIO={minio_result}"
                )
        except asyncio.CancelledError:
            logger.info("孤儿文件清理后台任务已停止")
            break
        except Exception as e:
            logger.error(f"孤儿文件清理循环异常: {e}", exc_info=True)

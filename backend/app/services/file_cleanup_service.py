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
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.base import async_session
from app.models.literature import Literature
from app.services.literature_service import LOCAL_STORAGE_DIR

logger = logging.getLogger("uvicorn")

# 提取文本文件命名模式：{literature_id}.txt
_TXT_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.txt$"
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


async def scan_orphan_files(db: AsyncSession) -> dict:
    """扫描目录，返回 {referenced: [文件名], orphan: [文件名], total: N}（不执行移动）。"""
    referenced_files, referenced_ids = await collect_referenced(db)
    referenced: list[str] = []
    orphan: list[str] = []

    if not LOCAL_STORAGE_DIR.exists():
        return {"referenced": referenced, "orphan": orphan, "total": 0}

    for f in LOCAL_STORAGE_DIR.iterdir():
        if not f.is_file():
            continue
        base = f.name
        if _TXT_PATTERN.match(base):
            lit_id = base.rsplit(".", 1)[0]
            if lit_id in referenced_ids:
                referenced.append(base)
            else:
                orphan.append(base)
        elif _is_referenced(base, referenced_files):
            referenced.append(base)
        else:
            orphan.append(base)

    return {
        "referenced": referenced,
        "orphan": orphan,
        "total": len(referenced) + len(orphan),
    }


def purge_trash(retention_days: Optional[int] = None) -> dict:
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


async def cleanup_orphan_files(db: AsyncSession, dry_run: bool = False) -> dict:
    """清理孤儿文件：将不在数据库中的文件移入回收目录（dry_run=True 仅预览不移动）。

    返回：
    - dry_run: {scanned, orphan_count, orphan_files, dry_run: true}
    - 执行:   {scanned, orphan_count, moved, failed, purged, trash_dir}
    """
    scan = await scan_orphan_files(db)
    orphan_files = scan["orphan"]
    scanned = scan["total"]

    if dry_run:
        return {
            "scanned": scanned,
            "orphan_count": len(orphan_files),
            "orphan_files": orphan_files,
            "dry_run": True,
        }

    trash = trash_dir()
    try:
        trash.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"创建回收目录失败: {trash}, {e}")
        return {"scanned": scanned, "orphan_count": len(orphan_files), "moved": 0, "failed": len(orphan_files)}

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
    }


async def _cleanup_loop():
    """后台循环：按配置间隔自动清理孤儿文件（backend lifespan 启动）。"""
    interval = int(getattr(settings, "ORPHAN_CLEANUP_INTERVAL", 86400))
    logger.info(f"孤儿文件清理后台任务已启动，间隔 {interval}s")
    while True:
        try:
            await asyncio.sleep(interval)
            async with async_session() as db:
                result = await cleanup_orphan_files(db, dry_run=False)
                logger.info(f"后台孤儿文件清理完成: {result}")
        except asyncio.CancelledError:
            logger.info("孤儿文件清理后台任务已停止")
            break
        except Exception as e:
            logger.error(f"孤儿文件清理循环异常: {e}", exc_info=True)

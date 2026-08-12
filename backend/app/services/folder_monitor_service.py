"""文件夹监控服务：定期扫描本地文件夹，自动导入新文件并触发提取。"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitored_folder import MonitoredFolder, MonitoredFile
from app.models.literature import Literature
from app.models.base import async_session
from app.services.literature_service import upload_literature, compute_pdf_hash
from app.services.extraction_service import trigger_extraction
from app.core.document_parser import ALLOWED_EXTS

logger = logging.getLogger("uvicorn")

# 后台循环检查间隔（秒）
LOOP_CHECK_INTERVAL = 60


# ===== CRUD =====

async def list_monitored_folders(db: AsyncSession) -> list[MonitoredFolder]:
    r = await db.execute(select(MonitoredFolder).order_by(MonitoredFolder.created_at.desc()))
    return list(r.scalars().all())


async def get_monitored_folder(db: AsyncSession, folder_id: uuid.UUID) -> Optional[MonitoredFolder]:
    r = await db.execute(select(MonitoredFolder).where(MonitoredFolder.id == folder_id))
    return r.scalar_one_or_none()


async def create_monitored_folder(db: AsyncSession, data: dict) -> MonitoredFolder:
    folder_path = data["folder_path"]
    p = Path(folder_path)
    if not p.exists():
        raise ValueError(f"文件夹不存在: {folder_path}")
    if not p.is_dir():
        raise ValueError(f"路径不是文件夹: {folder_path}")

    folder = MonitoredFolder(**data)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


async def update_monitored_folder(db: AsyncSession, folder_id: uuid.UUID, data: dict) -> Optional[MonitoredFolder]:
    folder = await get_monitored_folder(db, folder_id)
    if not folder:
        return None

    # 如果更新了 folder_path，需要校验
    if "folder_path" in data and data["folder_path"]:
        p = Path(data["folder_path"])
        if not p.exists() or not p.is_dir():
            raise ValueError(f"文件夹路径无效: {data['folder_path']}")

    updatable = [
        "name", "folder_path", "enabled", "scan_interval_seconds", "file_extensions",
        "auto_extract", "extraction_model", "extraction_api_key", "extraction_base_url",
    ]
    for field in updatable:
        if field in data and data[field] is not None:
            setattr(folder, field, data[field])

    folder.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(folder)
    return folder


async def delete_monitored_folder(db: AsyncSession, folder_id: uuid.UUID) -> bool:
    folder = await get_monitored_folder(db, folder_id)
    if not folder:
        return False
    await db.delete(folder)
    await db.commit()
    return True


async def list_monitored_files(db: AsyncSession, folder_id: uuid.UUID) -> list[MonitoredFile]:
    r = await db.execute(
        select(MonitoredFile)
        .where(MonitoredFile.folder_id == folder_id)
        .order_by(MonitoredFile.created_at.desc())
    )
    return list(r.scalars().all())


# ===== 扫描逻辑 =====

def _parse_extensions(ext_str: Optional[str]) -> set[str]:
    """解析扩展名字符串为集合，默认返回 ALLOWED_EXTS。"""
    if not ext_str or not ext_str.strip():
        return ALLOWED_EXTS
    exts = set()
    for e in ext_str.split(","):
        e = e.strip().lower()
        if e:
            if not e.startswith("."):
                e = "." + e
            exts.add(e)
    return exts if exts else ALLOWED_EXTS


async def scan_folder(db: AsyncSession, folder: MonitoredFolder) -> dict:
    """扫描单个文件夹，导入新文件。

    返回 {"scanned": N, "imported": N, "skipped": N, "failed": N}
    """
    folder_path = Path(folder.folder_path)
    if not folder_path.exists() or not folder_path.is_dir():
        folder.status = "error"
        folder.error_message = f"文件夹不存在或不可访问: {folder.folder_path}"
        folder.last_scan_at = datetime.now(timezone.utc)
        await db.commit()
        return {"scanned": 0, "imported": 0, "skipped": 0, "failed": 0}

    folder.status = "scanning"
    folder.error_message = None
    await db.commit()

    extensions = _parse_extensions(folder.file_extensions)

    # 列出匹配的文件
    all_files = []
    for f in folder_path.rglob("*"):
        if f.is_file() and f.suffix.lower() in extensions:
            all_files.append(f)

    # 查询已处理的文件路径
    r = await db.execute(
        select(MonitoredFile.file_path).where(MonitoredFile.folder_id == folder.id)
    )
    processed_paths = {row[0] for row in r.all()}

    new_files = [f for f in all_files if str(f) not in processed_paths]

    imported = 0
    skipped = 0
    failed = 0

    for file_path in new_files:
        try:
            file_bytes = file_path.read_bytes()
            file_hash = compute_pdf_hash(file_bytes)
            file_stat = file_path.stat()

            # 查重：检查是否已有相同 pdf_hash 的文献
            dup_r = await db.execute(
                select(Literature.id).where(Literature.pdf_hash == file_hash).limit(1)
            )
            existing_lit_id = dup_r.scalar_one_or_none()

            if existing_lit_id:
                # 内容重复，跳过
                mf = MonitoredFile(
                    folder_id=folder.id,
                    file_path=str(file_path),
                    file_name=file_path.name,
                    file_hash=file_hash,
                    file_size=file_stat.st_size,
                    file_mtime=datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc),
                    status="skipped_duplicate",
                    literature_id=existing_lit_id,
                    imported_at=datetime.now(timezone.utc),
                )
                db.add(mf)
                skipped += 1
            else:
                # 导入文献
                literature = await upload_literature(
                    db, file_bytes, file_path.name,
                    title=file_path.stem,
                )

                # 触发提取
                if folder.auto_extract:
                    try:
                        await trigger_extraction(
                            db, literature.id,
                            model=folder.extraction_model or None,
                            api_key=folder.extraction_api_key or None,
                            base_url=folder.extraction_base_url or None,
                        )
                    except Exception as ext_err:
                        logger.warning(f"文件夹监控: 文件 {file_path.name} 提取触发失败: {ext_err}")

                mf = MonitoredFile(
                    folder_id=folder.id,
                    file_path=str(file_path),
                    file_name=file_path.name,
                    file_hash=file_hash,
                    file_size=file_stat.st_size,
                    file_mtime=datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc),
                    status="imported",
                    literature_id=literature.id,
                    imported_at=datetime.now(timezone.utc),
                )
                db.add(mf)
                imported += 1

        except Exception as e:
            logger.error(f"文件夹监控: 导入文件 {file_path} 失败: {e}", exc_info=True)
            mf = MonitoredFile(
                folder_id=folder.id,
                file_path=str(file_path),
                file_name=file_path.name,
                status="failed",
                error_message=str(e)[:500],
            )
            db.add(mf)
            failed += 1

    # 更新文件夹状态
    folder.last_scan_at = datetime.now(timezone.utc)
    folder.last_scan_new_count = len(new_files)
    folder.total_imported_count += imported
    folder.status = "idle"
    await db.commit()

    logger.info(
        f"文件夹监控: 扫描 '{folder.name}' 完成 — "
        f"发现 {len(new_files)} 个新文件, 导入 {imported}, 跳过 {skipped}, 失败 {failed}"
    )
    return {
        "scanned": len(new_files),
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
    }


# ===== 后台监控循环 =====

async def _folder_monitor_loop():
    """后台循环：定期检查所有启用的文件夹，到时间则触发扫描。"""
    logger.info("文件夹监控后台任务已启动")
    while True:
        try:
            await asyncio.sleep(LOOP_CHECK_INTERVAL)
            async with async_session() as db:
                r = await db.execute(
                    select(MonitoredFolder).where(MonitoredFolder.enabled.is_(True))
                )
                folders = list(r.scalars().all())

                now = datetime.now(timezone.utc)
                for folder in folders:
                    # 判断是否到扫描时间
                    if folder.last_scan_at:
                        elapsed = (now - folder.last_scan_at).total_seconds()
                        if elapsed < folder.scan_interval_seconds:
                            continue

                    try:
                        await scan_folder(db, folder)
                    except Exception as e:
                        logger.error(f"文件夹监控: 扫描 '{folder.name}' 异常: {e}", exc_info=True)
                        folder.status = "error"
                        folder.error_message = str(e)[:500]
                        folder.last_scan_at = datetime.now(timezone.utc)
                        await db.commit()

        except asyncio.CancelledError:
            logger.info("文件夹监控后台任务已停止")
            break
        except Exception as e:
            logger.error(f"文件夹监控循环异常: {e}", exc_info=True)

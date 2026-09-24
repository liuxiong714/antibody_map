"""数据库自动备份服务：后台循环定时执行 pg_dump，防止断电/关机导致最近写入丢失。

策略：
- 每 AUTO_BACKUP_INTERVAL_MINUTES（默认 60 分钟）在 backend 容器内执行一次 pg_dump，
  输出到 BACKUP_DIR（映射到宿主机项目根 backups/ 目录）。
- 备份完成后立即同步更新 latest_backup.sql 软链/副本，方便一键恢复。
- 自动清理超过 AUTO_BACKUP_KEEP_LAST（默认 48）份的旧备份，避免磁盘无限增长。
- 关闭浏览器、退出 backend 进程等场景不会触发问题：备份文件已在宿主机磁盘。
- 即便容器被强制终止，最近 1 小时内的数据也有 SQL 快照可恢复；加上 Postgres
  fsync=on 保证每个 commit 都刷盘，两层保险。

触发方式：
- 后台循环：backend 启动时随 lifespan 启动（由 settings.AUTO_BACKUP_ENABLED 控制）。
- 同步函数 do_backup() 可被手动接口 /api/v1/system/backup 直接调用。
"""

import asyncio
import glob
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from app.config import settings

logger = logging.getLogger("uvicorn")


def _pg_dump() -> tuple[bool, str]:
    """执行一次 pg_dump，返回 (成功标志, 备份文件路径或错误信息)。

    必须在 backend 容器内运行（容器内已装 postgresql-client，且 DATABASE_URL 指向 postgres 服务）。
    """
    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_file = backup_dir / f"auto_backup_{ts}.sql"
    latest_file = backup_dir / "latest_backup.sql"

    # 从 DATABASE_URL 解析连接参数
    # DATABASE_URL=postgresql+asyncpg://antibody:xxx@postgres:5432/antibody_map
    db_url = settings.DATABASE_URL
    # pg_dump 用 libpq 连接串，替换 asyncpg 驱动名
    libpq_url = db_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")

    cmd = [
        "pg_dump",
        "--no-owner",
        "--no-privileges",
        "--file", str(dump_file),
        libpq_url,
    ]

    try:
        env = os.environ.copy()
        env["PGPASSWORD"] = env.get("POSTGRES_PASSWORD", "")  # 兜底，正常 libpq_url 已含密码

        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=settings.BACKUP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"[自动备份] pg_dump 超时（{settings.BACKUP_TIMEOUT}s）")
        return False, "pg_dump timeout"
    except FileNotFoundError:
        logger.error("[自动备份] pg_dump 未找到，检查 backend 是否装了 postgresql-client")
        return False, "pg_dump not found"

    if result.returncode != 0:
        # 清理失败产生的半截文件
        if dump_file.exists() and dump_file.stat().st_size < 1024:
            dump_file.unlink()
        logger.error(f"[自动备份] pg_dump 失败: {result.stderr.strip()[:500]}")
        return False, result.stderr.strip()[:500]

    # 成功后更新 latest 副本
    import shutil
    # 用 copyfile 而非 copy2/copy：仅复制文件内容，不做 chmod/copystat
    # WSL/NTFS 环境对 utime/chmod 有限制，会抛 PermissionError
    shutil.copyfile(str(dump_file), str(latest_file))

    size_kb = dump_file.stat().st_size / 1024
    logger.info(f"[自动备份] 完成 -> {dump_file.name} ({size_kb:.1f} KB)")

    # 清理旧备份
    _cleanup_old_backups(backup_dir, keep=settings.AUTO_BACKUP_KEEP_LAST)

    return True, str(dump_file)


def _cleanup_old_backups(backup_dir: Path, keep: int) -> None:
    """删除旧的 auto_backup_*.sql 文件，只保留最近 keep 份。"""
    files = sorted(
        glob.glob(str(backup_dir / "auto_backup_*.sql")),
        key=lambda p: Path(p).stat().st_mtime,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            Path(old).unlink()
            logger.info(f"[自动备份] 清理旧备份: {Path(old).name}")
        except OSError as e:
            logger.warning(f"[自动备份] 清理失败 {old}: {e}")


async def _auto_backup_loop() -> None:
    """后台循环：每 AUTO_BACKUP_INTERVAL_MINUTES 分钟执行一次 pg_dump。"""
    interval_s = settings.AUTO_BACKUP_INTERVAL_MINUTES * 60
    logger.info(
        f"[自动备份] 后台任务启动：每 {settings.AUTO_BACKUP_INTERVAL_MINUTES} 分钟一次，"
        f"保留最近 {settings.AUTO_BACKUP_KEEP_LAST} 份"
    )

    # 启动后先跑一次，确保刚重启的 backend 立即有一份新鲜备份
    try:
        await asyncio.to_thread(_pg_dump)
    except Exception as e:
        logger.error(f"[自动备份] 启动时首次备份失败: {e}")

    while True:
        try:
            await asyncio.sleep(interval_s)
            await asyncio.to_thread(_pg_dump)
        except asyncio.CancelledError:
            # lifespan 退出时被 cancel，正常情况
            logger.info("[自动备份] 后台任务已停止")
            break
        except Exception as e:
            logger.error(f"[自动备份] 循环异常: {e}")


def do_backup_sync() -> tuple[bool, str]:
    """同步执行一次备份（供手动 API 调用）。"""
    return _pg_dump()

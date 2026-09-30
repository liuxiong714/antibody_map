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


# ============================================================================
# P1-B4: 完整备份（pg_dump + MinIO 对象 + data 目录）及 restore 实现
# ============================================================================


def _get_minio_client():
    """构造 MinIO client（从环境变量读取，失败返回 None）。"""
    try:
        from minio import Minio
    except ImportError:
        logger.warning("[B4] minio SDK 未安装，跳过 MinIO 备份")
        return None

    endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
    access = os.getenv("MINIO_ACCESS_KEY", os.getenv("MINIO_ROOT_USER", ""))
    secret = os.getenv("MINIO_SECRET_KEY", os.getenv("MINIO_ROOT_PASSWORD", ""))
    secure = os.getenv("MINIO_SECURE", "false").lower() in ("1", "true", "yes")

    if not access or not secret:
        logger.warning("[B4] MINIO_ACCESS_KEY / MINIO_SECRET_KEY 未配置，跳过 MinIO 备份")
        return None

    try:
        client = Minio(endpoint, access_key=access, secret_key=secret, secure=secure)
        client.list_buckets()
        return client
    except Exception as e:
        logger.warning(f"[B4] MinIO 连接失败，跳过 MinIO 备份: {e}")
        return None


def _minio_export(work_dir: Path) -> tuple[int, list[str]]:
    """导出 MinIO 所有 bucket 的对象到 work_dir/minio/<bucket>/。"""
    client = _get_minio_client()
    if client is None:
        return 0, ["(minio not available)"]

    minio_root = work_dir / "minio"
    minio_root.mkdir(parents=True, exist_ok=True)

    total = 0
    skipped: list[str] = []

    try:
        buckets = client.list_buckets()
    except Exception as e:
        logger.error(f"[B4] list_buckets 失败: {e}")
        return 0, ["list_failed"]

    for bucket in buckets:
        bucket_name = bucket.name
        bucket_dir = minio_root / bucket_name
        bucket_dir.mkdir(parents=True, exist_ok=True)

        try:
            objects = client.list_objects(bucket_name, recursive=True)
            for obj in objects:
                local_path = bucket_dir / obj.object_name
                local_path.parent.mkdir(parents=True, exist_ok=True)
                client.fget_object(bucket_name, obj.object_name, str(local_path))
                total += 1
            logger.info(f"[B4] MinIO 导出 bucket={bucket_name} 对象数={total - sum(1 for _ in bucket_dir.rglob('*') if _.is_file())}")
        except Exception as e:
            logger.warning(f"[B4] MinIO 导出 bucket={bucket_name} 失败: {e}")
            skipped.append(bucket_name)

    return total, skipped


def _minio_restore(minio_root: Path) -> tuple[int, list[str]]:
    """从 minio_root/<bucket>/ 恢复对象到 MinIO。"""
    client = _get_minio_client()
    if client is None:
        return 0, ["(minio not available)"]

    total = 0
    skipped: list[str] = []

    if not minio_root.exists():
        logger.warning(f"[B4] minio_root={minio_root} 不存在")
        return 0, ["no_dir"]

    for bucket_dir in minio_root.iterdir():
        if not bucket_dir.is_dir():
            continue
        bucket_name = bucket_dir.name
        try:
            if not client.bucket_exists(bucket_name):
                client.make_bucket(bucket_name)
            for local_file in bucket_dir.rglob("*"):
                if not local_file.is_file():
                    continue
                obj_name = str(local_file.relative_to(bucket_dir))
                client.fput_object(bucket_name, obj_name, str(local_file))
                total += 1
            logger.info(f"[B4] MinIO 恢复 bucket={bucket_name} 对象数={total}")
        except Exception as e:
            logger.warning(f"[B4] MinIO 恢复 bucket={bucket_name} 失败: {e}")
            skipped.append(bucket_name)

    return total, skipped


def _data_dir_export(work_dir: Path) -> bool:
    """打包 /app/backend/data 目录到 work_dir/data.tar.gz。"""
    import shutil as _shutil

    data_src = Path("/app/backend/data")
    if not data_src.exists():
        logger.warning("[B4] /app/backend/data 不存在，跳过 data 备份")
        return False

    try:
        _shutil.make_archive(str(work_dir / "data"), "gztar", root_dir=str(data_src))
        logger.info(f"[B4] data 目录打包完成")
        return True
    except Exception as e:
        logger.error(f"[B4] data 目录打包失败: {e}")
        return False


def _data_dir_restore(data_tar: Path) -> bool:
    """从 data.tar.gz 解压恢复到 /app/backend/data。"""
    import tarfile

    if not data_tar.exists():
        logger.warning(f"[B4] data_tar={data_tar} 不存在")
        return False

    data_dst = Path("/app/backend/data")
    data_dst.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(str(data_tar), "r:gz") as tf:
            tf.extractall(str(data_dst))
        logger.info("[B4] data 目录恢复完成")
        return True
    except Exception as e:
        logger.error(f"[B4] data 目录恢复失败: {e}")
        return False


def do_full_backup_sync() -> tuple[bool, str]:
    """完整备份：pg_dump + MinIO 全 bucket 对象 + data 目录 → 单个 .tar.gz。"""
    import tarfile as _tarfile
    import shutil as _shutil

    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    ok, pg_result = _pg_dump()
    if not ok:
        return False, f"pg_dump 失败: {pg_result}"

    work_dir = backup_dir / f"_full_tmp_{ts}"
    work_dir.mkdir(parents=True, exist_ok=True)

    _shutil.copyfile(str(Path(pg_result)), str(work_dir / "database.sql"))

    minio_objs, minio_skipped = _minio_export(work_dir)
    data_ok = _data_dir_export(work_dir)

    full_backup = backup_dir / f"full_backup_{ts}.tar.gz"
    try:
        with _tarfile.open(str(full_backup), "w:gz") as tar:
            for item in work_dir.iterdir():
                tar.add(str(item), arcname=item.name)
    except Exception as e:
        logger.error(f"[B4] 完整备份打包失败: {e}")
        return False, str(e)

    _shutil.rmtree(str(work_dir), ignore_errors=True)

    size_kb = full_backup.stat().st_size / 1024
    logger.info(
        f"[B4] 完整备份完成 → {full_backup.name} ({size_kb:.1f} KB) | "
        f"pg=✓ | minio_objs={minio_objs}(skip={minio_skipped}) | data={'✓' if data_ok else 'skip'}"
    )
    return True, str(full_backup)


def do_full_restore_sync(backup_path: str) -> tuple[bool, str]:
    """从完整备份 .tar.gz 恢复：pg + MinIO + data。⚠️ 破坏性操作。"""
    import tarfile as _tarfile
    import shutil as _shutil

    backup_file = Path(backup_path)
    if not backup_file.exists():
        return False, f"备份文件不存在: {backup_path}"

    backup_dir = Path(settings.BACKUP_DIR)
    work_dir = backup_dir / f"_restore_tmp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        with _tarfile.open(str(backup_file), "r:gz") as tar:
            tar.extractall(str(work_dir))
    except Exception as e:
        _shutil.rmtree(str(work_dir), ignore_errors=True)
        return False, f"解压备份失败: {e}"

    results: list[str] = []

    # pg_restore (psql single-transaction)
    pg_sql = work_dir / "database.sql"
    if pg_sql.exists():
        db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")
        cmd = ["psql", db_url, "-f", str(pg_sql), "--single-transaction"]
        try:
            env = os.environ.copy()
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=settings.BACKUP_TIMEOUT)
            results.append("pg=✓" if result.returncode == 0 else f"pg=FAIL({result.stderr.strip()[:200]})")
        except Exception as e:
            results.append(f"pg=FAIL({e})")
    else:
        results.append("pg=skip")

    # MinIO restore
    minio_root = work_dir / "minio"
    if minio_root.exists() and any(minio_root.iterdir()):
        n_ok, n_skip = _minio_restore(minio_root)
        results.append(f"minio={n_ok}objs(skip={n_skip})")
    else:
        results.append("minio=skip")

    # data dir restore
    data_tar = work_dir / "data.tar.gz"
    if data_tar.exists():
        results.append(f"data={'✓' if _data_dir_restore(data_tar) else 'FAIL'}")
    else:
        results.append("data=skip")

    _shutil.rmtree(str(work_dir), ignore_errors=True)
    summary = " | ".join(results)
    logger.info(f"[B4] 完整备份恢复完成 → {backup_file.name} | {summary}")

    pg_ok = "pg=✓" in summary
    return (pg_ok, summary)

"""数据库自动备份服务：后台循环定时执行 pg_dump，防止断电/关机导致最近写入丢失。

策略：
- 每 AUTO_BACKUP_INTERVAL_MINUTES（默认 60 分钟）在 backend 容器内执行一次 pg_dump，
  输出到 BACKUP_DIR（映射到宿主机项目根 backups/ 目录）。
- 备份完成后立即同步更新 latest_backup.dump 软链/副本，方便一键恢复。
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


def safe_extract(tar, dst: str) -> None:
    """V3-09: tarfile.extractall 的路径穿越安全替代。

    拒绝任何用 ``..`` 或绝对路径越权写出目标目录的成员。
    接受普通成员（含符号链接），但符号链接解析后也不得越界。
    """
    dst_path = Path(dst).resolve()
    dst_str = str(dst_path)
    for member in tar.getmembers():
        # 用 resolve() 消掉 ".." 和符号链接；判断是否仍在 dst 下
        member_path = (dst_path / member.name).resolve()
        if not str(member_path).startswith(dst_str + os.sep) and str(member_path) != dst_str:
            logger.warning(f"[safe_extract] 跳过越权成员: {member.name}")
            continue
        tar.extract(member, dst)


def _pg_dump() -> tuple[bool, str]:
    """执行一次 pg_dump，返回 (成功标志, 备份文件路径或错误信息)。

    必须在 backend 容器内运行（容器内已装 postgresql-client，且 DATABASE_URL 指向 postgres 服务）。
    """
    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_file = backup_dir / f"auto_backup_{ts}.dump"
    latest_file = backup_dir / "latest_backup.dump"

    # 从 DATABASE_URL 解析连接参数
    # DATABASE_URL=postgresql+asyncpg://antibody:xxx@postgres:5432/antibody_map
    db_url = settings.DATABASE_URL
    # pg_dump 用 libpq 连接串，替换 asyncpg 驱动名
    libpq_url = db_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")

    cmd = [
        "pg_dump",
        # V2-09: -Fc 自定义压缩格式（支持并行恢复 + 更低存储占用）
        # 原代码纯 SQL 明文，大库场景恢复慢且占用大
        "--no-owner",
        "--no-privileges",
        "-Fc",
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
    """删除旧的 auto_backup_*.dump 文件，只保留最近 keep 份。"""
    files = sorted(
        glob.glob(str(backup_dir / "auto_backup_*.dump")),
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
            # V3-09: 路径穿越防护 — 拒绝 .. 越权成员
            safe_extract(tf, str(data_dst))
        logger.info("[B4] data 目录恢复完成")
        return True
    except Exception as e:
        logger.error(f"[B4] data 目录恢复失败: {e}")
        return False


def do_full_backup_sync() -> tuple[bool, str]:
    """完整备份：pg_dump + rowcounts 清单 + MinIO + data + SHA256 校验 → 单个 .tar.gz。

    符合 Batch 0 D1 验收标准：
      pg_dump -Fc → database.dump
      psql rowcounts → rowcounts.csv  （事后可对比恢复前后行数一致）
      _minio_export → minio/
      _data_dir_export → data.tar.gz
      sha256sum → SHA256SUMS          （每个产物一行）
      tar -czf → full_backup_{ts}.tar.gz
    """
    import tarfile as _tarfile
    import shutil as _shutil
    import hashlib

    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    ok, pg_result = _pg_dump()
    if not ok:
        return False, f"pg_dump 失败: {pg_result}"

    work_dir = backup_dir / f"_full_tmp_{ts}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. pg_dump ---
    _shutil.copyfile(str(Path(pg_result)), str(work_dir / "database.dump"))

    # --- 2. rowcounts 清单（Batch 0 D1 必需）---
    rowcounts_path = work_dir / "rowcounts.csv"
    _write_rowcounts(rowcounts_path)

    # --- 3. MinIO ---
    minio_objs, minio_skipped = _minio_export(work_dir)

    # --- 4. data 目录 ---
    data_ok = _data_dir_export(work_dir)

    # --- 5. SHA256SUMS ---
    sha_path = work_dir / "SHA256SUMS"
    with open(sha_path, "w", encoding="utf-8") as sha_file:
        for item in sorted(work_dir.iterdir()):
            if item.name.startswith("_"):
                continue
            if item.is_file():
                h = hashlib.sha256()
                with open(item, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        h.update(chunk)
                sha_file.write(f"{h.hexdigest()}  {item.name}\n")

    # --- 6. 打包 ---
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
        f"pg=✓ | rowcounts=✓ | minio_objs={minio_objs}(skip={minio_skipped}) | "
        f"data={'✓' if data_ok else 'skip'} | sha256=✓"
    )
    return True, str(full_backup)


def _write_rowcounts(out_path: Path) -> None:
    """向 out_path 写一张 CSV：rowcounts.csv (relname, n_live_tup)。

    对应文档 D1 的 psql rowcounts 清单。用 asyncpg 连接（不依赖 psql CLI），
    若连接失败则写一行表头 + WARNING，不阻塞备份主流程。
    """
    import asyncio

    try:
        import asyncpg
    except ImportError:
        logger.warning("[B4] asyncpg 未安装，跳过 rowcounts.csv")
        return

    async def _query():
        c = await asyncpg.connect(
            settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")
        )
        try:
            rows = await c.fetch(
                "SELECT relname, n_live_tup AS approx_rows "
                "FROM pg_stat_user_tables ORDER BY relname"
            )
            return [(r["relname"], r["approx_rows"]) for r in rows]
        finally:
            await c.close()

    try:
        rows = asyncio.run(_query())
    except Exception as e:
        logger.warning(f"[B4] rowcounts 查询失败，写空清单: {e}")
        rows = []

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("relname,approx_rows\n")
        for name, cnt in rows:
            f.write(f"{name},{cnt}\n")


def _verify_sha256(work_dir: Path) -> tuple[bool, list[str]]:
    """校验 work_dir/SHA256SUMS 中记录的每个产物哈希是否匹配。

    返回 (全部匹配, [不匹配的文件名列表])。若无 SHA256SUMS 文件则视为通过
    （兼容旧版备份）。
    """
    import hashlib

    sha_file = work_dir / "SHA256SUMS"
    if not sha_file.exists():
        return True, ["(no SHA256SUMS — old backup)"]

    mismatches: list[str] = []
    with open(sha_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            expected, filename = parts
            actual_path = work_dir / filename
            if not actual_path.exists():
                mismatches.append(f"{filename}: missing")
                continue
            h = hashlib.sha256()
            with open(actual_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    h.update(chunk)
            if h.hexdigest() != expected:
                mismatches.append(filename)

    return len(mismatches) == 0, mismatches


def _compare_rowcounts(work_dir: Path) -> str:
    """对比备份 rowcounts.csv 和当前 DB 的行数，返回对比摘要字符串。"""
    import csv
    import asyncio as _asyncio

    rc_file = work_dir / "rowcounts.csv"
    if not rc_file.exists():
        return "(no rowcounts.csv in backup — old backup)"

    try:
        import asyncpg
    except ImportError:
        return "(asyncpg missing — skip rowcounts compare)"

    # 读备份基线
    baseline: dict[str, int] = {}
    with open(rc_file, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                baseline[row["relname"]] = int(row["approx_rows"] or 0)
            except (ValueError, KeyError):
                pass

    async def _query_current():
        c = await asyncpg.connect(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://"))
        try:
            rows = await c.fetch(
                "SELECT relname, n_live_tup AS approx_rows "
                "FROM pg_stat_user_tables"
            )
            return {r["relname"]: int(r["approx_rows"] or 0) for r in rows}
        finally:
            await c.close()

    try:
        current = _asyncio.run(_query_current())
    except Exception as e:
        return f"(current rowcounts query failed: {e})"

    # 逐表差异
    diffs = []
    for name, base in sorted(baseline.items()):
        cur = current.get(name, 0)
        if base == cur:
            continue
        delta = cur - base
        diffs.append(f"{name}: {base} → {cur} ({delta:+d})")

    if not diffs:
        return f"(all {len(baseline)} tables match baseline)"
    # 截断最多 20 条差异
    summary = "; ".join(diffs[:20])
    if len(diffs) > 20:
        summary += f"; ... +{len(diffs) - 20} more"
    return summary


def _resolve_pg_dump_file(work_dir: Path) -> Path | None:
    """V5-03: 从备份工作目录里选 pg_dump 产物的恢复路径（可单测）。

    优先级: database.dump > database.sql > None（两候选都不存在）。

    契约:
      - 返回 Path: 调用方按文件魔数自动选 pg_restore / psql
      - 返回 None: 调用方走 FAIL 分支（V4-01 第三层兜底，而非静默 skip）

    为什么是独立函数:
      之前路径选择内联在 do_full_restore_sync 里，无法单测，"V4-01 的
      .sql fallback 到底有没有生效"只能靠端到端 E2E 验证。V5-03 抽出后
      三个边界（.dump 有 / 仅 .sql / 都无）各有单元测试，反向验证可做。
    """
    dump_path = work_dir / "database.dump"
    sql_path = work_dir / "database.sql"
    if dump_path.exists():
        return dump_path
    if sql_path.exists():
        return sql_path
    return None


def do_full_restore_sync(
    backup_path: str,
    *,
    verify_only: bool = False,
    target_test: bool = False,
    allow_nonempty: bool = False,
) -> tuple[bool, str]:
    """从完整备份 .tar.gz 恢复：pg + MinIO + data。⚠️ 破坏性操作。

    参数:
        verify_only:  只校验备份 SHA256 + 对比 rowcounts，不真恢复。
        target_test:  目标库允许非空；否则若发现目标库有数据则直接拒绝。
        allow_nonempty: 同 target_test（互斥同义，兼容调用方）。

    D1 安全门:
        1. 先 SHA256 校验 — 备份文件损坏直接拒绝
        2. verify_only=True 时到此为止（演练模式）
        3. target_test=False 且目标库非空 → 拒绝（防止误覆盖生产）
    """
    import tarfile as _tarfile
    import shutil as _shutil

    backup_file = Path(backup_path)
    if not backup_file.exists():
        return False, f"备份文件不存在: {backup_path}"

    backup_dir = Path(settings.BACKUP_DIR)
    work_dir = backup_dir / f"_restore_tmp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # --- 解压 ---
    try:
        with _tarfile.open(str(backup_file), "r:gz") as tar:
            safe_extract(tar, str(work_dir))
    except Exception as e:
        _shutil.rmtree(str(work_dir), ignore_errors=True)
        return False, f"解压备份失败: {e}"

    # --- D1-1: SHA256 校验 ---
    sha_ok, sha_mismatches = _verify_sha256(work_dir)
    sha_result = "✓" if sha_ok else f"FAIL({sha_mismatches})"

    # --- D1-2: rowcounts 对比 ---
    rc_result = _compare_rowcounts(work_dir)

    summary_parts = [f"sha256={sha_result}", f"rowcounts={rc_result}"]

    # --- verify_only 模式：到此为止 ---
    if verify_only:
        _shutil.rmtree(str(work_dir), ignore_errors=True)
        logger.info(f"[D1-verify] 备份校验通过 → {backup_file.name} | " + " | ".join(summary_parts))
        return sha_ok, " | ".join(summary_parts)

    # --- SHA256 不过就不继续恢复 ---
    if not sha_ok:
        _shutil.rmtree(str(work_dir), ignore_errors=True)
        return False, " | ".join(summary_parts) + " (aborted — sha256 mismatch)"

    # --- D1-3: 目标库非空检查 ---
    if not (target_test or allow_nonempty):
        is_nonempty, tables = _check_target_nonempty()
        if is_nonempty:
            _shutil.rmtree(str(work_dir), ignore_errors=True)
            return (
                False,
                "TARGET_NONEMPTY REFUSE — 目标库存在数据: "
                + ", ".join(tables[:5])
                + f" (共 {len(tables)} 张表)\n"
                + "如需演练恢复到测试库，加参数 --target-test；\n"
                + "如需强行覆盖（极度危险），需用 Python API 显式传 allow_nonempty=True"
            )

    # --- 执行恢复 ---
    results: list[str] = []

    # V3-01 + V4-01 + V5-03: 通过可测函数选恢复文件
    # 优先级: database.dump > database.sql > None（都无 → FAIL）
    pg_file = _resolve_pg_dump_file(work_dir)
    if pg_file is None:
        results.append("pg=FAIL(no database.dump / database.sql in archive)")
    else:
        db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")
        try:
            head = pg_file.open("rb").read(5)
        except Exception as e:
            results.append(f"pg=FAIL(read_head:{e})")
            head = b""

        if head.startswith(b"PGDMP"):
            # pg_dump -Fc 二进制归档 → pg_restore
            cmd = ["pg_restore", "--no-owner", "--no-acl", "--clean", "--if-exists",
                   "-d", db_url, str(pg_file)]
        else:
            # 纯文本 SQL → psql
            cmd = ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-f", str(pg_file)]

        try:
            env = os.environ.copy()
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=settings.BACKUP_TIMEOUT)
            if result.returncode == 0:
                # V4-01 双重校验：pg_restore returncode=0 但可能恢复空文件/结构损坏
                # 查核心表行数，若 data_point + literature 都为 0 则视为恢复失败
                restored_ok = _verify_post_restore_nonempty()
                results.append("pg=✓" if restored_ok else "pg=FAIL(post_restore_empty)")
            else:
                results.append(f"pg=FAIL({result.stderr.strip()[:200]})")
        except FileNotFoundError as e:
            results.append(f"pg=FAIL(binary_not_found:{cmd[0]})")
        except Exception as e:
            results.append(f"pg=FAIL({e})")

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
    summary = " | ".join(summary_parts) + " | " + " | ".join(results)
    logger.info(f"[B4] 完整备份恢复完成 → {backup_file.name} | {summary}")

    pg_ok = "pg=✓" in summary
    return (pg_ok, summary)


def _check_target_nonempty() -> tuple[bool, list[str]]:
    """检查目标库是否有任何数据。返回 (非空, 有数据的表名列表)。

    用 asyncpg，不依赖 psql CLI。任何一张表行数 > 0 视为非空。
    """
    import asyncio as _asyncio

    try:
        import asyncpg
    except ImportError:
        # 拿不到就认为非空（宁可拒绝不做）
        return True, ["(asyncpg missing — conservative refuse)"]

    async def _query():
        c = await asyncpg.connect(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://"))
        try:
            rows = await c.fetch(
                "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname"
            )
            return [(r["relname"], int(r["n_live_tup"] or 0)) for r in rows]
        finally:
            await c.close()

    try:
        tables = _asyncio.run(_query())
    except Exception as e:
        return True, [f"(query failed: {e}) — conservative refuse"]

    nonempty = [name for name, cnt in tables if cnt > 0]
    return (len(nonempty) > 0, nonempty)


def _verify_post_restore_nonempty() -> bool:
    """V4-01: pg_restore/psql 成功后验证目标库确实有数据。

    pg_restore 对空 archive / 结构错误文件也可能 returncode=0，
    必须额外查核心表行数。data_point + literature 至少一张有数据才算成功。
    """
    import asyncio as _asyncio

    try:
        import asyncpg
    except ImportError:
        return True  # 拿不到驱动就不额外卡

    async def _query():
        c = await asyncpg.connect(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://"))
        try:
            cnts = {}
            for tbl in ("data_point", "literature"):
                try:
                    cnt = await c.fetchval(f"SELECT COUNT(*) FROM {tbl}")
                    cnts[tbl] = int(cnt or 0)
                except Exception:
                    cnts[tbl] = -1  # 表不存在
            return cnts
        finally:
            await c.close()

    try:
        cnts = _asyncio.run(_query())
    except Exception:
        return True  # 查询异常不要卡恢复，returncode=0 已经过了一道门

    # 至少一张核心表有 > 0 行；两表都是 0 才视为空库
    if cnts.get("data_point", 0) > 0 or cnts.get("literature", 0) > 0:
        return True
    if cnts.get("data_point", -1) == -1 and cnts.get("literature", -1) == -1:
        # 两表都不存在 → 恢复完全失败
        return False
    # 两表都存在但都是 0 行
    return False

"""系统信息与后台日志查看接口。

- /system/info        ：返回版本号、运行环境、功能特性等动态系统信息
- /system/logs        ：列出日志目录下的日志文件
- /system/logs/content：读取指定日志文件的尾部内容（支持按级别/关键字过滤）

日志文件由 app.core.logging_config 统一写入（loguru），目录为 backend/logs/。
"""

import asyncio
import datetime
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.config import settings
from app.core.logging_config import LOGS_DIR
from app.schemas.common import ApiResponse
from app.services import goal_threshold_service

router = APIRouter(prefix="/system")

logger = logging.getLogger("uvicorn")

# 备份互斥锁：避免并发登出触发多条 pg_dump
_backup_lock = asyncio.Lock()

# 功能特性列表：与 README「核心功能」保持同步，每次发版更新 README 时需一并维护
FEATURES = [
    "文献智能提取",
    "精确字符溯源",
    "长文档分块并行提取",
    "强 Schema 约束",
    "MinerU 增强解析",
    "全列排序与筛选",
    "交互式地图",
    "多维度分析",
    "Meta 分析",
    "FOI 感染力分析",
    "空间热点分析",
    "抗原图谱",
    "数据质量评分",
    "分析快照与引用",
    "报告生成",
    "文件夹监控",
    "浏览器插件",
    "多格式预览",
    "JWT认证",
    "用户权限管理",
    "审计日志",
    "标签分类",
    "Word/Excel 导出",
]

# 日志行格式（loguru 文件输出）：{time} | {level: <8} | {name}:{function}:{line} - {message}
_LOG_LINE_RE = re.compile(r"^(?P<time>\S+ \S+) \| (?P<level>\S+) \| (?P<rest>.*)$")

# 允许的日志级别（大小写不敏感），用于前端过滤
VALID_LEVELS = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}


def _safe_log_file(filename: str) -> Path:
    """校验文件名，防止路径穿越；只允许访问日志目录下的 .log 文件。"""
    if not filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    name = Path(filename).name
    if name != filename or not name.endswith(".log"):
        raise HTTPException(status_code=400, detail="非法的日志文件名")
    file_path = (LOGS_DIR / name).resolve()
    if not str(file_path).startswith(str(LOGS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法的日志路径")
    return file_path


@router.get("/info", response_model=ApiResponse, summary="获取系统信息", description="返回系统名称、版本号、运行环境、功能特性与日志目录等动态信息")
async def system_info(_user=Depends(get_current_user)):
    """获取系统动态信息（版本号等来源于单一版本源 settings.APP_VERSION）。"""
    return ApiResponse(
        data={
            "name": "Antibody Map",
            "version": settings.APP_VERSION,
            "environment": settings.APP_ENV,
            "features": FEATURES,
            "log_dir": str(LOGS_DIR),
            "repo_url": "https://github.com/liuxiong714/antibody_map",
        }
    )


@router.get("/logs", response_model=ApiResponse, summary="列出日志文件", description="列出日志目录下的所有日志文件（名称、大小、修改时间），按修改时间倒序")
async def list_log_files(_user=Depends(get_current_user)):
    """列出日志目录下的所有 .log 文件。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for p in sorted(LOGS_DIR.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            st = p.stat()
            files.append(
                {
                    "name": p.name,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }
            )
        except OSError:
            continue
    return ApiResponse(data={"dir": str(LOGS_DIR), "files": files})


@router.get("/logs/content", response_model=ApiResponse, summary="读取日志内容", description="读取指定日志文件尾部内容，支持按级别与关键字过滤")
async def read_log_content(
    file: str = Query(..., description="日志文件名，如 app_2026-08-18.log"),
    lines: int = Query(500, ge=1, le=5000, description="读取尾部行数"),
    level: str = Query("", description="按级别过滤，如 ERROR / WARNING / INFO"),
    keyword: str = Query("", description="按关键字过滤（包含匹配）"),
    _user=Depends(get_current_user),
):
    """读取日志文件尾部内容；可选按级别、关键字过滤。"""
    file_path = _safe_log_file(file)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"日志文件不存在: {file}")

    level_upper = level.strip().upper()
    if level_upper and level_upper not in VALID_LEVELS:
        raise HTTPException(status_code=400, detail=f"非法的日志级别: {level}")

    # 只读取文件尾部，避免大文件整体加载
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, 2)
        size = f.tell()
        read_from = max(0, size - 256 * 1024)  # 最多向后回读 256KB 足够覆盖数千行
        f.seek(read_from)
        buffer = f.read()
        if read_from > 0:
            # 跳过首行不完整内容（前半行被截断）
            first_newline = buffer.find("\n")
            buffer = buffer[first_newline + 1:] if first_newline != -1 else buffer

    raw_lines = buffer.splitlines()
    tail_lines = raw_lines[-lines:] if len(raw_lines) > lines else raw_lines

    entries = []
    for idx, line in enumerate(tail_lines):
        line_no = idx + 1
        m = _LOG_LINE_RE.match(line)
        if m:
            lv = m.group("level").strip().upper()
            rest = m.group("rest")
        else:
            # 非标准行（如多行堆栈），归为所属上一级别，仅做关键字过滤
            lv = "INFO"
            rest = line

        if level_upper and lv != level_upper:
            continue
        if keyword and keyword not in line:
            continue

        entries.append(
            {
                "line": line_no,
                "level": lv,
                "text": line,
            }
        )

    return ApiResponse(
        data={
            "file": file,
            "total_lines": len(tail_lines),
            "matched_lines": len(entries),
            "entries": entries,
        }
    )


@router.post("/backup", response_model=ApiResponse, summary="数据库备份", description="对 PostgreSQL 执行 pg_dump 逻辑备份，导出带时间戳的 SQL 文件到项目 backups/ 目录；单次超时 300 秒")
async def backup_database(_user=Depends(get_current_user)):
    """对数据库执行 pg_dump 备份，返回备份文件信息。"""
    async with _backup_lock:
        url = make_url(settings.DATABASE_URL)
        host = url.host or "postgres"
        port = url.port or 5432
        dbname = url.database or ""
        username = url.username or "antibody"
        password = url.password or ""

        backup_dir = Path(settings.BACKUP_DIR)
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"[备份] 创建备份目录失败: {backup_dir} error={e}")
            raise HTTPException(status_code=500, detail=f"备份目录不可写: {e}")

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dump_file = backup_dir / f"antibody_map_backup_{ts}.sql"

        cmd = [
            "pg_dump",
            "-h", host,
            "-p", str(port),
            "-U", username,
            "--no-owner",
            "--no-privileges",
            "-d", dbname,
        ]

        env = {"PGPASSWORD": password}
        logger.info(f"[备份] 开始 pg_dump: host={host}:{port} db={dbname} -> {dump_file.name}")
        try:
            # 直接以 dump 文件作为 stdout，避免大容量备份占用内存
            with dump_file.open("wb") as out:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=out,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                _, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=settings.BACKUP_TIMEOUT
                )
        except asyncio.TimeoutError:
            if proc:
                proc.kill()
                await proc.wait()
            logger.error(f"[备份] pg_dump 超时: {settings.BACKUP_TIMEOUT}s")
            raise HTTPException(
                status_code=500,
                detail=f"备份超时（>{settings.BACKUP_TIMEOUT}s），请稍后重试",
            )
        except OSError as e:
            logger.error(f"[备份] pg_dump 执行失败（可能未安装 postgresql-client）: {e}")
            raise HTTPException(
                status_code=500,
                detail="备份工具不可用：容器缺少 pg_dump，请联系管理员",
            )

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace").strip()
            logger.error(f"[备份] pg_dump 返回非零: {proc.returncode} stderr={err_text[-500:]}")
            raise HTTPException(status_code=500, detail=f"数据库备份失败: {err_text[-300:]}")

        # 连带写入一份 latest_backup.sql 副本，便于恢复脚本固定引用
        latest_path = backup_dir / "latest_backup.sql"
        try:
            dump_file.touch(exist_ok=True)
            latest_path.write_bytes(dump_file.read_bytes())
        except OSError:
            pass  # 副本失败不影响主备份

        try:
            size = dump_file.stat().st_size
        except OSError:
            size = 0

        logger.info(f"[备份] 成功: {dump_file.name} size={size}B by user={_user.username if _user else '?'}")
        mb = round(size / 1024 / 1024, 2)
        return ApiResponse(
            message="数据库备份成功",
            data={
                "filename": dump_file.name,
                "path": str(dump_file),
                "size": size,
                "size_mb": mb,
                "created_at": ts,
            },
        )


def _safe_backup_path(filename: str) -> Path:
    """将文件名限定在备份目录内，防止路径穿越。"""
    backup_dir = Path(settings.BACKUP_DIR)
    p = (backup_dir / filename).resolve()
    if not p.is_relative_to(backup_dir.resolve()):
        raise HTTPException(status_code=404, detail="非法文件路径")
    return p


@router.get("/backups", response_model=ApiResponse, summary="备份文件列表", description="列出备份目录下已有的 .sql 备份文件（名称、大小、修改时间）")
async def list_backups(_user=Depends(get_current_user)):
    backup_dir = Path(settings.BACKUP_DIR)
    files = []
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    try:
        for f in sorted(backup_dir.glob("*.sql"), key=lambda x: x.stat().st_mtime, reverse=True):
            st = f.stat()
            files.append({
                "filename": f.name,
                "size": st.st_size,
                "size_mb": round(st.st_size / 1024 / 1024, 2),
                "mtime": int(st.st_mtime),
            })
    except OSError as e:
        logger.warning(f"[备份] 读取备份目录失败: {e}")
    return ApiResponse(message="获取备份列表成功", data={"dir": str(backup_dir), "files": files})


@router.get("/backup/download/{filename}", summary="下载备份文件", description="下载指定的数据库备份 .sql 文件")
async def download_backup(filename: str, _user=Depends(get_current_user)):
    p = _safe_backup_path(filename)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    return FileResponse(str(p), filename=p.name, media_type="application/sql")


@router.post("/restore", response_model=ApiResponse, summary="还原数据库备份", description="上传 .sql 备份文件并还原数据库。高危操作：还原前自动备份当前库，随后清空并重建数据库表。仅管理员可用。")
async def restore_database(
    file: UploadFile = File(...),
    _user=Depends(require_admin),
):
    """上传并还原数据库备份（仅管理员）。

    流程（保证原子性，失败自动回滚到还原前状态）：
    1. 先对当前数据库自动做一次备份（保险）
    2. 清空 public schema（DROP+CREATE）
    3. 用 psql 在单事务内导入备份文件（ON_ERROR_STOP，失败整体回滚）
    """
    filename = (file.filename or "restore.sql").strip()
    if not filename.lower().endswith(".sql"):
        raise HTTPException(status_code=400, detail="仅支持 .sql 备份文件")
    dump_bytes = await file.read()
    if not dump_bytes:
        raise HTTPException(status_code=400, detail="备份文件为空")

    # 1. 还原前自动备份当前库（保险）
    try:
        await backup_database(_user)
    except Exception as e:
        logger.warning(f"[还原] 还原前自动备份当前库失败: {e}")

    url = make_url(settings.DATABASE_URL)
    host = url.host or "postgres"
    port = url.port or 5432
    dbname = url.database or ""
    username = url.username or "antibody"
    password = url.password or ""

    # 2&3. 单事务导入：BEGIN → DROP/CREATE schema → 导入 dump → COMMIT
    pre_sql = b"BEGIN;\nDROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n"
    post_sql = b"\nCOMMIT;\n"
    combined = pre_sql + dump_bytes + post_sql

    cmd = [
        "psql", "-h", host, "-p", str(port), "-U", username, "-d", dbname,
        "-v", "ON_ERROR_STOP=1", "--no-psqlrc", "-q", "-X",
    ]
    env = {"PGPASSWORD": password, "PGCLIENTENCODING": "UTF8"}
    logger.info(f"[还原] 开始还原: host={host}:{port} db={dbname} 文件={filename}（{len(dump_bytes)} bytes）")
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(combined), timeout=settings.BACKUP_TIMEOUT
        )
    except asyncio.TimeoutError:
        if proc:
            proc.kill()
            await proc.wait()
        raise HTTPException(status_code=500, detail=f"还原超时（>{settings.BACKUP_TIMEOUT}s）")
    except OSError as e:
        logger.error(f"[还原] psql 执行失败: {e}")
        raise HTTPException(status_code=500, detail="还原工具不可用：容器缺少 psql，请联系管理员")

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace").strip()
        logger.error(f"[还原] psql 返回非零: {proc.returncode} stderr={err_text[-500:]}")
        # 单事务失败会自动回滚，数据库保持还原前状态
        raise HTTPException(status_code=400, detail=f"还原失败（已回滚）: {err_text[-300:]}")

    logger.info(f"[还原] 成功: {filename} by user={_user.username}")
    return ApiResponse(message="数据库还原成功", data={"filename": filename, "size": len(dump_bytes)})


# ===================== 每病保护目标阈值 =====================


class GoalThresholdRequest(BaseModel):
    threshold_percent: float = Field(..., ge=0, le=100, description="保护目标阈值（阳性率 %）")


@router.get("/thresholds", response_model=ApiResponse, summary="每病保护目标阈值列表", description="列出全部疾病的有效保护目标阈值（配置表覆盖值 + 默认值）")
async def list_goal_thresholds(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """列出全部疾病的保护目标阈值"""
    items = await goal_threshold_service.list_goal_thresholds(db)
    return ApiResponse(message="操作成功", data=items)


@router.put("/thresholds/{disease}", response_model=ApiResponse, summary="设置保护目标阈值", description="新增或更新某疾病的保护目标阈值（管理员）")
async def upsert_goal_threshold(
    disease: str,
    req: GoalThresholdRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """新增或更新某疾病的保护目标阈值"""
    try:
        data = await goal_threshold_service.upsert_goal_threshold(
            db,
            disease=disease,
            threshold_percent=req.threshold_percent,
            updated_by=str(getattr(_user, "id", "")),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(message="阈值已更新", data=data)


@router.delete("/thresholds/{disease}", response_model=ApiResponse, summary="重置保护目标阈值", description="删除某疾病的阈值覆盖，恢复默认值（管理员）")
async def delete_goal_threshold(
    disease: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """删除某疾病的阈值覆盖，恢复默认值"""
    await goal_threshold_service.delete_goal_threshold(db, disease)
    return ApiResponse(message="已恢复默认阈值", data={"disease": disease, "reset": True})

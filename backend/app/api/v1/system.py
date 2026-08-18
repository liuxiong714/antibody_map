"""系统信息与后台日志查看接口。

- /system/info        ：返回版本号、运行环境、功能特性等动态系统信息
- /system/logs        ：列出日志目录下的日志文件
- /system/logs/content：读取指定日志文件的尾部内容（支持按级别/关键字过滤）

日志文件由 app.core.logging_config 统一写入（loguru），目录为 backend/logs/。
"""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.config import settings
from app.core.logging_config import LOGS_DIR
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/system")

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

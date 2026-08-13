import asyncio
import logging
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models.base import engine
from app.api.v1.router import router as api_v1_router
from app.core.logging_config import setup_logging, logger

# 初始化统一结构化日志
setup_logging(level="DEBUG" if settings.APP_DEBUG else "INFO")


def _run_migrations():
    """通过子进程执行 Alembic 迁移，避免事件循环冲突。

    在 uvicorn 的事件循环中通过 asyncio.to_thread 调用 alembic 时，
    alembic env.py 内部的 asyncio.run() 会与主事件循环产生冲突导致死锁。
    使用 subprocess 在独立进程中运行可彻底避免此问题。
    """
    backend_dir = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        logger.error(f"Alembic migration failed (exit {result.returncode}):\n{result.stderr}")
        raise RuntimeError(f"Database migration failed: {result.stderr}")
    logger.info("Database migrations applied successfully")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时运行数据库迁移（在独立线程中执行，避免 asyncio.run() 嵌套）
    try:
        await asyncio.to_thread(_run_migrations)
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        raise

    # 启动文件夹监控后台任务
    from app.services.folder_monitor_service import _folder_monitor_loop
    monitor_task = asyncio.create_task(_folder_monitor_loop())

    yield

    # 停止文件夹监控后台任务
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

    await engine.dispose()


app = FastAPI(
    title="Antibody Map API",
    description="""血清抗体流行病学数据可视化平台 - 后端API

## 功能模块

- **认证管理**：用户登录、注册、Token刷新、密码修改、用户管理
- **文献管理**：文献上传、检索、全文搜索、查重、合并、标签管理
- **数据提取**：AI驱动的文献数据提取、提取历史管理、Word报告导出
- **地图数据**：全国抗体数据地理分布、趋势分析、区域对比、年龄分层
- **数据分析**：趋势分析、区域对比、年龄分层统计、高级图表（箱线图/热力图/雷达图）
- **报告生成**：数据报告自动生成与下载
- **文件夹监控**：文献自动导入文件夹监控
- **系统设置**：远程模型配置、系统信息查看

## 认证方式

所有受保护API使用 **Bearer Token** 认证，在请求头中添加：
```
Authorization: Bearer <your_access_token>
```

访问令牌有效期2小时，刷新令牌有效期7天。使用 `/auth/refresh` 端点获取新令牌。
""",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    contact={
        "name": "免疫规划实验室",
        "url": "https://github.com/liuxiong714/antibody_map",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "auth", "description": "用户认证、登录、Token管理、用户CRUD"},
        {"name": "literature", "description": "文献上传、检索、查重、合并、标签管理"},
        {"name": "extraction", "description": "AI文献数据提取、提取历史、数据导出"},
        {"name": "map", "description": "全国抗体数据地理分布与趋势分析"},
        {"name": "analysis", "description": "多维度数据分析与可视化"},
        {"name": "report", "description": "数据报告生成与下载"},
        {"name": "search", "description": "全文搜索"},
        {"name": "folder_monitor", "description": "文件夹自动监控与文献导入"},
        {"name": "models", "description": "远程AI模型配置管理"},
        {"name": "tags", "description": "文献标签管理"},
        {"name": "dictionary", "description": "数据字典查询"},
    ],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录每个 HTTP 请求的耗时与状态码（结构化日志）。"""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "Request failed",
            method=request.method,
            path=request.url.path,
            elapsed_ms=round(elapsed_ms, 2),
        )
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "Request completed",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        elapsed_ms=round(elapsed_ms, 2),
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix="/api/v1")

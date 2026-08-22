import asyncio
import logging
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.models.base import engine, async_session
from app.api.v1.router import router as api_v1_router
from app.core.logging_config import setup_logging, logger
from app.core.exceptions import AppError
from app.core.metrics import metrics_accessible, record_http_exception

# Prometheus HTTP 指标收集（依赖缺失时静默跳过，不影响应用启动）
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    from prometheus_fastapi_instrumentator.metrics import default as default_metrics
    HAS_PROMETHEUS = True
except Exception:  # pragma: no cover - 依赖缺失兜底
    HAS_PROMETHEUS = False

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

    # 初始化默认报告模板（仅当库中无任何模板时写入）
    try:
        from app.services import report_service
        async with async_session() as session:
            seeded = await report_service.seed_default_templates(session)
            if seeded:
                logger.info(f"已初始化默认报告模板 {seeded} 个")
    except Exception as e:
        logger.error(f"初始化默认报告模板失败: {e}")

    # 启动文件夹监控后台任务
    from app.services.folder_monitor_service import _folder_monitor_loop
    monitor_task = asyncio.create_task(_folder_monitor_loop())

    # 启动孤儿文件清理后台任务（默认每天一次，可配置 ORPHAN_CLEANUP_ENABLED 关闭）
    cleanup_task: Optional[asyncio.Task] = None
    if settings.ORPHAN_CLEANUP_ENABLED:
        from app.services.file_cleanup_service import _cleanup_loop
        cleanup_task = asyncio.create_task(_cleanup_loop())

    # 启动 Prometheus 指标后台采集任务（每 60 秒刷新 data_point_count / celery 队列深度）
    metrics_tasks: list = []
    if settings.METRICS_ENABLED:
        from app.core.metrics import start_metrics_background_tasks
        metrics_tasks = start_metrics_background_tasks()

    yield

    # 停止 Prometheus 指标后台采集任务
    for metrics_task in metrics_tasks:
        metrics_task.cancel()
        try:
            await metrics_task
        except asyncio.CancelledError:
            pass

    # 停止孤儿文件清理后台任务
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

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
    docs_url="/docs" if settings.APP_ENV == "development" else None,
    redoc_url="/redoc" if settings.APP_ENV == "development" else None,
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

# ---- 全局异常处理器：统一错误响应格式 ----
# 响应统一为：{ "success": false, "code", "message", "data", "request_id" }


def _error_response(
    *,
    code: str,
    message: str,
    data: Optional[dict] = None,
    request_id: Optional[str] = None,
) -> dict:
    """构造统一格式的错误响应体。"""
    body = {
        "success": False,
        "code": code,
        "message": message,
        "data": data,
    }
    if request_id:
        body["request_id"] = request_id
    return body


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """业务异常：按异常携带的 code/message/details/status_code 渲染。"""
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_response(
            code=exc.code,
            message=exc.message,
            data=exc.details,
        ),
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    """数据库异常：记录日志并返回 500 标准格式，避免泄露底层细节。"""
    logger.exception(f"Database error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content=_error_response(
            code="DATABASE_ERROR",
            message="数据库操作失败，请稍后重试",
        ),
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    """请求校验失败：返回 422，包含字段级错误详情。"""
    errors = exc.errors()
    details = [
        {
            "field": ".".join(str(p) for p in err.get("loc", ()) if p not in ("loc", "body")),
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in errors
    ] if errors else None
    return JSONResponse(
        status_code=422,
        content=_error_response(
            code="VALIDATION_ERROR",
            message="请求参数校验失败",
            data=details,
        ),
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录每个 HTTP 请求的耗时与状态码（结构化日志）。"""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        record_http_exception(500)  # 记录 Prometheus 异常计数（非阻塞）
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

# ---- Prometheus /metrics 访问控制 ----
# 未授权访问 /metrics 直接返回 403，不泄露内部指标（需在路由注册前生效）
@app.middleware("http")
async def metrics_access_guard(request: Request, call_next):
    if request.url.path == "/metrics" and not metrics_accessible(request):
        return JSONResponse(
            status_code=403,
            content=_error_response(
                code="METRICS_FORBIDDEN",
                message="无权访问指标端点",
            ),
        )
    return await call_next(request)

# ---- Prometheus 指标端点（放在业务路由注册之前）----
# 自动收集 HTTP 请求量(按 method/status)、延迟直方图；METRICS_ENABLED 可整体关闭
if settings.METRICS_ENABLED and HAS_PROMETHEUS:
    Instrumentator().add(
        default_metrics()
    ).instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=settings.APP_ENV == "development",
        tags=["monitoring"],
    )

app.include_router(api_v1_router, prefix="/api/v1")

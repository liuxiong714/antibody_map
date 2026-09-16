import asyncio
import contextlib
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.models.base import Base, engine
import app.models  # noqa: F401  # 确保所有模型注册到 Base.metadata（供 create_all 兜底建表）
from app.api.v1.router import router as api_v1_router
from app.config import settings
from app.core.exceptions import AppError
from app.core.logging_config import logger, setup_logging
from app.core.metrics import metrics_accessible, record_http_exception
from app.models.base import async_session, engine

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

    额外校验迁移链分叉（多个 head）：只记 warning 不阻塞启动——历史上项目
    已存在多个 head（非 bug），真实升级由 Alembic 自己处理。
    """
    backend_dir = Path(__file__).resolve().parent.parent

    heads = subprocess.run(
        [sys.executable, "-m", "alembic", "heads", "--verbose"],
        cwd=str(backend_dir), capture_output=True, text=True, timeout=30,
    )
    if heads.returncode == 0:
        head_lines = [l for l in heads.stdout.strip().splitlines() if l.strip() and not l.startswith('INFO') and not l.startswith('TRACE')]
        real_heads = [l for l in head_lines if ' (revision ' in l or not l.startswith('  ')]
        if len(real_heads) > 1:
            logger.warning(f"Alembic migration chain has {len(real_heads)} heads (possible fork). Alembic will attempt to merge during upgrade. Heads: {real_heads}")

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


async def _ensure_tables():
    """兜底建表：以 SQLAlchemy 模型为准补齐缺失的表。

    Alembic 迁移链可能未覆盖部分模型（如 user、audit_log、kg_qa_log），
    用 metadata.create_all 幂等地补建缺失表，不影响已存在的表。

    额外执行少量幂等 ALTER TABLE（ADD COLUMN IF NOT EXISTS）补齐新列。
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 补齐 kg_triple.review_status（幂等）
        try:
            await conn.execute(text(
                "ALTER TABLE kg_triple ADD COLUMN IF NOT EXISTS review_status VARCHAR(16) NOT NULL DEFAULT 'pending'"
            ))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_kg_triple_review_status ON kg_triple (review_status)"))
        except Exception as e:
            logger.warning(f"补齐 kg_triple.review_status 失败（忽略）: {e}")
    logger.info("Database tables ensured (create_all fallback)")


async def _seed_admin_user():
    """确保默认管理员账号存在（admin / 默认密码）。

    首次启动时 user 表可能为空，导致无账号可登录；这里幂等插入管理员。
    """
    from sqlalchemy import select
    from app.api.v1.auth import DEFAULT_PASSWORD
    from app.core.security import hash_password
    from app.models.base import async_session
    from app.models.user import User

    async with async_session() as session:
        existing = await session.execute(select(User).where(User.username == "admin"))
        if existing.scalar_one_or_none() is None:
            session.add(User(
                username="admin",
                display_name="管理员",
                is_admin=True,
                is_active=True,
                hashed_password=hash_password(DEFAULT_PASSWORD),
            ))
            await session.commit()
            logger.info("Default admin user created (username=admin)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时运行数据库迁移（在独立线程中执行，避免 asyncio.run() 嵌套）
    try:
        await asyncio.to_thread(_run_migrations)
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        raise

    # 兜底补齐迁移链未覆盖的表（如 user、audit_log）
    await _ensure_tables()

    # 确保默认管理员账号存在
    await _seed_admin_user()

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
    cleanup_task: asyncio.Task | None = None
    if settings.ORPHAN_CLEANUP_ENABLED:
        from app.services.file_cleanup_service import _cleanup_loop
        cleanup_task = asyncio.create_task(_cleanup_loop())

    # 启动回收站自动清理后台任务（每天检查一次，永久删除超过30天的软删除文献）
    trash_cleanup_task: asyncio.Task | None = None
    try:
        from app.services.literature_service import _trash_cleanup_loop
        trash_cleanup_task = asyncio.create_task(_trash_cleanup_loop())
    except Exception as e:
        logger.error(f"启动回收站清理任务失败: {e}")

    # 启动分析快照清理后台任务（每天一次，回收超过 SNAPSHOT_TTL_DAYS 天的旧快照）
    snapshot_cleanup_task: asyncio.Task | None = None
    try:
        from app.services.snapshot_service import _snapshot_cleanup_loop
        snapshot_cleanup_task = asyncio.create_task(_snapshot_cleanup_loop())
    except Exception as e:
        logger.error(f"启动快照清理任务失败: {e}")

    # 启动过期临时模型配置清理后台任务（每小时一次，回收单次提取注入的临时凭证）
    model_config_cleanup_task: asyncio.Task | None = None
    try:
        from app.services.extraction_service import _expired_model_config_cleanup_loop
        model_config_cleanup_task = asyncio.create_task(_expired_model_config_cleanup_loop())
    except Exception as e:
        logger.error(f"启动过期模型配置清理任务失败: {e}")

    # 启动 Prometheus 指标后台采集任务（每 60 秒刷新 data_point_count / celery 队列深度）
    metrics_tasks: list = []
    if settings.METRICS_ENABLED:
        from app.core.metrics import start_metrics_background_tasks
        metrics_tasks = start_metrics_background_tasks()

    yield

    # 停止 Prometheus 指标后台采集任务
    for metrics_task in metrics_tasks:
        metrics_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await metrics_task

    # 停止孤儿文件清理后台任务
    if cleanup_task:
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup_task

    # 停止回收站自动清理后台任务
    if trash_cleanup_task:
        trash_cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await trash_cleanup_task

    # 停止分析快照清理后台任务
    if snapshot_cleanup_task:
        snapshot_cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await snapshot_cleanup_task

    # 停止过期临时模型配置清理后台任务
    if model_config_cleanup_task:
        model_config_cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await model_config_cleanup_task

    # 停止文件夹监控后台任务
    monitor_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await monitor_task

    # 释放外部 HTTP 共享连接池（Crossref/OpenAlex/EuropePMC 统一连接）
    try:
        from app.core.external_http import close_client
        await close_client()
    except Exception as e:
        logger.error(f"关闭外部 HTTP 连接池失败: {e}")

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
    data: dict | None = None,
    request_id: str | None = None,
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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """FastAPI/Starlette 的 HTTPException 统一转成 ApiResponse 格式，避免 detail 裸出。"""
    record_http_exception(exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_response(
            code=f"HTTP_{exc.status_code}",
            message=str(exc.detail) if exc.detail else "请求失败",
        ),
    )


@app.middleware("http")
async def inject_trace_id(request: Request, call_next):
    """注入请求级 trace_id：从 X-Request-Id 读或生成；记录到 request.state 并写入响应头。"""
    import uuid as _uuid
    trace_id = request.headers.get("x-request-id") or _uuid.uuid4().hex[:16]
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = trace_id
    return response


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
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
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

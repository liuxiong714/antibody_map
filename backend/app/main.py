import asyncio
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models.base import engine
from app.api.v1.router import router as api_v1_router

logger = logging.getLogger("uvicorn")


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
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix="/api/v1")

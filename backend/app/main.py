import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models.base import engine
from app.api.v1.router import router as api_v1_router

logger = logging.getLogger("uvicorn")


def _run_migrations():
    """同步执行 Alembic 迁移（在子线程中运行以避免事件循环冲突）"""
    from alembic.config import Config
    from alembic import command
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations applied successfully")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时运行数据库迁移（在独立线程中执行，避免 asyncio.run() 嵌套）
    try:
        await asyncio.to_thread(_run_migrations)
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        raise
    yield
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

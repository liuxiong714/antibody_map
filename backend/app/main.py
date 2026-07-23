import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.models.base import engine, Base
from app.api.v1.router import router as api_v1_router

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时尝试创建数据库表（Docker 环境下生效）
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # 为已有 report 表添加新列（兼容旧数据库）
            await conn.execute(text(
                "ALTER TABLE report ADD COLUMN IF NOT EXISTS report_type VARCHAR(30) DEFAULT 'antibody_analysis'"
            ))
            await conn.execute(text(
                "ALTER TABLE report ADD COLUMN IF NOT EXISTS task_type VARCHAR(100)"
            ))
            await conn.execute(text(
                "ALTER TABLE report ADD COLUMN IF NOT EXISTS task_time VARCHAR(200)"
            ))
            await conn.execute(text(
                "ALTER TABLE report ADD COLUMN IF NOT EXISTS task_location VARCHAR(200)"
            ))
            await conn.execute(text(
                "ALTER TABLE report ADD COLUMN IF NOT EXISTS personnel_count INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE report ADD COLUMN IF NOT EXISTS personnel_gender VARCHAR(100)"
            ))
            await conn.execute(text(
                "ALTER TABLE report ADD COLUMN IF NOT EXISTS personnel_age VARCHAR(100)"
            ))
            await conn.execute(text(
                "ALTER TABLE report ADD COLUMN IF NOT EXISTS personnel_vaccination_history TEXT"
            ))
        logger.info("Database tables created/updated successfully")
    except Exception as e:
        logger.warning(f"Database migration issue: {e}")
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

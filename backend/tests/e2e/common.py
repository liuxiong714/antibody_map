"""V4-07 E2E 公共工具 — 解决 strict async fixture 问题。"""
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings


@asynccontextmanager
async def e2e_engine_session():
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        try:
            yield engine, db
        finally:
            await engine.dispose()

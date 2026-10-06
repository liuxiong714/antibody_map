"""V4-07 E2E 测试 conftest — 标记 + skip 控制。

E2E 测试默认跳过（需要完整栈: PG + MinIO + Redis + LLM）。
跑法: pytest tests/e2e -v --run-e2e
"""
from __future__ import annotations

import asyncio
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.config import settings


# ===== pytest marker =====
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests requiring full stack (PG+MinIO+Redis+LLM)"
    )


def pytest_addoption(parser):
    parser.addoption("--run-e2e", action="store_true", default=False,
                     help="Run E2E tests (default: skip)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-e2e"):
        return
    skip_e2e = pytest.mark.skip(reason="E2E test — 需要显式传 --run-e2e 才跑")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


# ===== helpers (非 fixture — 避免 strict async fixture 问题) =====

def pg_available() -> bool:
    """检测 PG 是否可达（同步）。"""
    try:
        engine = create_async_engine(settings.DATABASE_URL)
        async def check():
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
        asyncio.run(check())
        return True
    except Exception:
        return False
    finally:
        try:
            asyncio.run(engine.dispose())
        except Exception:
            pass


def make_engine():
    return create_async_engine(settings.DATABASE_URL)

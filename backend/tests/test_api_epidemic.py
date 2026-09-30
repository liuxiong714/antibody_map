"""epidemic.py 端点测试。"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1 import epidemic


def _fake_db():
    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalars = MagicMock(return_value=fake_result)
    fake_result.all = MagicMock(return_value=[])
    fake_result.scalar_one = MagicMock(return_value=None)
    fake_result.count = MagicMock(return_value=0)
    db.execute = AsyncMock(return_value=fake_result)
    return db


@pytest.mark.asyncio
async def test_epidemic_overview():
    resp = await epidemic.epidemic_overview(
        disease="新冠", db=_fake_db(),
    )
    assert resp.data is not None


@pytest.mark.asyncio
async def test_epidemic_data_points():
    resp = await epidemic.epidemic_data_points(
        disease="新冠", page=1, page_size=20, db=_fake_db(),
    )
    assert resp.data is not None


@pytest.mark.asyncio
async def test_pathogen_monitoring_list():
    resp = await epidemic.pathogen_monitoring_list(
        disease="新冠", page=1, page_size=20, db=_fake_db(),
    )
    assert resp.data is not None


@pytest.mark.asyncio
async def test_pathogen_monitoring_by_literature():
    resp = await epidemic.pathogen_monitoring_by_literature(
        literature_id=uuid.UUID(int=1), db=_fake_db(),
    )
    assert resp.data is not None

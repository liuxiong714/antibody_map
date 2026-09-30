"""api/v1/synthetic.py 端点测试 —— 2/2 green (list + export)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _fake_db():
    db = MagicMock()
    fake_task = MagicMock()
    fake_task.id = uuid.UUID(int=1)
    fake_task.status = "failed"
    fake_task.created_at = None
    fake_task.updated_at = None
    fake_task.report_json = {"assess": "ok"}
    fake_result = MagicMock()
    fake_scalars = MagicMock()
    fake_scalars.first = MagicMock(return_value=fake_task)
    fake_scalars.all = MagicMock(return_value=[])
    fake_result.scalars = MagicMock(return_value=fake_scalars)
    fake_result.scalar_one_or_none = MagicMock(return_value=fake_task)
    fake_result.scalar = MagicMock(return_value=0)
    db.execute = AsyncMock(return_value=fake_result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_list_synthetic():
    from app.api.v1 import synthetic as synapi
    resp = await synapi.list_synthetic(db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_export_synthetic():
    from app.api.v1 import synthetic as synapi
    result = await synapi.export_synthetic(task_id=uuid.UUID(int=1), db=_fake_db())
    assert result is not None

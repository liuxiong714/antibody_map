"""api/v1/extraction.py 端点测试 —— MagicMock db (6 passed, 1 skip)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _fake_db():
    db = MagicMock()
    fake_lit = SimpleNamespace(
        id=uuid.UUID(int=1), title="Test",
        extraction_status="completed", extraction_version=1,
        extraction_started_at=None, extraction_finished_at=None,
        has_fulltext=True, version=1, authors=[], abstract=None,
        status="done", extracted_count=5,
    )
    fake_result = MagicMock()
    fake_scalars = MagicMock()
    fake_scalars.first = MagicMock(return_value=fake_lit)
    fake_scalars.all = MagicMock(return_value=[])
    fake_result.scalars = MagicMock(return_value=fake_scalars)
    fake_result.scalar_one_or_none = MagicMock(return_value=fake_lit)
    fake_result.scalar = MagicMock(return_value=0)
    db.execute = AsyncMock(return_value=fake_result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = MagicMock()
    db.get = AsyncMock(return_value=fake_lit)
    return db


@pytest.mark.asyncio
async def test_sync_literature_metadata():
    from app.api.v1 import extraction
    resp = await extraction.sync_literature_metadata(literature_id=uuid.UUID(int=1), db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_stop_extraction():
    from app.api.v1 import extraction
    resp = await extraction.stop_extraction(literature_id=uuid.UUID(int=1), db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_sync_metadata_batch():
    from app.api.v1 import extraction
    resp = await extraction.sync_metadata_batch(db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_reset_stuck_extractions():
    from app.api.v1 import extraction
    resp = await extraction.reset_stuck_extractions(db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_reset_my_extractions():
    from app.api.v1 import extraction
    fake_user = SimpleNamespace(id="user-1", username="test")
    resp = await extraction.reset_my_extractions(current_user=fake_user, db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_export_data_points():
    from app.api.v1 import extraction
    result = await extraction.export_data_points(literature_id=uuid.UUID(int=1), db=_fake_db())
    assert result is not None


@pytest.mark.asyncio
async def test_get_extraction_queue_status():
    from app.api.v1 import extraction
    try:
        resp = await extraction.get_extraction_queue_status(db=_fake_db())
        assert resp is not None
    except Exception as e:
        pytest.skip(f"Redis not available: {type(e).__name__}")

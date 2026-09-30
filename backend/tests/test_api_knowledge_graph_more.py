"""api/v1/knowledge_graph.py 端点测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_kg_svc():
    kg = MagicMock()
    for name, ret in [
        ("get_graph", {"nodes": [], "links": []}),
        ("get_overview", {"entities": 0, "relations": 0}),
        ("get_options", {"provinces": [], "pathogens": []}),
    ]:
        setattr(kg, name, AsyncMock(return_value=ret))
    return kg


def _fake_db():
    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalars = MagicMock(return_value=fake_result)
    fake_result.all = MagicMock(return_value=[])
    fake_result.scalar = MagicMock(return_value=0)
    db.execute = AsyncMock(return_value=fake_result)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_overview():
    from app.api.v1 import knowledge_graph as kgapi
    fake_kg = _fake_kg_svc()
    with patch("app.api.v1.knowledge_graph.kg", fake_kg):
        resp = await kgapi.overview(db=_fake_db())
    assert resp.data is not None


@pytest.mark.asyncio
async def test_options():
    from app.api.v1 import knowledge_graph as kgapi
    fake_kg = _fake_kg_svc()
    with patch("app.api.v1.knowledge_graph.kg", fake_kg):
        resp = await kgapi.options(db=_fake_db())
    assert resp.data is not None


@pytest.mark.asyncio
async def test_graph():
    from app.api.v1 import knowledge_graph as kgapi
    fake_kg = _fake_kg_svc()
    with patch("app.api.v1.knowledge_graph.kg", fake_kg):
        resp = await kgapi.graph(db=_fake_db())
    assert resp.data is not None


@pytest.mark.asyncio
async def test_stats_counts():
    from app.api.v1 import knowledge_graph as kgapi
    fake_db = _fake_db()
    fake_execute = MagicMock()
    fake_execute.scalar = MagicMock(return_value=0)
    fake_db.execute = AsyncMock(return_value=fake_execute)
    resp = await kgapi.stats(db=fake_db)
    assert resp.data is not None

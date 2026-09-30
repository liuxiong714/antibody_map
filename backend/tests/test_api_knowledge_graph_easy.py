"""api/v1/knowledge_graph.py 简单端点测试 —— 纯 service-patch。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import knowledge_graph as kgapi


def _fake_db():
    return MagicMock()


@pytest.mark.asyncio
async def test_overview_success():
    fake = {"total_entities": 1000, "total_relations": 5000}
    with patch("app.api.v1.knowledge_graph.kg.get_overview", AsyncMock(return_value=fake)):
        resp = await kgapi.overview(review_status=["approved"], db=_fake_db())
    assert resp.data == fake


@pytest.mark.asyncio
async def test_options_success():
    fake = {"provinces": ["北京", "上海"], "pathogens": ["新冠", "甲流"]}
    with patch("app.api.v1.knowledge_graph.kg.get_options", AsyncMock(return_value=fake)):
        resp = await kgapi.options(db=_fake_db())
    assert resp.data == fake


@pytest.mark.asyncio
async def test_graph_returns_patched_data():
    fake_graph = {"nodes": [{"id": "n1"}], "links": [{"source": "n1", "target": "n2"}]}
    with patch("app.api.v1.knowledge_graph.kg.get_graph", AsyncMock(return_value=fake_graph)):
        resp = await kgapi.graph(db=_fake_db())
    assert resp.data == fake_graph

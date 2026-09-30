"""map_data.py 端点测试 —— patch map_service。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_db():
    db = MagicMock()
    fake_result = MagicMock()
    fake_scalars = MagicMock()
    fake_scalars.first = MagicMock(return_value=None)
    fake_scalars.all = MagicMock(return_value=[])
    fake_result.scalars = MagicMock(return_value=fake_scalars)
    fake_result.scalar_one_or_none = MagicMock(return_value=None)
    fake_result.scalar = MagicMock(return_value=0)
    db.execute = AsyncMock(return_value=fake_result)
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_map_data_available_years():
    from app.api.v1 import map_data as mapi
    with patch("app.api.v1.map_data.map_service") as m_svc:
        m_svc.get_available_years = AsyncMock(return_value=[2020, 2021])
        resp = await mapi.available_years(db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_map_data_province_data():
    from app.api.v1 import map_data as mapi
    with patch("app.api.v1.map_data.map_service") as m_svc:
        m_svc.get_province_data = AsyncMock(return_value=[])
        resp = await mapi.province_data(db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_map_data_city_data():
    from app.api.v1 import map_data as mapi
    with patch("app.api.v1.map_data.map_service") as m_svc:
        m_svc.get_city_data = AsyncMock(return_value=[])
        resp = await mapi.city_data(province="北京", db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_map_data_summary():
    from app.api.v1 import map_data as mapi
    with patch("app.api.v1.map_data.map_service") as m_svc:
        m_svc.get_summary = AsyncMock(return_value={})
        resp = await mapi.summary(db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_map_data_yearly_province_data():
    from app.api.v1 import map_data as mapi
    with patch("app.api.v1.map_data.map_service") as m_svc:
        m_svc.get_province_yearly_data = AsyncMock(return_value=[])
        resp = await mapi.yearly_province_data(db=_fake_db())
    assert resp is not None


@pytest.mark.asyncio
async def test_map_data_population_options():
    from app.api.v1 import map_data as mapi
    with patch("app.api.v1.map_data.map_service") as m_svc:
        m_svc.get_population_options = AsyncMock(return_value=[])
        resp = await mapi.population_options(db=_fake_db())
    assert resp is not None

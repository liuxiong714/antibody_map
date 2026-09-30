"""api/v1/dictionary.py 直接常量端点测试 —— 无需 patch。"""
from __future__ import annotations

import pytest
from app.api.v1 import dictionary as dic


@pytest.mark.asyncio
async def test_get_diseases():
    resp = await dic.get_diseases()
    assert resp.data is not None
    assert len(resp.data) > 0


@pytest.mark.asyncio
async def test_get_provinces():
    resp = await dic.get_provinces()
    assert resp.data is not None
    assert len(resp.data) >= 34  # 34 省级


@pytest.mark.asyncio
async def test_get_methods():
    resp = await dic.get_methods()
    assert resp.data is not None
    assert len(resp.data) > 0

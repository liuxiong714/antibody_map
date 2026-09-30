"""api/v1/analysis.py 批量端点测试 —— patch analysis_service + 正确参数签名。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


SVC_MOCKS = {
    "get_trend": {"trend": []},
    "get_region_compare": {"data": []},
    "get_zone_compare": {"data": []},
    "get_equity_analysis": {"hi": 0.8, "lo": 0.2},
    "get_quality_assessment": {},
    "rescore_quality": {"ok": True},
    "get_goal_tracking": {"goals": []},
    "get_age_curve": {"n_points": 100, "curve": []},
    "get_birth_cohort": {"cohorts": []},
    "get_meta_merge": {"rows": []},
    "get_meta_analysis": {"total": 10, "subgroups": []},
    "get_spatial_hotspots": {"clusters": [], "n_valid": 10},
    "get_assay_heterogeneity": {"i2": 0.1},
    "get_simulation": {"scenarios": []},
    "get_age_stratify": {"buckets": []},
    "get_summary": {"total": 100},
    "get_immune_barrier_assessment": {"barrier": 0.5},
    "get_immunity_projection": {"projection": []},
    "get_effective_barrier": {"effective": 0.3},
    "get_barrier_probability": 0.8,
    "get_barrier_scenarios": [],
    "get_approved_data_points": ([], 100),
    "get_approved_data_points_for_snapshot": ([], 100),
    "get_data_gap_analysis": {"gaps": []},
    "get_coverage_review_stats": {"pending": 0},
    "get_foi_analysis": {"fois": []},
    "get_vaccine_analysis": {"coverage": {}},
}


@pytest.fixture
def fake_svc():
    svc = MagicMock()
    for name, ret in SVC_MOCKS.items():
        setattr(svc, name, AsyncMock(return_value=ret))
    return svc


def _fake_db():
    return MagicMock()


def _load_ana(fake_svc):
    p = patch("app.api.v1.analysis.analysis_service", fake_svc)
    p.start()
    from app.api.v1 import analysis as ana
    return ana, p


# ========= 每个端点各自 test =========

@pytest.mark.asyncio
async def test_get_trend(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_trend(
            disease="新冠", province=None,
            year_start=2000, year_end=2025, db=_fake_db(),
        )
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_region_compare(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_region_compare(
            disease="新冠", province="北京", db=_fake_db(),
        )
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_zone_compare(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_zone_compare(
            disease="新冠", province="北京", db=_fake_db(),
        )
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_equity(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_equity(
            disease="新冠", year_start=2000, year_end=2025, db=_fake_db(),
        )
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_quality(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_quality(
            disease="新冠", province="北京", db=_fake_db(),
        )
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_goal_tracking(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_goal_tracking(db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_age_curve(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_age_curve(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_birth_cohort(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_birth_cohort(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_meta_merge(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_meta_merge(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_meta_analysis(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_meta_analysis(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_spatial_hotspots(fake_svc):
    ana, p = _load_ana(fake_svc)
    # spatial_hotspots 内部也查 SQL，需要 patch db.execute
    fake_db = _fake_db()
    # 让 db.execute 模拟返回一个 scaler list（≥8 省份）
    fake_execute = MagicMock()
    fake_execute.scalars = MagicMock(return_value=["北京", "上海", "广东", "江苏", "浙江", "四川", "湖北", "山东", "福建", "湖南"])
    fake_db.execute = AsyncMock(return_value=fake_execute)
    try:
        resp = await ana.get_spatial_hotspots(
            disease="新冠", level="province", db=fake_db,
        )
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_assay_heterogeneity(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_assay_heterogeneity(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_age_stratify(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_age_stratify(
            disease="新冠", data_type="seroprevalence", db=_fake_db(),
        )
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_summary(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_summary(
            disease="新冠", data_type="seroprevalence", db=_fake_db(),
        )
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_immune_barrier(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_immune_barrier(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_immunity_projection(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_immunity_projection(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_effective_barrier(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_effective_barrier(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_approved_data_points(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_approved_data_points(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_data_gaps(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_data_gaps(db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


@pytest.mark.asyncio
async def test_get_simulation(fake_svc):
    ana, p = _load_ana(fake_svc)
    try:
        resp = await ana.get_simulation(disease="新冠", db=_fake_db())
    finally:
        p.stop()
    assert resp.data is not None


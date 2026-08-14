"""GMC 几何均数修复回归测试。

验证 get_summary / get_age_stratify 的 avg_gmc 已改用 geometric_mean_with_ci
（几何均值）而非算术均值；沿用 test_analysis_advanced.py 的 FakeDB / run 工具。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.analysis_service import get_summary, get_age_stratify


# ── 工具：Fake DB / Fake 数据点 ───────────────────────────

class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    """依次返回每个 execute 对应的结果批次。"""
    def __init__(self, *row_batches):
        self._batches = list(row_batches)
        self.executed_queries = []

    async def execute(self, query):
        self.executed_queries.append(query)
        if self._batches:
            return FakeResult(self._batches.pop(0))
        return FakeResult([])


def _dp(value, data_type="gmc", ss=100):
    """构造一个模拟 DataPoint 对象（属性访问方式）。"""
    return SimpleNamespace(
        value=value, data_type=data_type, sample_size=ss, review_status="approved",
        estimate_type="primary", province="广东", collection_year=2020,
        age_min=20, age_max=30, ci_lower=None, ci_upper=None,
        literature_id=uuid4(),
    )


def run(fn, db, *args, **kwargs):
    import asyncio
    return asyncio.run(fn(db, *args, **kwargs))


# ── 回归测试 ──────────────────────────────────────────────

def test_summary_gmc_is_geometric():
    # [100, 2000, 30000] 几何均值≈1817.12，算术均值=10700（错误结果）
    res = run(get_summary, FakeDB([_dp(100), _dp(2000), _dp(30000)]))
    assert res["avg_gmc"] == pytest.approx(1817.12, rel=1e-2)
    assert res["avg_gmc"] != 10700.0


def test_age_stratify_gmc_is_geometric():
    res = run(get_age_stratify, FakeDB([_dp(100), _dp(2000), _dp(30000)]))
    gmcs = [r["avg_gmc"] for r in res if r["avg_gmc"] is not None]
    assert gmcs and gmcs[0] == pytest.approx(1817.12, rel=1e-2)

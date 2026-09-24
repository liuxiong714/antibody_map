"""P1: get_simulation 的 ve（疫苗保护效率）参数测试

覆盖：
  1. ve=1.0 默认行为 与 旧公式（effective = cov + (1-cov)·boost）完全等价
  2. ve=0.9 等 非1值，新公式 protective = cov·ve; effective = protective + (1-protective/100)·boost
  3. 边界：ve=0（基础接种无效，仅加强针） / ve>1 钳位 1.0 / ve<0 钳位 0.0
  4. required_coverage 反推也随 ve 修正（h = cv + (1-cv)b → c = (h-b)/(v(1-b))）
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.analysis.infectious_disease import get_simulation


# ── FakeDB（适配 get_goal_threshold 的额外查询）────────────────

class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """依次返回批次；get_simulation 内部依次查询：DataPoint seroprevalence → goal_threshold。"""
    def __init__(self, *row_batches):
        self._batches = list(row_batches)

    async def execute(self, query):
        if self._batches:
            return FakeResult(self._batches.pop(0))
        return FakeResult([])


def dp(**kwargs):
    base = dict(
        id="dp-1", literature_id="lit-1",
        disease="measles", age_min=5, age_max=10, value=80, sample_size=100,
        data_type="seroprevalence", estimate_type="primary", review_status="approved",
        quality_grade="A",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def run(fn, db, *args, **kwargs):
    import asyncio
    return asyncio.run(fn(db, *args, **kwargs))


# ============================================================
# 1. ve=1.0 默认 → 与旧公式完全等价（现有测试已证）
# ============================================================

def test_ve_default_one_equivalent_to_old_formula():
    """cov=60, boost=50, ve=1.0 → protective=60, effective=60+0.4*50=80（同旧公式）。"""
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=60, booster_rate=50)
    sim = res["simulated"]
    assert sim is not None
    assert sim["effective_coverage_percent"] == pytest.approx(80.0, abs=1e-4)
    assert sim["protective_coverage_percent"] == pytest.approx(60.0, abs=1e-4)
    assert sim["ve_used"] == pytest.approx(1.0, abs=1e-6)
    # 顶层也带 ve_used
    assert res["ve_used"] == pytest.approx(1.0, abs=1e-6)
    # 加强针增益 = effective - protective
    assert sim["gain_from_booster_percent"] == pytest.approx(20.0, abs=1e-4)


# ============================================================
# 2. ve=0.9 新行为
# ============================================================

def test_ve_0_point_9_reduces_protective():
    """cov=60, boost=50, ve=0.9 → protective=54, effective=54+0.46*50=77。"""
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=60, booster_rate=50, ve=0.9)
    sim = res["simulated"]
    assert sim is not None
    assert sim["protective_coverage_percent"] == pytest.approx(54.0, abs=1e-4)
    assert sim["effective_coverage_percent"] == pytest.approx(77.0, abs=1e-4)
    assert sim["ve_used"] == pytest.approx(0.9, abs=1e-6)
    assert sim["gain_from_booster_percent"] == pytest.approx(23.0, abs=1e-4)


def test_ve_0_point_5_no_booster_protected_only_half():
    """cov=60, boost=0, ve=0.5 → protective=30, effective=30, gain=0。"""
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=60, booster_rate=0, ve=0.5)
    sim = res["simulated"]
    assert sim is not None
    assert sim["protective_coverage_percent"] == pytest.approx(30.0, abs=1e-4)
    assert sim["effective_coverage_percent"] == pytest.approx(30.0, abs=1e-4)
    assert sim["gain_from_booster_percent"] == pytest.approx(0.0, abs=1e-4)


# ============================================================
# 3. 边界钳位
# ============================================================

@pytest.mark.parametrize("ve_input, expected_clamped", [
    (1.5, 1.0),   # 超过 1 → 钳为 1
    (2.0, 1.0),
    (0.0, 0.0),
    (-0.1, 0.0),  # 低于 0 → 钳为 0
    (-0.5, 0.0),
])
def test_ve_clamped(ve_input: float, expected_clamped: float):
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=80, booster_rate=20, ve=ve_input)
    assert res["ve_used"] == pytest.approx(expected_clamped, abs=1e-9)
    sim = res["simulated"]
    assert sim["ve_used"] == pytest.approx(expected_clamped, abs=1e-9)


def test_ve_zero_only_booster_effective():
    """ve=0 → protective=0, effective = boost (boost 作用于 100% 未保护者)。"""
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=100, booster_rate=80, ve=0.0)
    sim = res["simulated"]
    assert sim is not None
    assert sim["protective_coverage_percent"] == pytest.approx(0.0, abs=1e-4)
    # effective = 0 + (1-0)*80 = 80
    assert sim["effective_coverage_percent"] == pytest.approx(80.0, abs=1e-4)
    assert sim["gain_from_booster_percent"] == pytest.approx(80.0, abs=1e-4)


def test_ve_one_no_booster_protected_equals_cov():
    """ve=1, boost=0 → protective = effective = cov, gain=0（基础接种 100% 转化保护）。"""
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=75, booster_rate=0, ve=1.0)
    sim = res["simulated"]
    assert sim is not None
    assert sim["protective_coverage_percent"] == pytest.approx(75.0, abs=1e-4)
    assert sim["effective_coverage_percent"] == pytest.approx(75.0, abs=1e-4)
    assert sim["gain_from_booster_percent"] == pytest.approx(0.0, abs=1e-4)


# ============================================================
# 4. required_coverage 反推 随 ve 修正
# ============================================================

def test_required_coverage_with_ve_revision():
    """measles 文献 R0=15 → HIT≈93.3%。boost=0, ve=0.8:
      c = 0.933 / 0.8 = 1.166 → required=116.6 → None（>100 不可达）。"""
    res = run(get_simulation, FakeDB([dp(value=95)], []),
              disease="measles", assumed_coverage=0, booster_rate=0, ve=0.8)
    assert res["required_coverage_to_reach_hit"] is None, \
        "VE=0.8 下需 cov>100% 才达 HIT → 应返回 None"


def test_required_coverage_with_ve_0_point_9_and_booster():
    """varicella SP=50%@age10 → FOI≈0.0693, R0≈5.20, FOI HIT≈80.77%。
    FOI HIT 优先于 WHO=85%（get_simulation 当前优先级链）。
    boost=20, ve=0.9: c=(0.8077-0.2)/(0.9*(1-0.2))=0.6077/0.72≈0.844 → required≈84.4。"""
    res = run(get_simulation, FakeDB([dp(disease="varicella", value=50, age_min=5, age_max=15)], []),
              disease="varicella", assumed_coverage=0, booster_rate=20, ve=0.9)
    # FOI 优先 → hit_target = 80.77
    assert res["current"]["hit_percent"] == pytest.approx(80.77, abs=0.05)
    assert res["required_coverage_to_reach_hit"] == pytest.approx(84.4, abs=0.1)


def test_ve_zero_required_is_none():
    """VE=0 → 基础接种完全无效，required=None。"""
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=80, booster_rate=0, ve=0.0)
    assert res["required_coverage_to_reach_hit"] is None


# ============================================================
# 5. notes 里有 VE 兼容性提示
# ============================================================

def test_notes_contain_ve_compat_warning_when_ve_default():
    """ve≈1.0 时 notes 应包含兼容性提示。"""
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=80, booster_rate=10)
    assert any("VE=1.0" in n for n in res["notes"]), f"notes={res['notes']}"


def test_notes_no_ve_warning_when_ve_custom():
    """显式传入 ve=0.8 → 不应再提示兼容性警告。"""
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=80, booster_rate=10, ve=0.8)
    assert not any("VE=1.0" in n for n in res["notes"]), f"notes={res['notes']}"


# ============================================================
# 6. 既有字段保持不变（前端兼容）
# ============================================================

def test_existing_fields_still_present():
    """simulated 旧字段全在，顶层 assumed_coverage_percent / booster_rate_percent / current / notes 不变。"""
    res = run(get_simulation, FakeDB([dp()], []),
              disease="measles", assumed_coverage=80, booster_rate=20, ve=0.7)
    sim = res["simulated"]
    # 旧字段
    assert "effective_coverage_percent" in sim
    assert "hit_percent" in sim
    assert "gap_to_hit_percent" in sim
    assert "gain_from_booster_percent" in sim
    assert "status" in sim
    # 新增字段
    assert "protective_coverage_percent" in sim
    assert "ve_used" in sim
    # 顶层
    assert "ve_used" in res
    assert "assumed_coverage_percent" in res
    assert "booster_rate_percent" in res
    assert "current" in res
    assert "required_coverage_to_reach_hit" in res
    assert "notes" in res

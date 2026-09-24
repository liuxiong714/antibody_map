"""P0: get_barrier_scenarios + /analysis/barrier-scenarios

覆盖：
  1. 默认三条 scenarios（baseline/high_cov/booster）
  2. 自定义 scenarios 列表
  3. VE 口径：protective = cov*ve; effective = protective + (1-protective)*booster
  4. required_coverage 反推公式与 get_simulation 完全一致
  5. r_eff 计算（有接触矩阵 NGM 残差 / 均匀近似退化）
  6. 补种人数 gap 与数值（七普总人口 14.12 亿粗估）
  7. 无 rows → 回退文献 R0
  8. status 状态字符串正确
  9. 端点已注册
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.analysis.infectious_disease import get_barrier_scenarios


# ============================================================
# Fake fixtures（复用 test_simulation_ve 模式）
# ============================================================

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
    """依次返回批次：seroprevalence rows → goal_threshold → (可能更多)"""

    def __init__(self, *row_batches):
        self._batches = list(row_batches)

    async def execute(self, query):
        if self._batches:
            return FakeResult(self._batches.pop(0))
        return FakeResult([])


def dp(**kwargs):
    base = dict(
        id="dp-1", literature_id="lit-1",
        disease="measles", collection_year=2023,
        age_min=5, age_max=10, value=80, sample_size=100,
        data_type="seroprevalence", estimate_type="primary", review_status="approved",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


# ============================================================
# 1. 默认三条 scenarios（前端不传 scenarios 参数）
# ============================================================

def test_default_three_scenarios():
    db = FakeDB(
        [
            dp(age_min=0, age_max=4, value=85, sample_size=150),
            dp(age_min=5, age_max=17, value=90, sample_size=200),
            dp(age_min=18, age_max=29, value=80, sample_size=100),
            dp(age_min=30, age_max=59, value=78, sample_size=180),
            dp(age_min=60, age_max=200, value=70, sample_size=50),
        ],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles", province="北京"))
    assert len(res["scenarios"]) == 3
    names = {s["name"] for s in res["scenarios"]}
    assert names == {"baseline", "high_cov", "booster"}


# ============================================================
# 2. VE 口径：protective = cov*ve, effective = protective + (1-protective)*booster
# ============================================================

@pytest.mark.parametrize("cov,boost,ve,expected_prot,expected_eff", [
    (80.0,  0.0, 1.0, 80.0, 80.0),
    (80.0, 50.0, 1.0, 80.0, 90.0),
    (90.0,  0.0, 0.7, 63.0, 63.0),
    (90.0, 50.0, 0.7, 63.0, 81.5),
])
def test_ve_formula_exact(cov, boost, ve, expected_prot, expected_eff):
    protective = cov * ve
    effective = protective + (1 - protective / 100) * boost
    assert protective == pytest.approx(expected_prot, abs=1e-9)
    assert effective == pytest.approx(expected_eff, abs=1e-9)


def test_service_output_ve_formula_exact():
    cov, boost, ve = 80.0, 50.0, 0.85
    protective_expected = cov * ve
    effective_expected = protective_expected + (1 - protective_expected / 100) * boost

    db = FakeDB(
        [dp(age_min=0, age_max=10, value=80, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(
        db, disease="measles",
        scenarios=[{"name": "t1", "coverage": cov, "booster": boost, "ve": ve}],
    ))
    sc = res["scenarios"][0]
    assert sc["protective_coverage_percent"] == pytest.approx(protective_expected, abs=1e-2)
    assert sc["effective_barrier_percent"] == pytest.approx(effective_expected, abs=1e-2)


# ============================================================
# 3. required_coverage 反推公式（动态 HIT，从 service 读出）
# ============================================================

def test_required_coverage_formula_independent():
    """直接公式验证，不依赖 service。"""
    # h = 0.95, b=0, v=1 → c = (0.95-0)/(1*1) = 0.95 → 95
    assert round((0.95 - 0) / (1.0 * 1.0) * 100, 2) == 95.0
    # h=0.95, b=0.5, v=1 → 0.45 / 0.5 = 0.9 → 90
    assert round((0.95 - 0.5) / (1.0 * 0.5) * 100, 2) == 90.0
    # h=0.95, b=0.5, v=0.7 → 0.45 / 0.35 = 1.2857 > 100 → None
    assert (0.95 - 0.5) / (0.7 * 0.5) * 100 > 100


def test_service_required_coverage_consistent_with_reverse_formula():
    """service 返回的 required_coverage 与手动反推公式结果一致。"""
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=90, sample_size=100),
         dp(age_min=5, age_max=17, value=88, sample_size=200),
         dp(age_min=18, age_max=29, value=85, sample_size=150),
         dp(age_min=30, age_max=59, value=82, sample_size=200),
         dp(age_min=60, age_max=200, value=78, sample_size=80)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(
        db, disease="measles",
        scenarios=[{"name": "t1", "coverage": 85.0, "booster": 30.0, "ve": 1.0}],
    ))
    sc = res["scenarios"][0]
    h = sc["hit_target_percent"] / 100.0
    b = 30.0 / 100.0
    v = 1.0
    expected_req = round((h - b) / (v * (1.0 - b)) * 100.0, 2)
    if expected_req > 100.0:
        expected_req = None
    assert sc["required_coverage_to_reach_hit"] == pytest.approx(expected_req, abs=1e-2)


# ============================================================
# 4. R_eff 计算（有接触矩阵）
# ============================================================

def test_r_eff_contact_matrix_used_true():
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=85, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    assert res["r_eff_contact_matrix_used"] is True
    for sc in res["scenarios"]:
        assert sc["r_eff"] is not None
        assert sc["assumption"] is not None


def test_r_eff_drops_as_coverage_rises():
    """高 coverage → 低 effective_ratio → 低 R_eff（覆盖不足时反过来）。"""
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=80, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    # baseline cov=80, high_cov cov=95, booster cov=80+50
    base_r = res["scenarios"][0]["r_eff"]
    high_r = res["scenarios"][1]["r_eff"]
    boost_r = res["scenarios"][2]["r_eff"]
    # 95% 覆盖的 R_eff 应该 < 80% 覆盖（假设 R0 值稳定，均匀免疫下成正比）
    assert high_r < base_r
    # booster scenario effective = 80 + 20*0.5 = 90 → R_eff 介于 baseline 和 high_cov 之间
    assert boost_r <= base_r


# ============================================================
# 5. 补种人数（七普总人口 14.12 亿粗估）
# ============================================================

def test_vaccinate_gap_is_max_zero():
    """gap 永远 ≥ 0（不要求补种时 gap=0）。"""
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=99, sample_size=100),
         dp(age_min=5, age_max=17, value=98, sample_size=200),
         dp(age_min=18, age_max=29, value=97, sample_size=150),
         dp(age_min=30, age_max=59, value=96, sample_size=200),
         dp(age_min=60, age_max=200, value=95, sample_size=80)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    for sc in res["scenarios"]:
        if sc["vaccinate_gap_percent"] is not None:
            assert sc["vaccinate_gap_percent"] >= 0


def test_vaccinate_people_population_constant():
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=80, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    assert res["population_used"] == 1_411_780_000.0
    assert "七普" in res["population_note"]


def test_vaccinate_people_matches_gap_formula():
    """补种人数 = gap% × 七普总人口 / 100。"""
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=85, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(
        db, disease="measles",
        scenarios=[{"name": "t1", "coverage": 85.0, "booster": 0.0, "ve": 1.0}],
    ))
    sc = res["scenarios"][0]
    if sc["vaccinate_gap_percent"] is not None:
        expected = round(sc["vaccinate_gap_percent"] / 100.0 * 1_411_780_000)
        assert sc["vaccinate_people"] == expected


def test_required_none_when_impossible():
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=80, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(
        db, disease="measles",
        scenarios=[{"name": "impossible", "coverage": 80.0, "booster": 0.0, "ve": 0.0}],
    ))
    sc = res["scenarios"][0]
    assert sc["required_coverage_to_reach_hit"] is None
    assert sc["vaccinate_gap_percent"] is None
    assert sc["vaccinate_people"] is None


# ============================================================
# 6. status 字符串
# ============================================================

def test_status_values_valid():
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=80, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    for sc in res["scenarios"]:
        assert sc["status"] in {"reached", "near", "not_reached", "undetermined"}


def test_status_reached_when_effective_equals_hit():
    """effective == hit_target（边界）→ reached。"""
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=99, sample_size=100),
         dp(age_min=5, age_max=17, value=98, sample_size=200),
         dp(age_min=18, age_max=29, value=97, sample_size=150),
         dp(age_min=30, age_max=59, value=96, sample_size=200),
         dp(age_min=60, age_max=200, value=95, sample_size=80)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(
        db, disease="measles",
        scenarios=[{"name": "t1", "coverage": 100.0, "booster": 0.0, "ve": 1.0}],
    ))
    sc = res["scenarios"][0]
    assert sc["effective_barrier_percent"] == 100.0
    assert sc["hit_target_percent"] is not None
    if sc["effective_barrier_percent"] >= sc["hit_target_percent"]:
        assert sc["status"] == "reached"


def test_status_not_reached_when_below_hit():
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=80, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    base = res["scenarios"][0]  # cov=80
    if base["hit_target_percent"] is not None and base["effective_barrier_percent"] + 10 < base["hit_target_percent"]:
        assert base["status"] == "not_reached"


# ============================================================
# 7. 无 rows → 回退文献 R0
# ============================================================

def test_no_rows_falls_back_to_reference_r0():
    db = FakeDB([], [])
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    assert res["hit_target_percent"] is not None  # 文献 R0=15 → HIT=93.3
    assert res["hit_target_source"] in {"who", "literature_r0", "goal"}
    assert res["r0_estimated_from_foi"] is None
    #补种仍可算
    for sc in res["scenarios"]:
        assert sc["required_coverage_to_reach_hit"] is not None or sc["hit_target_percent"] is None


def test_no_disease_no_hit():
    db = FakeDB([], [])
    res = asyncio.run(get_barrier_scenarios(db))
    assert res["hit_target_percent"] is None
    for sc in res["scenarios"]:
        assert sc["status"] == "undetermined"


# ============================================================
# 8. notes / hit_target_source
# ============================================================

def test_notes_hit_source_label():
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=99, sample_size=100),
         dp(age_min=5, age_max=17, value=98, sample_size=200),
         dp(age_min=18, age_max=29, value=97, sample_size=150),
         dp(age_min=30, age_max=59, value=96, sample_size=200),
         dp(age_min=60, age_max=200, value=95, sample_size=80)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    assert any("HIT" in n for n in res["notes"])
    assert res["hit_target_source"] in {"mle_foi", "who", "literature_r0", "goal", "none"}


def test_notes_have_uniformity_assumption():
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=80, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    assert any("均匀免疫" in n or "年龄组" in n for n in res["notes"])


# ============================================================
# 9. 端点已注册（通过 import 验证路由注册）
# ============================================================

def test_endpoint_importable():
    """分析 API 模块能成功导入（端点在模块加载时注册到 router）。"""
    from app.api.v1.analysis import get_barrier_scenarios_api
    assert callable(get_barrier_scenarios_api)


def test_with_snapshot_decorator_chain():
    """with_snapshot 装饰器保留函数名和 doc（@wraps 正常工作）。"""
    from app.api.v1.analysis import get_barrier_scenarios_api
    assert "barrier" in get_barrier_scenarios_api.__name__
    assert "免疫" in (get_barrier_scenarios_api.__doc__ or "")


# ============================================================
# 10. output 能 json 序列化
# ============================================================

def test_output_json_serializable():
    db = FakeDB(
        [dp(age_min=0, age_max=4, value=80, sample_size=100)],
        [],
    )
    res = asyncio.run(get_barrier_scenarios(db, disease="measles"))
    s = json.dumps(res, ensure_ascii=False)
    assert "measles" in s
    assert "baseline" in s
    assert "vaccinate_people" in s
    assert "population_used" in s

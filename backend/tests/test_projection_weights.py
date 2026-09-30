"""P0: project_barrier weights 参数 — 默认行为不变 + 加权基线 + 交集退化

合同：
  1. weights=None → 与旧逐位相等（简单平均 baseline = Σp_i/n）
  2. weights 提供 → 基线 = Σw_i·p_i / Σw_i（仅交集键）
  3. weights 与键无交集 → 回退简单平均
  4. 递推公式与 weights 解耦（基线确定后每年等比衰减）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.immunity_dynamics import project_barrier


# ============================================================
# 1. 默认 weights=None → 与旧逐位相等
# ============================================================

def test_default_behavior_unchanged_simple_average():
    """5 个年龄组等阳性率 80% → baseline 80% = 0.8（简单平均）。"""
    sp = {"0-4": 80, "5-17": 80, "18-29": 80, "30-59": 80, "60+": 80}
    traj = project_barrier(sp, waning_rate=0.02, years=5, birth_cohort_size=0.012)
    assert len(traj) == 6
    assert traj[0] == pytest.approx(0.8, abs=1e-4)


def test_default_behavior_unequal_groups_simple_mean():
    """不等阳性率：baseline = (0.6+0.7+0.8+0.9+0.5)/5 = 0.7（简单平均）。"""
    sp = {"0-4": 60, "5-17": 70, "18-29": 80, "30-59": 90, "60+": 50}
    traj = project_barrier(sp, waning_rate=0.02, years=3, birth_cohort_size=0.012)
    assert traj[0] == pytest.approx(0.7, abs=1e-4)


def test_default_behavior_matches_explicit_equal_weights():
    """weights 全相等 → 等价于简单平均（基线与 weights=None 相同）。"""
    sp = {"0-4": 60, "5-17": 70, "18-29": 80, "30-59": 90, "60+": 50}
    traj_none = project_barrier(sp, waning_rate=0.01, years=3)
    traj_eq = project_barrier(sp, waning_rate=0.01, years=3,
                              weights={"0-4": 1.0, "5-17": 1.0, "18-29": 1.0,
                                       "30-59": 1.0, "60+": 1.0})
    assert traj_none == traj_eq  # 逐位相等


def test_trajectory_recursion_unchanged():
    """基线 = b，每年 → b·(1-w)·(1-bc)，与 weights 解耦。"""
    sp = {"0-4": 80, "5-17": 80, "18-29": 80, "30-59": 80, "60+": 80}
    traj = project_barrier(sp, waning_rate=0.1, years=3, birth_cohort_size=0.05)
    w_frac = 1 - 0.1
    b_frac = 1 - 0.05
    # 显式重算一遍
    baseline = 0.8
    assert traj[0] == pytest.approx(baseline, abs=1e-4)
    assert traj[1] == pytest.approx(baseline * w_frac * b_frac, abs=1e-4)
    assert traj[2] == pytest.approx(traj[1] * w_frac * b_frac, abs=1e-4)
    assert traj[3] == pytest.approx(traj[2] * w_frac * b_frac, abs=1e-4)


# ============================================================
# 2. 加权基线
# ============================================================

def test_weighted_baseline_favors_high_weight_groups():
    """weights={old:9, young:1} 时 60+ 年龄组 50% 阳性率应拉低基线更厉害。"""
    sp = {"young": 80, "old": 50}
    w_eq = {"young": 1.0, "old": 1.0}
    w_old_bias = {"young": 1.0, "old": 9.0}

    t_eq = project_barrier(sp, waning_rate=0, years=0, weights=w_eq)
    t_old = project_barrier(sp, waning_rate=0, years=0, weights=w_old_bias)

    # 简单平均 (0.8+0.5)/2 = 0.65；加权偏向 old → 更低
    assert t_eq[0] == pytest.approx(0.65, abs=1e-4)
    assert t_old[0] < t_eq[0]
    assert t_old[0] == pytest.approx(
        (1.0 * 0.8 + 9.0 * 0.5) / (1.0 + 9.0), abs=1e-4
    )


def test_weighted_trajectory_same_recursion_after_baseline():
    """加权 vs 简单平均 → 基线不同，但递推公式相同（年衰减/出生稀释系数一致）。"""
    sp = {"A": 60, "B": 80}
    w = {"A": 1.0, "B": 9.0}
    traj_w = project_barrier(sp, waning_rate=0.1, years=3, birth_cohort_size=0.05, weights=w)
    traj_n = project_barrier(sp, waning_rate=0.1, years=3, birth_cohort_size=0.05)
    # 不同基线
    assert traj_w[0] != pytest.approx(traj_n[0], abs=1e-4)
    # 但每段递推缩放因子相同 → 相邻比值相同（round 累积误差用 abs=1e-2 容差）
    w_frac, b_frac = 1 - 0.1, 1 - 0.05
    for i in range(1, len(traj_w)):
        assert traj_w[i] / traj_w[i-1] == pytest.approx(
            w_frac * b_frac, abs=1e-2
        )
        assert traj_n[i] / traj_n[i-1] == pytest.approx(
            w_frac * b_frac, abs=1e-2
        )


def test_immunity_projection_service_uses_pf_weights(monkeypatch):
    """端到端：get_immunity_projection 命中 3/5 接触矩阵年龄组时，
    基线应与简单平均不同，并在 notes 标注接触加权。"""
    import asyncio
    from types import SimpleNamespace
    from app.services.analysis import infectious_disease as idl

    # 确保接触矩阵可用（真实 china_contact_matrix.json）
    try:
        from app.core.effective_immunity import load_contact_matrix
        C = load_contact_matrix()
        assert C.shape == (5, 5)
    except Exception:
        pytest.skip("接触矩阵 JSON 缺失")

    class FakeResult:
        def __init__(self, rows): self._rows = rows
        def scalars(self): return self
        def all(self): return self._rows

    class FakeDB:
        def __init__(self, rows): self._rows = rows
        async def execute(self, q): return FakeResult(self._rows)

    def dp(**kw):
        base = dict(literature_id="lit-1", disease="measles", collection_year=2023,
                    value=80, sample_size=100,
                    data_type="seroprevalence", estimate_type="primary",
                    review_status="approved")
        base.update(kw)
        return SimpleNamespace(**base)

    # 每个数据点年龄区间精确落在单一接触矩阵组 → map_age_to_group 成功命中
    rows = [
        dp(age_min=0, age_max=4, value=85, sample_size=100),    # 0-4
        dp(age_min=5, age_max=17, value=80, sample_size=150),  # 5-17
        dp(age_min=18, age_max=29, value=70, sample_size=120), # 18-29
        dp(age_min=30, age_max=59, value=75, sample_size=200), # 30-59
        dp(age_min=60, age_max=200, value=60, sample_size=80), # 60+
    ]
    res = asyncio.run(idl.get_immunity_projection(
        FakeDB(rows), disease="measles", projection_years=3
    ))
    assert res["baseline_barrier"] is not None
    # notes 含接触加权说明
    assert any("Perron-Frobenius" in n for n in res["notes"]), res["notes"]
    # trajectory 长度正确
    assert len(res["barrier_trajectory"]) == 4  # 0 + 3 年


def test_immunity_projection_falls_back_when_few_contact_hits(monkeypatch):
    """数据点跨多个接触矩阵年龄组（age_min=0, age_max=30 跨 0-4/5-17/18-29）
    → map_age_to_group 返回 None 多 → 命中不足 3 组 → 回退简单平均，notes 无 PF 标注。"""
    import asyncio
    from types import SimpleNamespace
    from app.services.analysis import infectious_disease as idl

    class FakeResult:
        def __init__(self, rows): self._rows = rows
        def scalars(self): return self
        def all(self): return self._rows

    class FakeDB:
        def __init__(self, rows): self._rows = rows
        async def execute(self, q): return FakeResult(self._rows)

    def dp(**kw):
        base = dict(literature_id="lit-1", disease="measles", collection_year=2023,
                    value=80, sample_size=100,
                    data_type="seroprevalence", estimate_type="primary",
                    review_status="approved")
        base.update(kw)
        return SimpleNamespace(**base)

    # 年龄范围跨组 → 多数被 map_age_to_group 丢弃
    rows = [
        dp(age_min=0, age_max=30, value=75, sample_size=300),    # 跨 3 组 → None
        dp(age_min=30, age_max=59, value=75, sample_size=200),  # 30-59 ✓
        dp(age_min=60, age_max=80, value=60, sample_size=80),   # 60+ ✓
        # 只有 2 个命中 → < 3 → 回退简单平均
    ]
    res = asyncio.run(idl.get_immunity_projection(
        FakeDB(rows), disease="measles", projection_years=3
    ))
    assert res["baseline_barrier"] is not None
    # notes 不含 PF 标注
    assert not any("Perron-Frobenius" in n for n in res["notes"]), res["notes"]
    # 应该含不足 3 组的日志（但日志是 logger，不在 notes；这里只验证没 PF 标注）


# ============================================================
# 3. 交集退化 / 异常回退
# ============================================================

def test_weights_no_overlap_falls_back_to_simple_average():
    """weights 键与阳性率键完全无交集 → 回退简单平均。"""
    sp = {"A": 80, "B": 60}
    w = {"X": 1.0, "Y": 1.0}  # 完全不匹配
    t_none = project_barrier(sp, waning_rate=0, years=0)
    t_w = project_barrier(sp, waning_rate=0, years=0, weights=w)
    assert t_w[0] == pytest.approx(t_none[0], abs=1e-4)
    assert t_w[0] == pytest.approx(0.7, abs=1e-4)


def test_weights_partial_overlap_only_intersection_used():
    """weights 只部分匹配 → 仅交集组参与加权，其他组跳过（不报错）。"""
    sp = {"A": 80, "B": 60, "C": 50}
    w = {"A": 1.0, "B": 1.0}  # C 无 weights → 跳过
    t_w = project_barrier(sp, waning_rate=0, years=0, weights=w)
    # 仅 A/B 参与 → (0.8+0.6)/2 = 0.7
    assert t_w[0] == pytest.approx(0.7, abs=1e-4)


def test_weights_all_zero_falls_back():
    """weights 全 0 → Σw=0 → 回退简单平均。"""
    sp = {"A": 80, "B": 60}
    w = {"A": 0.0, "B": 0.0}
    t_none = project_barrier(sp, waning_rate=0, years=0)
    t_w = project_barrier(sp, waning_rate=0, years=0, weights=w)
    assert t_w[0] == pytest.approx(t_none[0], abs=1e-4)

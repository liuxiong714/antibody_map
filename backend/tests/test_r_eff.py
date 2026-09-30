"""P0: 新世代矩阵（NGM）残差法 R_eff 测试

覆盖：
  1. 均匀人群解析解：所有 p_i = p → R_eff = r0 × (1 − p)
  2. 全保护 → R_eff = 0，herd_immunity_met = True
  3. 无保护 → R_eff = r0（数值上等于传入 r0）
  4. 边界：空矩阵 / r0≤0 / 退化 NGM
  5. 易感性 susceptibility dict / list / 默认全 1
  6. 旧 effective_barrier 仍然可用（deprecated 但不删除）
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.effective_immunity import (
    AGE_GROUPS_CONTACT,
    r_eff,
    effective_barrier,
    load_contact_matrix,
)

# ============================================================
# 共享夹具
# ============================================================

@pytest.fixture(scope="module")
def rng():
    return np.random.default_rng(42)


@pytest.fixture(scope="module")
def matrix5(rng) -> np.ndarray:
    """5×5 随机非负接触矩阵（非对称）。"""
    return np.abs(rng.normal(1.0, 0.3, (5, 5)))


def _uniform_positivity(p: float) -> dict[str, float]:
    return {g: p for g in AGE_GROUPS_CONTACT}


# ============================================================
# 1. 均匀人群解析解
# ============================================================

@pytest.mark.parametrize("p_percent, r0, expected_r_eff", [
    (0.0, 15.0, 15.0),    # 无保护
    (50.0, 15.0, 7.5),    # 均匀半保护
    (80.0, 15.0, 3.0),    # 高保护
    (90.0, 15.0, 1.5),    # 接近阈值
    (93.3, 15.0, 1.0),    # 刚好 R_eff=1
    (95.0, 15.0, 0.75),   # 过阈值 herd immunity
    (100.0, 15.0, 0.0),   # 全保护
])
def test_uniform_population_analytical(matrix5, p_percent, r0, expected_r_eff):
    """均匀免疫分布：R_eff = r0 × (1 − p)（NGM 残差矩阵整体缩放 1-p）。"""
    res = r_eff(_uniform_positivity(p_percent), matrix5, r0=r0)
    assert res["r_eff"] == pytest.approx(expected_r_eff, abs=0.02)


def test_uniform_population_r_eff_scales_linearly_with_r0(matrix5):
    """r0 翻倍 → R_eff 同比翻倍（均匀免疫下 R_eff 对 r0 线性）。"""
    p = _uniform_positivity(80.0)
    res_a = r_eff(p, matrix5, r0=5.0)
    res_b = r_eff(p, matrix5, r0=10.0)
    res_c = r_eff(p, matrix5, r0=15.0)
    assert res_b["r_eff"] == pytest.approx(2.0 * res_a["r_eff"], abs=1e-4)
    assert res_c["r_eff"] == pytest.approx(3.0 * res_a["r_eff"], abs=1e-4)


# ============================================================
# 2. 全保护 / 无保护 边界
# ============================================================

def test_full_protection_gives_zero(matrix5):
    """p=100% → 残差矩阵全零 → ρ(K)=0 → R_eff=0。"""
    res = r_eff(_uniform_positivity(100.0), matrix5, r0=15.0)
    assert res["r_eff"] == pytest.approx(0.0, abs=1e-6)
    assert res["herd_immunity_met"] is True
    assert res["rho_k"] == pytest.approx(0.0, abs=1e-6)


def test_no_protection_gives_r0(matrix5):
    """p=0% → 残差 NGM 本身 → R_eff = r0。"""
    res = r_eff(_uniform_positivity(0.0), matrix5, r0=15.0)
    assert res["r_eff"] == pytest.approx(15.0, abs=1e-4)
    assert res["rho_k"] == pytest.approx(res["rho_ngm"], abs=1e-6)


def test_no_protection_matches_r0_input(matrix5):
    """任意 r0，无保护下 R_eff 数值上等于传入 r0。"""
    for r0 in [2.5, 5.0, 15.0, 18.0]:
        res = r_eff(_uniform_positivity(0.0), matrix5, r0=r0)
        assert res["r_eff"] == pytest.approx(r0, abs=1e-4)


# ============================================================
# 3. 边界退化
# ============================================================

def test_zero_r0_returns_none(matrix5):
    """r0=0 → 无法归一化，返回 None。"""
    res = r_eff(_uniform_positivity(50.0), matrix5, r0=0.0)
    assert res["r_eff"] is None


def test_empty_matrix_returns_none():
    res = r_eff({}, np.zeros((0, 0)), r0=15.0)
    assert res["r_eff"] is None
    assert res["herd_immunity_met"] is None
    assert res["group_contributions"] == []


def test_zero_contact_matrix_returns_none(rng):
    res = r_eff(_uniform_positivity(50.0), np.zeros((5, 5)), r0=15.0)
    assert res["r_eff"] is None


def test_single_group(matrix5):
    """只有一个年龄组有阳性率，其他 p=0 —— 仍可计算。"""
    pos = {AGE_GROUPS_CONTACT[0]: 90.0}  # 其他隐式 p=0
    res = r_eff(pos, matrix5, r0=15.0)
    # 退化 n=1 均匀公式不严格成立，但应返回有限值
    assert res["r_eff"] is not None
    assert res["r_eff"] > 0


# ============================================================
# 4. susceptibility 入参多态
# ============================================================

def test_susceptibility_dict_and_ndarray_give_same_result(matrix5):
    """dict 按标签匹配 / ndarray 按行顺序 —— 应等价（d 全 1 情况）。"""
    pos = _uniform_positivity(80.0)
    d_dict = {g: 1.0 for g in AGE_GROUPS_CONTACT}
    d_arr = np.ones(5)
    r1 = r_eff(pos, matrix5, r0=15.0, susceptibility=d_dict)
    r2 = r_eff(pos, matrix5, r0=15.0, susceptibility=d_arr)
    r3 = r_eff(pos, matrix5, r0=15.0, susceptibility=None)
    assert r1["r_eff"] == pytest.approx(r2["r_eff"], abs=1e-4)
    assert r2["r_eff"] == pytest.approx(r3["r_eff"], abs=1e-4)


def test_susceptibility_non_uniform_changes_ngm_diagnostics(rng):
    """均匀免疫下 R_eff 恒等于 r0×(1-p)（标量等比缩放），与 susceptibility 无关。
    但 ρ(NGM) 应随 susceptibility 改变（传入 r0 固定后 R_eff 归一化抵消）。"""
    C = np.abs(rng.normal(1.0, 0.3, (5, 5)))
    pos = _uniform_positivity(50.0)
    d_uniform = {g: 1.0 for g in AGE_GROUPS_CONTACT}
    d_diff = {"0-4": 1.0, "5-17": 2.0, "18-29": 1.0, "30-59": 1.0, "60+": 0.5}
    r_uniform = r_eff(pos, C, r0=15.0, susceptibility=d_uniform)
    r_diff = r_eff(pos, C, r0=15.0, susceptibility=d_diff)
    # 均匀免疫：R_eff = r0·(1-p)/ρ(NGM)·ρ(NGM) = r0·(1-p)，与 d 无关
    assert r_uniform["r_eff"] == pytest.approx(r_diff["r_eff"], abs=1e-4)
    # 但 NGM 谱半径不同
    assert r_uniform["rho_ngm"] != pytest.approx(r_diff["rho_ngm"], abs=1e-6)


def test_susceptibility_changes_r_eff_when_non_uniform_immunity(rng):
    """异质免疫 + 异质易感性 → R_eff 偏离 r0×(1-p_avg) 解析解。"""
    C = np.abs(rng.normal(1.0, 0.3, (5, 5)))
    pos_hetero = {"0-4": 90, "5-17": 80, "18-29": 40, "30-59": 30, "60+": 25}
    d_uniform = {g: 1.0 for g in AGE_GROUPS_CONTACT}
    d_diff = {"0-4": 1.0, "5-17": 2.0, "18-29": 1.0, "30-59": 1.0, "60+": 0.5}
    r_uniform = r_eff(pos_hetero, C, r0=15.0, susceptibility=d_uniform)
    r_diff = r_eff(pos_hetero, C, r0=15.0, susceptibility=d_diff)
    # 异质免疫下 susceptibility 确实影响 R_eff
    assert r_uniform["r_eff"] != pytest.approx(r_diff["r_eff"], abs=1e-4)


# ============================================================
# 5. herd_immunity_met 判定 + gap
# ============================================================

@pytest.mark.parametrize("p_percent, r0, expect_met", [
    (93.4, 15.0, True),     # 15·(1-0.934)=0.99 < 1 → 刚好 met
    (95.0, 15.0, True),
    (90.0, 15.0, False),
    (0.0, 15.0, False),
    (100.0, 15.0, True),
])
def test_herd_immunity_met_flag(matrix5, p_percent, r0, expect_met):
    res = r_eff(_uniform_positivity(p_percent), matrix5, r0=r0)
    assert res["herd_immunity_met"] is expect_met


def test_extra_gap_zero_when_met(matrix5):
    res = r_eff(_uniform_positivity(100.0), matrix5, r0=15.0)
    assert res["herd_immunity_met"] is True
    assert res["required_extra_immunity_gap"] == pytest.approx(0.0, abs=1e-6)


def test_extra_gap_positive_when_not_met(matrix5):
    """R_eff > 1 → gap = (R_eff-1)/R_eff > 0。"""
    res = r_eff(_uniform_positivity(80.0), matrix5, r0=15.0)  # R_eff≈3 > 1
    assert res["herd_immunity_met"] is False
    assert res["required_extra_immunity_gap"] > 0
    # 线性近似上限 = R_eff - 1，gap < 此值
    assert res["required_extra_immunity_gap"] < res["r_eff"]


# ============================================================
# 6. group_contributions 贡献结构
# ============================================================

def test_group_contributions_sum_to_one(matrix5):
    """各年龄组贡献分数（残差行和归一化）应加总为 1。"""
    res = r_eff(_uniform_positivity(50.0), matrix5, r0=15.0)
    total = sum(c["contribution_fraction"] for c in res["group_contributions"])
    assert total == pytest.approx(1.0, abs=1e-4)
    assert len(res["group_contributions"]) == 5


def test_group_contributions_struct(matrix5):
    """每个 contribution 有 age_group / positivity_percent / residual_weight / fraction。"""
    res = r_eff(_uniform_positivity(80.0), matrix5, r0=15.0)
    for c in res["group_contributions"]:
        assert set(c.keys()) >= {"age_group", "positivity_percent",
                                 "residual_weight", "contribution_fraction"}
        assert c["age_group"] in AGE_GROUPS_CONTACT


# ============================================================
# 7. 真实 china_contact_matrix
# ============================================================

def test_real_contact_matrix_runs_smoke():
    """加载项目自带 china_contact_matrix.json，用均匀 85% 免疫跑通。"""
    C = load_contact_matrix()
    assert C.shape == (5, 5)
    pos = {g: 85.0 for g in AGE_GROUPS_CONTACT}
    res = r_eff(pos, C, r0=15.0)
    assert res["r_eff"] is not None
    assert 0 < res["r_eff"] <= 15


# ============================================================
# 8. 旧 effective_barrier 仍可用（仅 deprecated 警告，不删）
# ============================================================

def test_effective_barrier_still_works(matrix5):
    """标记 @deprecated 但调用不抛异常，返回结构不变。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        res = effective_barrier(_uniform_positivity(80.0), matrix5)
    assert "effective_barrier" in res
    assert "effective_barrier" not in str([str(x.category) for x in w])  # DeprecationWarning
    # 确认确实产生了 deprecation 警告
    deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(deprecation_warnings) >= 1
    assert "deprecated" in str(deprecation_warnings[0].message).lower() or \
           "r_eff" in str(deprecation_warnings[0].message)

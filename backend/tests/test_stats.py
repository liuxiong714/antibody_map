"""stats.py 单元测试：覆盖正常值、边界（空列表 / 单元素 / p=0/1）与已知数值。"""

import math

import pytest

from app.core.stats import (
    geometric_mean_with_ci,
    weighted_proportion_with_ci,
    weighted_linear_trend,
    gini,
    coefficient_of_variation,
    lowess,
    inverse_variance_meta,
    reliability_grade,
)


class TestGeometricMeanWithCI:
    def test_basic(self):
        res = geometric_mean_with_ci([1, 2, 4, 8])
        assert res["n"] == 4
        assert res["gmc"] == pytest.approx(2.8284, abs=1e-3)
        assert res["ci_lower"] < res["gmc"] < res["ci_upper"]
        assert res["ci_lower"] >= 0

    def test_all_same(self):
        res = geometric_mean_with_ci([5, 5, 5])
        assert res["gmc"] == pytest.approx(5.0)
        assert res["ci_lower"] <= 5.0 <= res["ci_upper"]

    def test_empty(self):
        assert geometric_mean_with_ci([]) == {
            "gmc": None, "ci_lower": None, "ci_upper": None, "n": 0,
        }

    def test_single(self):
        res = geometric_mean_with_ci([10.0])
        assert res["n"] == 1 and res["gmc"] == pytest.approx(10.0)

    def test_known_geometric_mean_1_10_100(self):
        # 已知答案：(1×10×100)^(1/3) = 10
        res = geometric_mean_with_ci([1, 10, 100])
        assert res["n"] == 3
        assert res["gmc"] == pytest.approx(10.0, abs=1e-4)
        assert res["ci_lower"] < 10.0 < res["ci_upper"]

    def test_ignore_nonpositive(self):
        res = geometric_mean_with_ci([0, -1, 2, None])
        assert res["n"] == 1 and res["gmc"] == pytest.approx(2.0)


class TestWeightedProportion:
    def test_equal_proportions(self):
        res = weighted_proportion_with_ci([0.5, 0.5], [100, 200])
        assert res["pooled_proportion"] == pytest.approx(0.5)
        assert res["ci_lower"] <= 0.5 <= res["ci_upper"]
        assert res["n_studies"] == 2

    def test_large_sample_dominates(self):
        # 大样本研究应占更高权重
        res = weighted_proportion_with_ci([0.1, 0.9], [10, 1000])
        assert res["pooled_proportion"] == pytest.approx(0.9, abs=0.01)

    def test_boundary_p0(self):
        res = weighted_proportion_with_ci([0.0, 0.5], [50, 100])
        assert 0.0 <= res["pooled_proportion"] <= 0.5
        assert res["ci_lower"] >= 0.0

    def test_boundary_p1(self):
        res = weighted_proportion_with_ci([1.0, 0.8], [50, 100])
        assert 0.8 <= res["pooled_proportion"] <= 1.0
        assert res["ci_upper"] <= 1.0

    def test_percentage_input(self):
        # 逆方差加权（权重 = n/(p(1-p)) 不同），合并率非简单算术平均 0.55
        res = weighted_proportion_with_ci([50, 60], [100, 100])
        assert res["pooled_proportion"] == pytest.approx(0.55102, abs=1e-4)
        assert 0.5 < res["pooled_proportion"] < 0.6

    def test_empty(self):
        res = weighted_proportion_with_ci([], [])
        assert res["pooled_proportion"] is None and res["n"] == 0 and res["n_studies"] == 0

    def test_invalid_n_skipped(self):
        res = weighted_proportion_with_ci([0.5, 0.5], [0, 100])
        assert res["n_studies"] == 1


class TestWeightedLinearTrend:
    def test_perfect_line(self):
        res = weighted_linear_trend([2010, 2011, 2012, 2013], [10, 20, 30, 40], [1, 1, 1, 1])
        assert res["slope_per_year"] == pytest.approx(10.0)
        assert res["r_squared"] == pytest.approx(1.0)
        assert res["direction"] == "increasing"
        assert res["p_value"] == 0.0

    def test_decreasing(self):
        res = weighted_linear_trend([1, 2, 3], [9, 6, 3])
        assert res["slope_per_year"] == pytest.approx(-3.0)
        assert res["direction"] == "decreasing"

    def test_weights_prioritize(self):
        # 第三点被赋予极大权重，趋势应显著向上
        res = weighted_linear_trend([0, 1, 2], [0, 0, 100], [1, 1, 100])
        assert res["slope_per_year"] > 0
        assert res["direction"] == "increasing"

    def test_flat(self):
        res = weighted_linear_trend([1, 2, 3], [5, 5, 5])
        assert res["direction"] == "flat"
        assert res["slope_per_year"] == pytest.approx(0.0)

    def test_empty(self):
        res = weighted_linear_trend([], [])
        assert res["slope_per_year"] is None and res["direction"] is None and res["n"] == 0

    def test_too_few_points(self):
        res = weighted_linear_trend([2020], [50.0])
        assert res["slope_per_year"] is None and res["direction"] is None


class TestGini:
    def test_equal(self):
        assert gini([1, 1, 1, 1]) == 0.0

    def test_known(self):
        assert gini([0, 0, 1, 1]) == pytest.approx(0.5)

    def test_single(self):
        assert gini([42]) == 0.0

    def test_empty(self):
        assert gini([]) == 0.0

    def test_negative_ignored(self):
        assert gini([1, 2, 3, -5]) == gini([1, 2, 3])


class TestCoefficientOfVariation:
    def test_constant(self):
        assert coefficient_of_variation([10, 10, 10]) == 0.0

    def test_known(self):
        assert coefficient_of_variation([2, 4]) == pytest.approx(math.sqrt(2) / 3, abs=1e-4)

    def test_empty(self):
        assert coefficient_of_variation([]) == 0.0

    def test_single(self):
        assert coefficient_of_variation([7]) == 0.0

    def test_zero_mean(self):
        assert coefficient_of_variation([0, 0, 0]) == 0.0


class TestLowess:
    def test_linear_preserved(self):
        x = list(range(10))
        y = [2.0 * v + 1 for v in x]
        xs, ys = lowess(x, y, frac=0.6)
        assert len(xs) == len(ys) == 10
        for xv, yv in zip(xs, ys):
            assert yv == pytest.approx(2.0 * xv + 1, abs=1e-6)

    def test_sorted_output(self):
        x = [5, 1, 3, 2, 4]
        y = [v * v for v in x]
        xs, ys = lowess(x, y)
        assert xs == sorted(xs)
        assert len(xs) == len(ys)

    def test_quadratic_smooth_close(self):
        x = list(range(20))
        y = [v * v for v in x]
        xs, ys = lowess(x, y, frac=0.6)
        # 平滑点应大致贴合二次曲线（LOWESS 在端点存在局部偏差，故用宽松界限）
        for xv, yv in zip(xs, ys):
            assert abs(yv - xv * xv) < 0.5 * xv + 20

    def test_insufficient(self):
        assert lowess([1], [2]) == ([], [])
        assert lowess([], []) == ([], [])


class TestInverseVarianceMeta:
    def test_homogeneous(self):
        res = inverse_variance_meta([0.5, 0.5], [100, 200], [0.4, 0.4], [0.6, 0.6])
        assert res["pooled_fixed"] == pytest.approx(0.5)
        assert res["i_squared_percent"] == pytest.approx(0.0)
        assert res["k"] == 2

    def test_ci_missing_fallback(self):
        res = inverse_variance_meta([0.5, 0.6], [100, 100], [None, None], [None, None])
        assert 0.5 <= res["pooled_fixed"] <= 0.6
        # 逆方差加权（权重 = 1/var 随 p 变化），非简单算术平均
        assert res["pooled_fixed"] == pytest.approx(0.55102, abs=1e-4)

    def test_boundary_p01(self):
        res = inverse_variance_meta([0.0, 1.0], [50, 50], [None, None], [None, None])
        assert res["k"] == 2
        assert res["i_squared_percent"] >= 0.0
        assert 0.0 <= res["pooled_fixed"] <= 1.0

    def test_empty(self):
        res = inverse_variance_meta([], [], [], [])
        assert res["pooled_fixed"] is None and res["pooled_random"] is None
        assert res["k"] == 0 and res["i_squared_percent"] == 0.0

    def test_random_fixed_keys(self):
        res = inverse_variance_meta([0.3, 0.5, 0.7], [80, 120, 60], [0.2, 0.4, 0.6], [0.4, 0.6, 0.8])
        assert res["pooled_fixed"] is not None
        assert res["pooled_random"] is not None
        assert res["q_statistic"] >= 0.0
        assert res["tau_squared"] >= 0.0


class TestReliabilityGrade:
    def test_grade_a(self):
        assert reliability_grade(1200, True, "high", True, 8) == "A"

    def test_grade_b(self):
        assert reliability_grade(400, True, "high", False, 2) == "B"

    def test_grade_c(self):
        assert reliability_grade(50, False, "medium", True, 1) == "C"

    def test_grade_d(self):
        assert reliability_grade(10, False, "low", False, 1) == "D"

    def test_none_inputs(self):
        assert reliability_grade(None, False, None, False, 0) == "D"

    def test_case_insensitive(self):
        assert reliability_grade(1200, True, "HIGH", True, 8) == "A"


def test_p_zero_one_does_not_raise():
    """p=0 / p=1 时各合并函数不应抛异常。"""
    weighted_proportion_with_ci([0.0, 1.0, 0.3], [10, 20, 30])
    inverse_variance_meta([0.0, 1.0, 0.3], [10, 20, 30], [None, None, None], [None, None, None])

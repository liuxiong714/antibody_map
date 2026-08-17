"""stats_engine.py 单元测试：全局 95% CI 引擎。

覆盖四个纯函数（binomial_ci / weighted_rate_ci / gmc_ci / proportion_test_ci）：
- 已知解析答案用例（Wilson CI x=40,n=100 ≈ [0.309,0.498]；GMC 对数平均；加权率）
- 边界用例（n=0 / 空输入 / 单元素 GMC）
- 小样本 Clopper-Pearson 精确法
- 固定随机种子的 auto 分流一致性
"""

import math
import random

import pytest

from app.core.stats_engine import (
    binomial_ci,
    weighted_rate_ci,
    gmc_ci,
    proportion_test_ci,
    fit_age_curve,
    foi_from_curve,
    fit_catalytic_models,
    cochran_armitage_trend,
    two_proportion_test,
    direct_standardize,
    morans_i,
    g_star,
    classify_hotspot_cluster,
    birth_year_from_age,
    decade_band,
    birth_cohort_analysis,
)


class TestBinomialCI:
    """单比例二项分布 95% CI（Wilson / Clopper-Pearson）。"""

    def test_wilson_known_answer(self):
        # 已知解析答案：x=40, n=100 → Wilson 95% CI ≈ [0.309, 0.498]
        lo, hi = binomial_ci(x=40, n=100)
        assert lo == pytest.approx(0.309, abs=2e-3)
        assert hi == pytest.approx(0.498, abs=2e-3)
        assert lo < 0.4 < hi

    def test_wilson_explicit_method(self):
        # n>=30 时 auto 分流到 wilson
        lo, hi = binomial_ci(x=40, n=100, method="wilson")
        assert lo == pytest.approx(0.309, abs=2e-3)
        assert hi == pytest.approx(0.498, abs=2e-3)

    def test_small_sample_clopper_pearson(self):
        # n<30 时 auto 分流到 Clopper-Pearson（beta 分布精确法）
        # x=0, n=10：下界为 0，上界 ≈ 0.308
        lo, hi = binomial_ci(x=0, n=10)
        assert lo == 0.0
        assert hi == pytest.approx(0.308, abs=1e-2)

    def test_small_sample_explicit_beta(self):
        lo, hi = binomial_ci(x=2, n=10, method="beta")
        assert lo is not None and hi is not None
        assert 0 <= lo <= hi <= 1
        assert lo < 0.2 < hi

    def test_boundary_n_zero(self):
        assert binomial_ci(x=5, n=0) == (None, None)

    def test_boundary_n_none(self):
        assert binomial_ci(x=5, n=None) == (None, None)

    def test_boundary_invalid_n(self):
        assert binomial_ci(x=5, n="abc") == (None, None)

    def test_boundary_negative_n(self):
        assert binomial_ci(x=5, n=-10) == (None, None)

    def test_x_clamped_to_n(self):
        # x 超过 n 时钳制到 n，不抛异常
        lo, hi = binomial_ci(x=150, n=100)
        assert lo is not None and hi is not None
        assert hi <= 1.0

    def test_auto_splits_by_sample_size_fixed_seed(self):
        # 固定随机种子：auto 与显式方法分流一致
        rng = random.Random(20260816)
        for _ in range(50):
            n = rng.randint(1, 120)
            p = rng.random()
            x = int(round(p * n))
            lo_auto, hi_auto = binomial_ci(x, n)
            lo_exp, hi_exp = binomial_ci(x, n, method="wilson" if n >= 30 else "beta")
            assert lo_auto == lo_exp
            assert hi_auto == hi_exp


class TestWeightedRateCI:
    """样本量加权阳性率 + 正态近似 95% CI。"""

    @staticmethod
    def _row(value, sample_size):
        return {"value": value, "sample_size": sample_size}

    def test_known_answer(self):
        # p=[0.5,0.3], n=[100,300] → p̂=0.35；SE=√(25+63)/400=2.345%；CI≈[30.40,39.60]
        res = weighted_rate_ci([self._row(50, 100), self._row(30, 300)])
        assert res["weighted_positivity"] == pytest.approx(35.0, abs=1e-6)
        assert res["ci_lower"] == pytest.approx(30.40, abs=2e-2)
        assert res["ci_upper"] == pytest.approx(39.60, abs=2e-2)
        assert res["n_total"] == 400
        assert res["n_dropped"] == 0
        assert res["method"] == "normal_approx"

    def test_percent_and_ratio_input_mixed(self):
        # 0-1 比例与百分数混用均可
        res = weighted_rate_ci([self._row(0.5, 100), self._row(0.3, 300)])
        assert res["weighted_positivity"] == pytest.approx(35.0, abs=1e-6)

    def test_dropped_when_sample_size_missing(self):
        # 保守起见：任一行 sample_size 缺失则整行剔除并计数
        res = weighted_rate_ci([self._row(50, 100), self._row(30, None), self._row(20, 0)])
        assert res["weighted_positivity"] == pytest.approx(50.0)
        assert res["n_dropped"] == 2
        assert res["n_total"] == 100

    def test_empty(self):
        res = weighted_rate_ci([])
        assert res["weighted_positivity"] is None
        assert res["ci_lower"] is None
        assert res["ci_upper"] is None
        assert res["n_total"] == 0

    def test_all_invalid(self):
        res = weighted_rate_ci([self._row(50, None), self._row(None, 100)])
        assert res["weighted_positivity"] is None

    def test_boundary_p_zero(self):
        # p=0 时方差为 0，CI 收紧为 0
        res = weighted_rate_ci([self._row(0, 100)])
        assert res["weighted_positivity"] == 0.0
        assert res["ci_lower"] == 0.0
        assert res["ci_upper"] == 0.0


class TestGMCCI:
    """GMC 几何均数 + 对数域 95% CI（样本量加权）。"""

    def test_geometric_mean_known_answer(self):
        # 对数平均：ln 10,100,1000 的均值为 ln100 → gmc=100
        res = gmc_ci([10, 100, 1000])
        assert res["gmc"] == pytest.approx(100.0, abs=1e-3)
        assert res["ci_lower"] == pytest.approx(7.389, abs=2e-2)
        assert res["ci_upper"] == pytest.approx(1353.96, abs=2.0)
        assert res["n"] == 3
        assert res["method"] == "lognormal"

    def test_weights_do_not_change_symmetric_mean(self):
        # 对称数据 + 任意权重 → 均值仍为 100，但 CI 收紧
        unweighted = gmc_ci([10, 100, 1000])
        weighted = gmc_ci([10, 100, 1000], weights=[100, 200, 100])
        assert weighted["gmc"] == pytest.approx(100.0, abs=1e-3)
        assert weighted["n_total"] == 400
        assert weighted["ci_upper"] - weighted["ci_lower"] < unweighted["ci_upper"] - unweighted["ci_lower"]

    def test_single_point_ci_none(self):
        # k<2 无法估计标准差 → CI 为 (None, None)
        res = gmc_ci([42.0])
        assert res["gmc"] == pytest.approx(42.0)
        assert res["ci_lower"] is None
        assert res["ci_upper"] is None

    def test_empty(self):
        res = gmc_ci([])
        assert res["gmc"] is None
        assert res["ci_lower"] is None
        assert res["ci_upper"] is None
        assert res["n"] == 0

    def test_non_positive_filtered(self):
        # 非正 / 缺失值剔除
        res = gmc_ci([10, -5, None, 100])
        assert res["gmc"] == pytest.approx(math.sqrt(1000), abs=1e-3)
        assert res["n"] == 2

    def test_invalid_weight_dropped(self):
        # 权重缺失/≤0 的行剔除并计数
        res = gmc_ci([10, 100, 1000], weights=[100, None, 100])
        assert res["n"] == 2
        assert res["n_dropped"] == 1


class TestProportionTestCI:
    """双比例之差的 Wald 近似 95% CI（预留）。"""

    def test_known_answer(self):
        # p1=0.5,n1=100；p2=0.4,n2=100 → d=0.1，SE=0.07 → CI≈[-0.037,0.237]
        res = proportion_test_ci(50, 100, 40, 100)
        assert res["diff"] == pytest.approx(0.1, abs=1e-3)
        assert res["ci_lower"] == pytest.approx(-0.037, abs=2e-2)
        assert res["ci_upper"] == pytest.approx(0.237, abs=2e-2)

    def test_invalid_input(self):
        res = proportion_test_ci(None, 100, 40, 100)
        assert res["diff"] is None
        res2 = proportion_test_ci(50, 0, 40, 100)
        assert res2["diff"] is None


class TestFitAgeCurve:
    """惩罚样条平滑 P(a)：常数水平数据 → 近似水平线；单调数据不误报违规。"""

    def test_constant_p05_outputs_horizontal(self):
        # 40 个年龄点全部 p=0.5（n 随机 50–300）→ 拟合应为近似水平线
        rng = random.Random(20260816)
        records = []
        for age in range(1, 41):
            n = rng.randint(50, 300)
            x = int(round(0.5 * n))
            records.append((float(age), x, n))
        fit = fit_age_curve(records)
        assert fit["spline"] is not None
        assert fit["lambda_smooth"] is not None
        curve = fit["curve"]
        assert len(curve) > 0
        prevs = [pt["prevalence"] for pt in curve]
        # 全部落在 50% ± 5pp（近似水平），且极差 < 5pp
        assert all(45.0 <= pv <= 55.0 for pv in prevs)
        assert max(prevs) - min(prevs) < 5.0

    def test_constant_p05_ci_contains_level(self):
        # 水平数据下置信带应覆盖真实水平 50%
        rng = random.Random(42)
        records = []
        for age in range(1, 41):
            n = rng.randint(50, 300)
            x = int(round(0.5 * n))
            records.append((float(age), x, n))
        fit = fit_age_curve(records)
        assert all(pt["ci_lower"] <= 50.0 <= pt["ci_upper"] for pt in fit["curve"])

    def test_monotonic_increasing_no_violation(self):
        # 真 λ=0.07 单调上升数据不应报单调性违规
        rng = random.Random(7)
        records = []
        for age in range(1, 41):
            p = 1.0 - math.exp(-0.07 * age)
            n = rng.randint(50, 300)
            x = int(round(p * n))
            records.append((float(age), x, n))
        fit = fit_age_curve(records)
        assert fit["monotonic_violation"] is False
        assert fit["age_range"][0] == pytest.approx(1.0)
        assert fit["age_range"][1] == pytest.approx(40.0)

    def test_empty_input(self):
        fit = fit_age_curve([])
        assert fit["spline"] is None
        assert fit["curve"] == []
        assert fit["lambda_smooth"] is None
        assert fit["n_records"] == 0

    def test_curve_dense_half_year_grid(self):
        # 输出 0.5 岁步长网格：年龄连续且相邻间隔为 0.5
        records = [(float(a), 100, 200) for a in range(1, 30)]
        fit = fit_age_curve(records)
        ages = [pt["age"] for pt in fit["curve"]]
        assert len(ages) >= 2
        diffs = {round(b - a, 4) for a, b in zip(ages, ages[1:])}
        assert diffs == {0.5}


class TestFoiFromCurve:
    """年龄别 FOI：λ(a) = P′(a)/(1−P(a))。"""

    def test_numerical_derivative_known_answer(self):
        # 概率尺度可调用对象 P(a)=1−e^(−0.07a)：数值微分应还原 λ≈0.07
        ages = [5.0, 15.0, 25.0, 35.0]
        foi = foi_from_curve(ages, lambda a: 1.0 - math.exp(-0.07 * a))
        for pt in foi:
            assert pt["foi"] is not None
            assert pt["foi"] == pytest.approx(0.07, abs=0.01)

    def test_spline_analytic_derivative(self):
        # 由 fit_age_curve 返回的 logit 尺度样条求 FOI：均值接近真 λ=0.07
        rng = random.Random(20260816)
        lam = 0.07
        records = []
        for age in range(1, 41):
            p = 1.0 - math.exp(-lam * age)
            n = rng.randint(50, 300)
            x = int(round(p * n))
            records.append((float(age), x, n))
        fit = fit_age_curve(records)
        grid = [pt["age"] for pt in fit["curve"]]
        foi = foi_from_curve(grid, fit["spline"])
        vals = [pt["foi"] for pt in foi if pt["foi"] is not None]
        assert len(vals) > 0
        mean_foi = sum(vals) / len(vals)
        assert 0.05 <= mean_foi <= 0.09

    def test_saturation_returns_none(self):
        # P ≥ 0.999 → λ 置 None（分母过小不稳定）
        foi = foi_from_curve([100.0], lambda a: 0.9999)
        assert foi[0]["foi"] is None

    def test_always_non_negative(self):
        # FOI 数值安全：不产生负值
        foi = foi_from_curve([1.0, 2.0, 3.0], lambda a: 1.0 - math.exp(-0.05 * a))
        assert all((pt["foi"] is None) or (pt["foi"] >= 0.0) for pt in foi)


class TestAgeCurveSynthetic:
    """验收：设真 λ=0.07，P(a)=1−e^(−λa) 造 40 个年龄点（n 随机 50–300）。
    接口返回曲线中 25 岁处的拟合 P 应落在 [0.75, 0.90]；FOI 均值接近 0.07（±0.02）。"""

    def test_synthetic_lambda_007(self):
        rng = random.Random(20260816)
        lam = 0.07
        records = []
        for age in range(1, 41):
            p = 1.0 - math.exp(-lam * age)
            n = rng.randint(50, 300)
            x = int(round(p * n))
            records.append((float(age), x, n))

        fit = fit_age_curve(records)
        curve = fit["curve"]
        # 25 岁处拟合 P 应在 [75%, 90%]
        p25 = next(pt["prevalence"] for pt in curve if abs(pt["age"] - 25.0) < 0.5)
        assert 75.0 <= p25 <= 90.0

        # FOI 曲线均值接近 0.07（容差 ±0.02）
        grid = [pt["age"] for pt in curve]
        foi = foi_from_curve(grid, fit["spline"])
        vals = [pt["foi"] for pt in foi if pt["foi"] is not None]
        assert len(vals) > 0
        mean_foi = sum(vals) / len(vals)
        assert 0.05 <= mean_foi <= 0.09


class TestCatalyticModels:
    """催化模型族 MLE 拟合与模型比较（fit_catalytic_models）。

    验收：
    - λ_true=0.08 常数模拟 → 推荐 M1_constant 且 λ 的 95%CI 覆盖 0.08；
    - 带 μ=0.02 的 seroreversion 模拟 → M2 应胜出；
    - 结构：models 按 AIC 升序、最佳 ΔAIC=0、Akaike 权重和为 1、LRT 存在。
    """

    @staticmethod
    def _sim_constant(lam: float, rng: random.Random) -> list:
        records = []
        for age in range(1, 41):
            p = 1.0 - math.exp(-lam * age)
            n = rng.randint(50, 300)
            x = int(round(p * n))
            records.append((float(age), x, n))
        return records

    @staticmethod
    def _sim_seroreversion(lam: float, mu: float, rng: random.Random) -> list:
        s = lam + mu
        records = []
        for age in range(1, 41):
            p = (lam / s) * (1.0 - math.exp(-s * age))
            n = rng.randint(50, 300)
            x = int(round(p * n))
            records.append((float(age), x, n))
        return records

    def test_m1_recommended_lambda_008(self):
        # λ_true=0.08 常数模型模拟 → M1 应为推荐且 λ CI 覆盖 0.08
        rng = random.Random(20260816)
        res = fit_catalytic_models(self._sim_constant(0.08, rng))
        assert res["recommended_model"] == "M1_constant"
        params = res["recommended_params"]
        assert params["lambda_ci_lower"] <= 0.08 <= params["lambda_ci_upper"]
        # 平均 FOI 接近真值 0.08（±0.005）
        assert res["recommended_foi_avg"] == pytest.approx(0.08, abs=5e-3)

    def test_m2_wins_seroreversion(self):
        # λ=0.08, μ=0.02 的 seroreversion 模拟 → M2 应胜出
        rng = random.Random(20260816)
        res = fit_catalytic_models(self._sim_seroreversion(0.08, 0.02, rng))
        assert res["recommended_model"] == "M2_seroreversion"
        m2 = next(m for m in res["models"] if m["name"] == "M2_seroreversion")
        assert m2["params"]["lambda"] == pytest.approx(0.08, abs=2e-2)
        assert m2["params"]["mu"] == pytest.approx(0.02, abs=1.5e-2)
        # M2 的 AIC 应小于 M1
        m1 = next(m for m in res["models"] if m["name"] == "M1_constant")
        assert m2["aic"] < m1["aic"]

    def test_models_sorted_by_aic_and_weights(self):
        rng = random.Random(20260816)
        res = fit_catalytic_models(self._sim_constant(0.08, rng))
        models = res["models"]
        # 按 AIC 升序
        aics = [m["aic"] for m in models]
        assert aics == sorted(aics)
        # 最佳 ΔAIC = 0
        assert models[0]["delta_aic"] == 0.0
        # Akaike 权重和为 1（收敛模型间）
        weights = [m["akaike_weight"] for m in models if m["akaike_weight"] is not None]
        assert sum(weights) == pytest.approx(1.0, abs=1e-4)
        # 推荐模型是 AIC 最小的收敛模型
        assert res["recommended_model"] == models[0]["name"]

    def test_comparison_has_lrt(self):
        rng = random.Random(20260816)
        res = fit_catalytic_models(self._sim_seroreversion(0.08, 0.02, rng))
        lrt = res["comparison"]["lrt"]
        assert lrt is not None
        assert lrt["pair"] == "M1_vs_M2"
        assert lrt["df"] == 1
        # seroreversion 模拟下 M2 应显著优于 M1（p 小）
        assert lrt["p_value"] < 0.05

    def test_fitted_curve_monotonic_ascending(self):
        rng = random.Random(20260816)
        res = fit_catalytic_models(self._sim_constant(0.08, rng))
        curve = res["fitted_curve"]
        assert len(curve) > 0
        ages = [pt["age"] for pt in curve]
        assert ages == sorted(ages)
        prev = -1.0
        for pt in curve:
            assert 0.0 <= pt["prevalence"] <= 100.0
            assert pt["prevalence"] >= prev - 1e-6  # M1/M2 单调不减
            prev = pt["prevalence"]

    def test_empty_records(self):
        res = fit_catalytic_models([])
        assert res["models"] == []
        assert res["recommended_model"] is None
        assert res["fitted_curve"] == []
        assert "无法拟合" in res["modeling_notes"][0]

    def test_invalid_records_filtered(self):
        # 非法记录（age<=0 / n<=0 / 非数值）剔除
        rng = random.Random(20260816)
        good = self._sim_constant(0.08, rng)[:10]
        bad = [(0.0, 5, 10), (5, 5, 0), ("x", "y", "z"), (None, None, None)]
        res = fit_catalytic_models(good + bad)
        assert res["n_records"] == 10
        assert res["recommended_model"] is not None

    def test_small_sample_note(self):
        # <8 个年龄点 → modeling_notes 提示置信度有限
        rng = random.Random(20260816)
        records = self._sim_constant(0.08, rng)[:5]
        res = fit_catalytic_models(records)
        assert any("置信度有限" in n for n in res["modeling_notes"])

    def test_m1_modeling_note_r0_assumption(self):
        # M1 被推荐时给出 R0=λ·L 适用性说明
        rng = random.Random(20260816)
        res = fit_catalytic_models(self._sim_constant(0.08, rng))
        assert any("R0=λ·L" in n for n in res["modeling_notes"])


class TestCochranArmitageTrend:
    """Cochran-Armitage 趋势检验。"""

    def test_monotonic_increasing_significant(self):
        # 构造单调上升 5 年数据 → p<0.05 且 direction_label=上升
        groups = [(2019, 40, 100), (2020, 55, 100), (2021, 60, 100), (2022, 70, 100), (2023, 80, 100)]
        res = cochran_armitage_trend(groups)
        assert res is not None
        assert res["z"] > 0
        assert res["p_value"] < 0.05
        assert res["direction"] == "increasing"
        assert res["direction_label"] == "上升"

    def test_monotonic_decreasing_significant(self):
        groups = [(2019, 80, 100), (2020, 70, 100), (2021, 60, 100), (2022, 45, 100), (2023, 40, 100)]
        res = cochran_armitage_trend(groups)
        assert res is not None
        assert res["z"] < 0
        assert res["p_value"] < 0.05
        assert res["direction"] == "decreasing"
        assert res["direction_label"] == "下降"

    def test_flat_trend_not_significant(self):
        # 大致平稳 → p≥0.05，direction_label=不显著
        groups = [(2019, 50, 100), (2020, 52, 100), (2021, 49, 100), (2022, 51, 100), (2023, 50, 100)]
        res = cochran_armitage_trend(groups)
        assert res is not None
        assert res["p_value"] >= 0.05
        assert res["direction_label"] == "不显著"

    def test_less_than_3_groups_returns_none(self):
        assert cochran_armitage_trend([(2019, 40, 100), (2020, 50, 100)]) is None

    def test_invalid_rows_skipped(self):
        # 非法行被跳过，剩余有效组 <3 → None
        res = cochran_armitage_trend([(2019, 40, 100), (2020, None, None), (2021, None, None)])
        assert res is None

    def test_all_zero_x_returns_none(self):
        # p̄=0 退化，无检验意义
        res = cochran_armitage_trend([(2019, 0, 100), (2020, 0, 100), (2021, 0, 100)])
        assert res is None


class TestTwoProportionTest:
    """两样本率比较：z 检验 + RD/RR 及 95%CI。"""

    def test_significant_difference(self):
        # 40/100 vs 60/100 → 显著差异
        res = two_proportion_test(40, 100, 60, 100)
        assert res["p_value"] < 0.05
        assert res["significant"] is True
        # RD = p1 - p2 = -0.2
        assert res["rd"] == pytest.approx(-0.2, abs=1e-4)
        assert res["rd_ci_upper"] < 0  # 差异方向明确，区间不含 0
        assert res["rr"] == pytest.approx(40 / 60, abs=1e-3)
        assert "差异具有统计学意义" in res["conclusion"]

    def test_equal_rates_not_significant(self):
        res = two_proportion_test(50, 100, 50, 100)
        assert res["significant"] is False
        assert res["rd"] == pytest.approx(0.0, abs=1e-6)
        assert res["rr"] == pytest.approx(1.0, abs=1e-6)

    def test_zero_cell_haldane_correction(self):
        # 0 格触发 0.5 校正，RR 与 CI 仍可计算
        res = two_proportion_test(0, 100, 50, 100)
        assert res["p1"] == pytest.approx(0.5 / 101.0, abs=1e-6)
        assert res["p_value"] < 0.05
        assert res["rr"] is not None
        assert res["significant"] is True

    def test_conclusion_direction_text(self):
        res = two_proportion_test(60, 100, 40, 100)
        assert "高于" in res["conclusion"]
        assert "低于" in two_proportion_test(40, 100, 60, 100)["conclusion"]


class TestDirectStandardize:
    """直接法标准化率（ASR，七普标准人口）。"""

    def test_asr_differs_from_crude_structural_difference(self):
        # 结构性差异：年轻组率高、年老组率低，而标准人口以中老年为主
        strata = [
            ("5-14", 0.85, 400),   # 高阳性率、样本多
            ("25-34", 0.60, 400),
            ("55-64", 0.30, 400),
            ("75-84", 0.15, 400),
        ]
        res = direct_standardize(strata)
        assert res["asr"] is not None
        assert res["crude"] is not None
        # 标准人口中老年权重更大 → ASR 显著低于粗率
        assert res["asr"] < res["crude"]
        # 数值差异应可分辨（>1 个百分点）
        assert (res["crude"] - res["asr"]) > 1.0
        assert res["standard_version"] == "china_pop_2020_v1"

    def test_less_than_3_strata_returns_none(self):
        res = direct_standardize([("5-14", 0.8, 100), ("25-34", 0.6, 100)])
        assert res["asr"] is None
        assert res["crude"] is None
        assert "不足" in res["note"]

    def test_no_strata_returns_none(self):
        res = direct_standardize([])
        assert res["asr"] is None

    def test_weights_aggregation_provided_standard(self):
        # 自定义标准（聚合年龄段），应得到与手算一致的 ASR
        standard = [
            {"group": "5-14", "weight": 0.2, "range": [5, 14]},
            {"group": "25-34", "weight": 0.3, "range": [25, 34]},
            {"group": "55-64", "weight": 0.5, "range": [55, 64]},
        ]
        strata = [("5-14", 0.5, 100), ("25-34", 0.6, 100), ("55-64", 0.4, 100)]
        res = direct_standardize(strata, standard=standard)
        expected = 0.2 * 0.5 + 0.3 * 0.6 + 0.5 * 0.4  # = 0.48
        assert res["asr"] == pytest.approx(expected * 100, abs=1e-4)
        # crude = 样本量加权 = 0.5
        assert res["crude"] == pytest.approx(50.0, abs=1e-4)


class TestSpatialHotspots:
    """空间统计：Moran's I 全局自相关 + Getis-Ord Gi* 局部热点。

    人造 4×4 网格（rook 邻接，行标准化权重 W）：
    - "东高西低"模式：东侧高阳性率、西侧低阳性率 → 正空间自相关，
      应 I > 0 且 p < 0.05；
    - 同一批数值随机洗牌 → 空间分布接近随机，应不显著（|I| 小、p ≥ 0.05）。
    - Gi* 返回逐省 {gi_z, p}，cluster 阈值映射全覆盖。
    """

    @staticmethod
    def _grid_w():
        import numpy as np
        from libpysal.weights import lat2W
        w = lat2W(4, 4)  # 4×4 rook 邻接，row-major 顺序 0..15
        w.transform = "r"
        return w

    @staticmethod
    def _east_high_west_low() -> list:
        # 行主序 4×4：西（左）低、东（右）高 → 强正空间聚集
        return [
            10, 10, 90, 90,
            10, 10, 90, 90,
            20, 20, 80, 80,
            20, 20, 80, 80,
        ]

    def test_east_high_west_low_moran_significant(self):
        import numpy as np
        np.random.seed(20260816)
        res = morans_i(self._east_high_west_low(), self._grid_w())
        assert res is not None
        assert res["I"] > 0.2           # 明显正自相关
        assert res["p_sim"] < 0.05      # 置换检验显著
        assert "聚集" in res["conclusion"]

    def test_random_shuffle_not_significant(self):
        import numpy as np
        vals = self._east_high_west_low()
        random.Random(42).shuffle(vals)  # 打散空间结构
        np.random.seed(20260816)
        res = morans_i(vals, self._grid_w())
        assert res is not None
        # 打散后 |I| 明显小于聚集模式（<0.15 安全线）
        assert abs(res["I"]) < 0.15
        # 置换 p 值不显著（固定种子下确定）
        assert res["p_sim"] >= 0.05

    def test_g_star_returns_per_region(self):
        import numpy as np
        np.random.seed(7)
        w = self._grid_w()
        gi = g_star(self._east_high_west_low(), w)
        assert gi is not None
        assert len(gi) == 16
        # 东高区域应为热点（正 Gi* z），西低区域应为冷点（负 Gi* z）
        east_z = gi[2]["gi_z"]  # 第一行第三列（东侧高值）
        west_z = gi[0]["gi_z"]  # 第一行第一列（西侧低值）
        assert east_z > west_z
        assert all({"gi_z", "p"} <= set(item) for item in gi)

    def test_less_than_8_valid_returns_none(self):
        import numpy as np
        from libpysal.weights import lat2W
        np.random.seed(3)
        w = lat2W(2, 3)  # 6 个单元 < 8
        w.transform = "r"
        assert morans_i([10, 20, 30, 40, 50, 60], w) is None
        assert g_star([10, 20, 30, 40, 50, 60], w) is None

    def test_cluster_threshold_mapping(self):
        # z 阈值：≥2.576 hot_99；≥1.96 hot_95；≥1.645 hot_90；负向对称 cold；其余 ns
        assert classify_hotspot_cluster(3.0) == "hot_99"
        assert classify_hotspot_cluster(2.6) == "hot_99"
        assert classify_hotspot_cluster(2.0) == "hot_95"
        assert classify_hotspot_cluster(1.7) == "hot_90"
        assert classify_hotspot_cluster(-3.0) == "cold_99"
        assert classify_hotspot_cluster(-2.6) == "cold_99"
        assert classify_hotspot_cluster(-2.0) == "cold_95"
        assert classify_hotspot_cluster(-1.7) == "cold_90"
        assert classify_hotspot_cluster(0.5) == "ns"
        assert classify_hotspot_cluster(None) == "ns"
        assert classify_hotspot_cluster("x") == "ns"


class TestBirthCohort:
    """出生队列：birth_year 推算 + 十年段分桶 + (队列, 调查年) 聚合。

    验收：1970s 队列率 95%、2010s 队列率 70% → heatmap 对角差异可见。
    """

    def test_birth_year_inference(self):
        # 已知：2000 年调查、年龄中点 15 → 出生 1985 → 段 1980-1989
        assert birth_year_from_age(2000, 15) == 1985
        assert birth_year_from_age(2000, 15.4) == 1985   # round
        assert birth_year_from_age(2000, 10.5) == 1990
        assert birth_year_from_age(None, 15) is None
        assert birth_year_from_age(2000, None) is None
        assert birth_year_from_age(2000, -1) is None     # 非法负年龄
        assert birth_year_from_age(1800, 15) is None     # 年份越界

    def test_decade_bucket(self):
        assert decade_band(1985) == "1980-1989"
        assert decade_band(1970) == "1970-1979"
        assert decade_band(2009) == "2000-2009"
        assert decade_band(2010) == "2010-2019"
        assert decade_band(None) is None
        assert decade_band("x") is None
        assert decade_band(1700) is None

    def test_1970s_high_2010s_low_diagonal_visible(self):
        # 2000 年调查：1970s 出生（age 25-35，中点30）率 95%；2010s 出生（age 0-9，中点5）率 70%
        records = []
        for i in range(5):   # 每个 cell 2+ 点
            records.append((2000, 30.0, 95.0, 100))   # 1970-1979
            records.append((2000, 30.0, 95.0, 100))
            records.append((2000, 5.0, 70.0, 100))    # 1990-1999（2000-5=1995）
            records.append((2000, 5.0, 70.0, 100))
        res = birth_cohort_analysis(records)
        # y_bands 按字符串排序："1970-1979" < "1990-1999"
        assert res["y_bands"] == ["1970-1979", "1990-1999"]
        # 找 1970s 与 1990s 的率
        rates = {c["birth_year_band"]: c["series"][0]["rate"] for c in res["cohorts"]}
        assert rates["1970-1979"] == pytest.approx(95.0, abs=0.5)
        assert rates["1990-1999"] == pytest.approx(70.0, abs=0.5)
        # 对角差异可见：老队列率显著高于新队列
        assert rates["1970-1979"] - rates["1990-1999"] > 20
        # matrix 行序与 y_bands 一致
        assert res["matrix"][0][0] == pytest.approx(95.0, abs=0.5)  # 1970-1979 行
        assert res["matrix"][1][0] == pytest.approx(70.0, abs=0.5)  # 1990-1999 行

    def test_cell_below_min_points_is_null(self):
        # 单点 cell 不足 2 → rate 置 None
        records = [
            (2000, 30.0, 95.0, 100),   # 1970-1979 只有 1 点
            (2000, 5.0, 70.0, 100),
            (2000, 5.0, 70.0, 100),
        ]
        res = birth_cohort_analysis(records)
        # cohorts 按 y_bands（字符串升序）排列，1970-1979 在前
        assert res["cohorts"][0]["birth_year_band"] == "1970-1979"
        assert res["cohorts"][0]["series"][0]["rate"] is None
        band_1990 = next(c for c in res["cohorts"] if c["birth_year_band"] == "1990-1999")
        assert band_1990["series"][0]["rate"] == pytest.approx(70.0, abs=0.5)
        assert band_1990["series"][0]["ci_lower"] is not None

    def test_dropped_counting(self):
        # 无法推算（无调查年 / 无年龄 / 非法率）的点剔除并计数
        records = [
            (2000, 30.0, 95.0, 100),
            (2000, 30.0, 95.0, 100),
            (None, 30.0, 95.0, 100),     # 无调查年
            (2000, None, 95.0, 100),     # 无年龄
            (2000, 30.0, -1.0, 100),     # 非法率
            (2000, 30.0, 95.0, 0),       # 非法样本量
        ]
        res = birth_cohort_analysis(records)
        assert res["n_records"] == 6
        assert res["dropped"] == 4
        assert len(res["cohorts"]) == 1
        assert res["cohorts"][0]["series"][0]["rate"] == pytest.approx(95.0, abs=0.5)

    def test_multi_year_series(self):
        # 同一队列（出生年份保持在同一十年段）多个调查年 → series 按年升序
        records = []
        for year in (1996, 1998, 2000):   # 年龄中点 15 → 出生 1981/1983/1985 → 均在 1980-1989
            records.append((year, 15.0, 90.0, 100))
            records.append((year, 15.0, 90.0, 100))
        res = birth_cohort_analysis(records)
        assert res["x_years"] == [1996, 1998, 2000]
        assert res["y_bands"] == ["1980-1989"]
        cohort = res["cohorts"][0]
        assert cohort["birth_year_band"] == "1980-1989"
        assert [s["year"] for s in cohort["series"]] == [1996, 1998, 2000]
        assert all(s["rate"] == pytest.approx(90.0, abs=0.5) for s in cohort["series"])



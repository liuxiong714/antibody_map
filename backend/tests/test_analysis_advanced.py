"""新增分析 service 函数测试。

覆盖 7 个新函数：
  get_equity_analysis / get_quality_assessment / get_goal_tracking /
  get_age_curve / get_meta_merge / get_assay_heterogeneity / get_simulation

包含已知答案校验（基尼系数、meta 合并、目标阈值、FOI 反推等），
沿用 test_analysis_gap.py 的 FakeDB 模式，不依赖真实数据库。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.analysis_service import (
    get_equity_analysis,
    get_quality_assessment,
    get_goal_tracking,
    get_age_curve,
    get_meta_merge,
    get_assay_heterogeneity,
    get_simulation,
)


# ── 工具：Fake DB / Fake 数据点 ───────────────────────────

class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    """依次返回每个 execute 对应的结果批次（支持 meta 合并的二次查询）。"""
    def __init__(self, *row_batches):
        self._batches = list(row_batches)
        self.executed_queries = []

    async def execute(self, query):
        self.executed_queries.append(query)
        if self._batches:
            return FakeResult(self._batches.pop(0))
        return FakeResult([])


def dp(**kwargs):
    """构造一个模拟 DataPoint 对象。"""
    base = dict(
        id=uuid4(),
        literature_id=uuid4(),
        disease="measles",
        region=None,
        province=None,
        city=None,
        latitude=None,
        longitude=None,
        age_group=None,
        age_min=None,
        age_max=None,
        sample_size=None,
        data_type="seroprevalence",
        value=None,
        unit=None,
        ci_lower=None,
        ci_upper=None,
        method=None,
        assay=None,
        population=None,
        collection_year=None,
        source_page=None,
        source_context=None,
        source_char_start=None,
        source_char_end=None,
        is_grounded=False,
        estimate_type="primary",
        parent_id=None,
        confidence="medium",
        review_status="approved",
        # 质量分级（meta 合并默认过滤 A+B；mock 默认 A 表示已通过过滤）
        quality_score=None,
        quality_grade="A",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def run(fn, db, *args, **kwargs):
    import asyncio
    return asyncio.run(fn(db, *args, **kwargs))


# ── 1. get_equity_analysis ────────────────────────────────

class TestEquityAnalysis:
    def test_empty(self):
        res = run(get_equity_analysis, FakeDB([]))
        assert res["n_provinces"] == 0
        assert res["summary"]["gini"] is None
        assert res["summary"]["best_province"] is None
        assert res["province_rows"] == []

    def test_gini_equal(self):
        # 两省加权阳性率相同 → 基尼系数 = 0
        db = FakeDB([
            dp(province="北京", value=50, sample_size=100),
            dp(province="广东", value=50, sample_size=100),
        ])
        res = run(get_equity_analysis, db)
        assert res["n_provinces"] == 2
        assert res["summary"]["gini"] == 0.0
        assert res["summary"]["coefficient_of_variation"] == 0.0

    def test_gini_known_unequal(self):
        # 已知答案：加权阳性率 [20,40,60] → 基尼 = (2·Σ(i+1)x)/(n·Σx) - (n+1)/n
        # cum = 1·20 + 2·40 + 3·60 = 280；G = 2·280/(3·120) - 4/3 = 0.222222
        db = FakeDB([
            dp(province="北京", value=20, sample_size=100),
            dp(province="广东", value=60, sample_size=100),
            dp(province="四川", value=40, sample_size=100),
        ])
        res = run(get_equity_analysis, db)
        assert res["summary"]["gini"] == pytest.approx(0.222222, abs=1e-5)
        assert res["summary"]["best_province"] == "广东"
        assert res["summary"]["worst_province"] == "北京"
        assert res["top_provinces"][0]["province"] == "广东"
        assert res["bottom_provinces"][0]["province"] == "北京"

    def test_meeting_target(self):
        # measles 阈值 95%：98 达标、90 未达标 → meeting_ratio = 0.5
        db = FakeDB([
            dp(disease="measles", province="北京", value=98, sample_size=100),
            dp(disease="measles", province="河北", value=90, sample_size=100),
        ])
        res = run(get_equity_analysis, db, disease="measles")
        assert res["summary"]["target_threshold_percent"] == 95
        assert res["summary"]["meeting_ratio"] == 0.5
        assert res["summary"]["meeting_provinces_count"] == 1

    def test_multi_province_semicolon(self):
        db = FakeDB([
            dp(province="北京;天津", value=50, sample_size=100),
        ])
        res = run(get_equity_analysis, db)
        assert res["n_provinces"] == 2
        assert {r["province"] for r in res["province_rows"]} == {"北京", "天津"}


# ── 2. get_quality_assessment ─────────────────────────────

class TestQualityAssessment:
    def test_empty(self):
        res = run(get_quality_assessment, FakeDB([]))
        assert res["total_estimates"] == 0
        assert res["summary"]["high_quality_ratio"] == 0.0
        assert res["single_estimate_provinces"] == []

    def test_grade_distribution_known(self):
        # 北京 5 条高质量（A），河北 1 条低质量（D）
        rows = (
            [dp(province="北京", sample_size=1000, ci_lower=45, ci_upper=55,
                confidence="high", is_grounded=True) for _ in range(5)]
            + [dp(province="河北", sample_size=10, ci_lower=None, ci_upper=None,
                  confidence="low", is_grounded=False)]
        )
        res = run(get_quality_assessment, FakeDB(rows))
        assert res["total_estimates"] == 6
        assert res["grade_distribution"]["A"] == 5
        assert res["grade_distribution"]["D"] == 1
        # 服务端 _ratio 保留 4 位小数
        assert res["summary"]["high_quality_ratio"] == pytest.approx(0.8333, abs=1e-4)
        assert res["summary"]["grade_a_ratio"] == pytest.approx(0.8333, abs=1e-4)
        # 河北仅 1 条主估计 → 证据薄弱预警
        assert "河北" in res["single_estimate_provinces"]
        assert "北京" not in res["single_estimate_provinces"]

    def test_single_estimate_note(self):
        rows = [dp(province="青海", sample_size=50, confidence="medium")]
        res = run(get_quality_assessment, FakeDB(rows))
        assert res["single_estimate_provinces"] == ["青海"]
        assert any("单点估计" in n for n in res["notes"])


# ── 3. get_goal_tracking ──────────────────────────────────

class TestGoalTracking:
    def test_no_disease(self):
        res = run(get_goal_tracking, FakeDB([]), disease=None)
        assert res["goal_threshold_percent"] is None
        assert any("请指定疾病" in n for n in res["notes"])

    def test_unknown_disease(self):
        res = run(get_goal_tracking, FakeDB([]), disease="外星病")
        assert res["goal_threshold_percent"] is None
        assert any("GOAL_THRESHOLDS" in n for n in res["notes"])

    def test_known_threshold_and_meeting(self):
        # measles 阈值 95%
        rows = [
            dp(disease="measles", province="北京", value=98, sample_size=100, collection_year=2020),
            dp(disease="measles", province="河北", value=90, sample_size=100, collection_year=2020),
            dp(disease="measles", province="北京", value=99, sample_size=100, collection_year=2021),
            dp(disease="measles", province="河北", value=99, sample_size=100, collection_year=2021),
        ]
        res = run(get_goal_tracking, FakeDB(rows), disease="measles")
        assert res["goal_threshold_percent"] == 95
        assert res["n_provinces"] == 2
        assert len(res["years"]) == 2
        y2020 = res["years"][0]
        assert y2020["year"] == 2020
        assert y2020["meeting_provinces"] == 1
        assert y2020["meeting_ratio"] == 0.5
        assert y2020["gap_to_hit"] < 0  # 全国加权率已超过 95% 目标
        assert res["latest_year"] == 2021
        assert res["latest_gap_to_hit"] == pytest.approx(-4.0)


# ── 4. get_age_curve ──────────────────────────────────────

class TestAgeCurve:
    def test_empty(self):
        res = run(get_age_curve, FakeDB([]), disease="measles")
        assert res["n_points"] == 0
        assert res["notes"]

    def test_invalid_metric_fallback(self):
        rows = [dp(age_min=1, age_max=2, value=10, sample_size=100)]
        res = run(get_age_curve, FakeDB(rows), disease="measles", metric="bad_metric")
        assert res["metric"] == "seroprevalence"

    def test_linear_series_smoothed(self):
        # 各年龄中点线性递增：LOWESS 应完美保持线性
        rows = [
            dp(age_min=1, age_max=2, value=10, sample_size=100),   # mid 1.5
            dp(age_min=3, age_max=4, value=20, sample_size=100),   # mid 3.5
            dp(age_min=5, age_max=6, value=30, sample_size=100),   # mid 5.5
            dp(age_min=7, age_max=8, value=40, sample_size=100),   # mid 7.5
        ]
        res = run(get_age_curve, FakeDB(rows), disease="measles")
        assert res["n_points"] == 4
        assert res["age_mid_range"] == [1.5, 7.5]
        smoothed = {p["age_mid"]: p["value"] for p in res["smoothed"]}
        assert smoothed[1.5] == pytest.approx(10.0, abs=0.5)
        assert smoothed[7.5] == pytest.approx(40.0, abs=0.5)

    def test_sigmoid_has_inflection(self):
        # S 型曲线应在陡增段检测到拐点
        rows = [
            dp(age_min=0, age_max=1, value=1, sample_size=100),
            dp(age_min=1, age_max=2, value=2, sample_size=100),
            dp(age_min=2, age_max=3, value=5, sample_size=100),
            dp(age_min=3, age_max=4, value=40, sample_size=100),
            dp(age_min=4, age_max=5, value=90, sample_size=100),
            dp(age_min=5, age_max=6, value=95, sample_size=100),
        ]
        res = run(get_age_curve, FakeDB(rows), disease="measles")
        assert res["n_points"] == 6
        assert len(res["inflection_points"]) >= 1
        # 拐点应落在陡增段（age_mid 3~4 附近）
        ip = res["inflection_points"][0]["age_mid"]
        assert 2.5 <= ip <= 5.0

    def test_gmc_metric(self):
        # 同一年龄组两条 gmc 主估计 → 几何均数已知答案：sqrt(10×100) ≈ 31.62
        rows = [
            dp(age_min=1, age_max=2, value=10, sample_size=100, data_type="gmc"),
            dp(age_min=1, age_max=2, value=100, sample_size=100, data_type="gmc"),
            dp(age_min=3, age_max=4, value=100, sample_size=100, data_type="gmc"),
        ]
        res = run(get_age_curve, FakeDB(rows), disease="measles", metric="gmc")
        assert res["metric"] == "gmc"
        assert res["n_points"] == 2
        vals = {p["age_mid"]: p["value"] for p in res["raw_points"]}
        assert vals[1.5] == pytest.approx(31.62, abs=0.1)


# ── 5. get_meta_merge ─────────────────────────────────────

class TestMetaMerge:
    def test_empty(self):
        res = run(get_meta_merge, FakeDB([]), disease="measles")
        assert res["n_provinces"] == 0
        assert res["notes"]

    def test_homogeneous_known_pooled(self):
        # 两研究阳性率相同 → I²=0，合并率 = 50%
        rows = [
            dp(province="北京", value=50, sample_size=100),
            dp(province="北京", value=50, sample_size=200),
        ]
        db = FakeDB(rows, [])  # 第二次查询返回文献标题（空）
        res = run(get_meta_merge, db, disease="measles")
        assert res["n_provinces"] == 1
        prov = res["results"][0]
        assert prov["province"] == "北京"
        assert prov["k"] == 2
        assert prov["pooled_fixed_percent"] == pytest.approx(50.0, abs=1e-4)
        assert prov["i_squared_percent"] == 0.0
        assert prov["heterogeneity"] == "low"

    def test_heterogeneous_high(self):
        # p=0.1 / 0.5 / 0.9（n 相同）→ I² 接近 100% → high
        rows = [
            dp(province="广东", value=10, sample_size=100),
            dp(province="广东", value=50, sample_size=100),
            dp(province="广东", value=90, sample_size=100),
        ]
        db = FakeDB(rows, [])
        res = run(get_meta_merge, db, disease="measles")
        prov = res["results"][0]
        assert prov["k"] == 3
        assert prov["i_squared_percent"] > 50
        assert prov["heterogeneity"] == "high"
        assert 0.3 < prov["pooled_fixed_percent"] / 100 < 0.7


# ── 6. get_assay_heterogeneity ────────────────────────────

class TestAssayHeterogeneity:
    def test_empty(self):
        res = run(get_assay_heterogeneity, FakeDB([]), disease="measles")
        assert res["n_assays"] == 0
        assert res["across_assay_i_squared_percent"] == 0.0

    def test_assay_stratified_known(self):
        # 两种 assay 阳性率相同 → 跨 assay I²=0，合并率 50%
        rows = [
            dp(province="北京", value=50, sample_size=100, assay="ELISA"),
            dp(province="北京", value=50, sample_size=100, assay="IFA"),
        ]
        res = run(get_assay_heterogeneity, FakeDB(rows), disease="measles")
        assert res["n_assays"] == 2
        assert res["across_assay_i_squared_percent"] == 0.0
        assert res["pooled_all_percent"] == pytest.approx(50.0, abs=1e-4)
        assays = {r["assay"] for r in res["results"]}
        assert assays == {"ELISA", "IFA"}

    def test_unknown_assay_label(self):
        rows = [dp(province="北京", value=50, sample_size=100, assay=None)]
        res = run(get_assay_heterogeneity, FakeDB(rows), disease="measles")
        assert res["n_assays"] == 1
        assert res["results"][0]["assay"] == "未注明"

    def test_high_heterogeneity_note(self):
        rows = [
            dp(province="北京", value=10, sample_size=100, assay="ELISA"),
            dp(province="北京", value=90, sample_size=100, assay="IFA"),
        ]
        res = run(get_assay_heterogeneity, FakeDB(rows), disease="measles")
        assert res["across_assay_i_squared_percent"] > 50
        assert any("异质性较高" in n for n in res["notes"])


# ── 7. get_simulation ─────────────────────────────────────

class TestSimulation:
    def test_empty(self):
        res = run(get_simulation, FakeDB([]), disease="measles")
        assert res["current"] is None
        assert res["simulated"] is None
        assert res["notes"]

    def test_high_seroprevalence_reached(self):
        # 观测阳性率 95%（measles）→ 催化模型反推 FOI → R0 → HIT ≈ 94.4%
        # current_status = reached；模拟（覆盖 90%+0 加强）→ near
        rows = [dp(disease="measles", age_min=10, age_max=15, value=95, sample_size=100)]
        res = run(get_simulation, FakeDB(rows), disease="measles")
        cur = res["current"]
        assert cur["status"] == "reached"
        assert cur["weighted_positivity_percent"] == pytest.approx(95.0, abs=1e-4)
        assert cur["estimated_r0"] is not None and cur["estimated_r0"] > 1
        assert cur["hit_percent"] is not None
        assert res["simulated"]["status"] == "near"
        assert res["simulated"]["effective_coverage_percent"] == pytest.approx(90.0, abs=1e-4)
        # 反推：无加强针时需覆盖 ≈ HIT% 才能达标
        assert res["required_coverage_to_reach_hit"] is not None
        assert 90 < res["required_coverage_to_reach_hit"] <= 100

    def test_booster_gain(self):
        # 覆盖 60% + 加强 50% → effective = 60 + 0.4·50 = 80%
        rows = [dp(disease="measles", age_min=5, age_max=10, value=80, sample_size=100)]
        res = run(get_simulation, FakeDB(rows), disease="measles",
                  assumed_coverage=60, booster_rate=50)
        assert res["simulated"]["effective_coverage_percent"] == pytest.approx(80.0, abs=1e-4)
        assert res["simulated"]["gain_from_booster_percent"] == pytest.approx(20.0, abs=1e-4)

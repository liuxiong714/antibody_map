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

    def first(self):
        return self._rows[0] if self._rows else None


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

    def test_small_sample_excluded_from_ranking(self):
        # F32：累计样本量 < MIN_SAMPLE_FOR_META(30) 的省不进入 Top/Bottom 与离散度
        db = FakeDB([
            dp(province="北京", value=99, sample_size=10),   # 高阳性但样本仅 10
            dp(province="广东", value=40, sample_size=100),
            dp(province="四川", value=35, sample_size=100),
            dp(province="河北", value=30, sample_size=100),
        ])
        res = run(get_equity_analysis, db)
        top_names = {r["province"] for r in res["top_provinces"]}
        assert "北京" not in top_names, "样本不足的省份不应进入 Top 排名"
        assert "广东" in top_names
        # 北京无 rank，且不参与基尼离散度
        bj = next(r for r in res["province_rows"] if r["province"] == "北京")
        assert bj["rank"] is None
        assert any("样本量" in n for n in res["notes"])

    def test_age_standardized_ranking(self):
        # F32：具备年龄分层时排名基于年龄标化阳性率
        # 北京全年龄段阳性率恒为 50% → 任意年龄标化后 ASR 必然仍为 50（均匀率的标化不变性）
        # 广东各年龄段率不同 → 触发 direct_standardize，is_age_standardized 为 True
        db = FakeDB([
            dp(province="广东", age_min=0, age_max=0, value=80, sample_size=100),
            dp(province="广东", age_min=1, age_max=4, value=70, sample_size=100),
            dp(province="广东", age_min=5, age_max=14, value=60, sample_size=100),
            dp(province="广东", age_min=15, age_max=59, value=50, sample_size=100),
            dp(province="广东", age_min=60, age_max=200, value=40, sample_size=100),
            dp(province="北京", age_min=0, age_max=0, value=50, sample_size=100),
            dp(province="北京", age_min=1, age_max=4, value=50, sample_size=100),
            dp(province="北京", age_min=5, age_max=14, value=50, sample_size=100),
            dp(province="北京", age_min=15, age_max=59, value=50, sample_size=100),
            dp(province="北京", age_min=60, age_max=200, value=50, sample_size=100),
        ])
        res = run(get_equity_analysis, db)
        gd = next(r for r in res["province_rows"] if r["province"] == "广东")
        bj = next(r for r in res["province_rows"] if r["province"] == "北京")
        # 两省均完成年龄标化
        assert gd["is_age_standardized"] is True and gd["asr"] is not None
        assert gd["n_strata"] >= 3
        assert bj["is_age_standardized"] is True
        # 均匀率标化不变性：北京 ASR == 加权率 == 50
        assert bj["asr"] == pytest.approx(50.0, abs=1e-6)
        assert bj["asr"] == pytest.approx(bj["weighted_positivity"], abs=1e-6)
        # 排名键使用标化率（std_positivity）：北京标化率确定，广东非均匀率标化参与排名
        assert any("年龄标化" in n for n in res["notes"])


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
        # 第 1 个批次为空：get_goal_threshold 查阈值配置表（回退默认 95%）
        # 第 2 个批次为数据行：基础查询
        res = run(get_goal_tracking, FakeDB([], rows), disease="measles")
        assert res["goal_threshold_percent"] == 95
        assert res["n_provinces"] == 2
        assert len(res["years"]) == 2
        y2020 = res["years"][0]
        assert y2020["year"] == 2020
        assert y2020["meeting_provinces"] == 1
        assert y2020["meeting_ratio"] == 0.5
        # 2020 全国加权率 = (100·98 + 100·90)/200 = 94.0，落后目标 95% 缺口 +1.0
        assert y2020["gap_to_hit"] == pytest.approx(1.0)
        assert res["latest_year"] == 2021
        assert res["latest_gap_to_hit"] == pytest.approx(-4.0)


# ── 4. get_age_curve ──────────────────────────────────────

class TestAgeCurve:
    def test_empty(self):
        res = run(get_age_curve, FakeDB([]), disease="measles")
        assert res["n_points"] == 0
        assert res["curve"] == []
        assert res["points"] == []
        assert res["foi_curve"] == []
        assert res["meta"]["lambda_smooth"] is None

    def test_insufficient_points_returns_empty_curve(self):
        # 数据点不足 8 个时不拟合样条，返回空 curve / foi_curve
        rows = [
            dp(age_min=1, age_max=2, value=10, sample_size=100),   # mid 1.5
            dp(age_min=3, age_max=4, value=20, sample_size=100),   # mid 3.5
            dp(age_min=5, age_max=6, value=30, sample_size=100),   # mid 5.5
            dp(age_min=7, age_max=8, value=40, sample_size=100),   # mid 7.5
        ]
        res = run(get_age_curve, FakeDB(rows), disease="measles")
        assert res["n_points"] == 4
        assert res["curve"] == []
        assert res["foi_curve"] == []
        # 各点按 age_mid 聚合，prevalence 为值百分比
        by_mid = {p["age_mid"]: p for p in res["points"]}
        assert set(by_mid) == {1.5, 3.5, 5.5, 7.5}
        assert by_mid[1.5]["prevalence"] == pytest.approx(10.0, abs=0.01)
        assert by_mid[7.5]["prevalence"] == pytest.approx(40.0, abs=0.01)
        assert res["meta"]["dropped_points"] == 0

    def test_aggregates_same_age_mid(self):
        # 同一年龄中点合并阳性数 x 与样本量 n：10/100 与 20/100 → 15/200 = 7.5%
        rows = [
            dp(age_min=1, age_max=2, value=10, sample_size=100),
            dp(age_min=1, age_max=2, value=20, sample_size=100),
        ]
        res = run(get_age_curve, FakeDB(rows), disease="measles")
        assert res["n_points"] == 1
        pt = res["points"][0]
        assert pt["age_mid"] == 1.5
        assert pt["n"] == 200
        assert pt["prevalence"] == pytest.approx(15.0, abs=0.01)

    def test_linear_series_smoothed(self):
        # 8 个年龄中点线性递增达到最小点数阈值 → 惩罚样条拟合出曲线
        rows = [
            dp(age_min=i, age_max=i + 1, value=v, sample_size=100)
            for i, v in zip(range(1, 16, 2), range(10, 90, 10))
        ]
        res = run(get_age_curve, FakeDB(rows), disease="measles")
        assert res["n_points"] == 8
        assert res["curve"], "足够点数时应拟合出样条曲线"
        assert all({"age", "prevalence", "ci_lower", "ci_upper"} <= set(c)
                   for c in res["curve"])
        assert res["meta"]["lambda_smooth"] is not None
        assert res["meta"]["monotonic_violation"] is False  # 递增曲线无下降段
        assert res["foi_curve"], "应产出年龄别 FOI"

    def test_sigmoid_shows_flat_tails(self):
        # S 型曲线两端平坦：FOI（力传染）在平台期应接近 0
        rows = [
            dp(age_min=i, age_max=i + 1, value=v, sample_size=100)
            for i, v in zip(range(1, 16, 2), [1, 5, 15, 40, 85, 92, 95, 96])
        ]
        res = run(get_age_curve, FakeDB(rows), disease="measles")
        assert res["n_points"] == 8
        assert res["curve"]
        foi = res["foi_curve"]
        assert foi, "应产出年龄别 FOI"
        # 极低成本/极高饱和端 FOI 相对大于中段陡增前的较低值（仅做结构校验）
        assert all("age" in pt and "foi" in pt for pt in foi)


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

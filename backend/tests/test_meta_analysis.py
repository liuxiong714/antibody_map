"""meta_proportion（Freeman-Tukey 双反正弦随机效应 Meta 合并）单元测试。

覆盖：
- 与 metafor（R）PFT 口径一致的独立参考实现逐项核对（Q / Q_p / I² / τ² / 双模型）
- 纯齐性数据（各研究 t 相同）→ I²=0、τ²=0、固定效应；τ²=0 时随机 == 固定
- 异质性数据 → 模型选择规则（Q 检验 p<0.10 或 I²>50% 用随机效应）
- k==1 返回二项 CI；k==0 返回 None；k>=10 附带 funnel + egger
- per_study 含 weight / transformed 字段
- get_meta_analysis service：无 group_by 全量合并 / group_by 分组 + Q_between
- 波及改造：get_trend / get_region_compare / get_age_stratify 输出 rate_weighted_legacy 与 meta
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import scipy.stats as sps

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.stats_engine import meta_proportion
from app.services.analysis_service import (
    get_meta_analysis,
    get_trend,
    get_region_compare,
    get_age_stratify,
)


# ════════════════════════════════════════════════════════════
# 独立参考实现（与 metafor::escalc(measure="PFT") + rma.uni 口径一致）
# ════════════════════════════════════════════════════════════

def _ref_ft(x: float, n: float) -> float:
    """Freeman-Tukey 双反正弦变换（参考实现，用于交叉核对）。"""
    return math.asin(math.sqrt(x / (n + 1.0))) + math.asin(math.sqrt((x + 1.0) / (n + 1.0)))


def _ref_meta(studies: list[tuple[float, float, str]]) -> dict:
    """独立实现规格中的固定/随机效应 + DL τ² + 模型选择。"""
    ts = [_ref_ft(x, n) for x, n, _ in studies]
    vs = [1.0 / (n + 0.5) for _, n, _ in studies]
    w_fe = [1.0 / v for v in vs]

    t_fe = sum(w * t for w, t in zip(w_fe, ts)) / sum(w_fe)
    Q = sum(w * (t - t_fe) ** 2 for w, t in zip(w_fe, ts))
    df = len(studies) - 1
    Q_p = float(sps.chi2.sf(Q, df))
    I2 = max(0.0, (Q - df) / Q) * 100.0 if Q > 0 else 0.0

    w2 = sum(w * w for w in w_fe)
    C = sum(w_fe) - w2 / sum(w_fe)
    tau2 = max(0.0, (Q - df) / C) if C > 0 and Q > df else 0.0

    w_re = [1.0 / (v + tau2) for v in vs]
    t_re = sum(w * t for w, t in zip(w_re, ts)) / sum(w_re)
    se_re = math.sqrt(1.0 / sum(w_re))

    use_random = (Q_p < 0.10) or (I2 > 50.0)
    return dict(Q=Q, df=df, Q_p=Q_p, I2=I2, tau2=tau2, t_fe=t_fe, t_re=t_re,
                se_re=se_re, use_random=use_random)


# 8 项研究的手造比例集（(x, n, label)）
STUDIES_8 = [
    (15, 100, "研究1"), (30, 200, "研究2"), (8, 50, "研究3"),
    (50, 250, "研究4"), (25, 150, "研究5"), (60, 300, "研究6"),
    (12, 80, "研究7"), (40, 220, "研究8"),
]


# ════════════════════════════════════════════════════════════
# meta_proportion 纯函数
# ════════════════════════════════════════════════════════════

class TestMetaProportionReference:
    """与独立参考实现逐项核对（metafor PFT 口径）。"""

    def test_8_studies_matches_reference(self):
        ref = _ref_meta(STUDIES_8)
        out = meta_proportion(STUDIES_8)
        pooled = out["pooled"]

        assert pooled["k"] == 8
        assert pooled["Q"] == pytest.approx(ref["Q"], rel=1e-6)
        assert pooled["Q_p"] == pytest.approx(ref["Q_p"], rel=1e-6)
        assert pooled["I2"] == pytest.approx(ref["I2"], rel=1e-6)
        assert pooled["tau2"] == pytest.approx(ref["tau2"], rel=1e-6)

        # 主模型选择规则：Q 检验 p<0.10 或 I²>50% → 随机效应
        expected_model = "random" if ref["use_random"] else "fixed"
        assert out["primary_model"] == expected_model
        assert pooled["model"] == expected_model

    def test_per_study_fields(self):
        out = meta_proportion(STUDIES_8)
        assert len(out["per_study"]) == 8
        for s in out["per_study"]:
            assert "label" in s and "x" in s and "n" in s
            assert "weight" in s and "transformed" in s
            # transformed 应与 FT 变换一致
            assert s["transformed"] == pytest.approx(_ref_ft(s["x"], s["n"]), rel=1e-6)
        # 主模型权重之和 ≈ 100%
        assert sum(s["weight"] for s in out["per_study"]) == pytest.approx(100.0, abs=1.0)

    def test_known_answer_8_studies(self):
        """已知解析答案（离线独立计算核对的固定值，避免参考实现同源）。"""
        out = meta_proportion(STUDIES_8)
        pooled = out["pooled"]
        # 以下数值来自独立计算（scipy），与 metafor PFT 实现一致；
        # 该 8 项集合近乎齐性 → I²=0、τ²=0、固定效应
        assert pooled["Q"] == pytest.approx(3.847383, abs=1e-4)
        assert pooled["Q_p"] == pytest.approx(0.797179, abs=1e-4)
        assert pooled["I2"] == pytest.approx(0.0, abs=1e-2)
        assert pooled["tau2"] == pytest.approx(0.0, abs=1e-6)
        assert pooled["model"] == "fixed"
        # 合并阳性率（各研究 15%-20%，FT 逆变换）≈ 17.66%
        assert pooled["rate"] == pytest.approx(17.66, abs=0.05)


class TestHomogeneity:
    """纯齐性数据：I²=0、τ²=0、固定效应；τ²=0 时随机 == 固定。"""

    @staticmethod
    def _homogeneous():
        # 相同 n 与 x → t 完全相同 → Q=0
        return [(60, 200, f"研究{i}") for i in range(1, 6)]

    def test_i2_zero_for_homogeneous(self):
        out = meta_proportion(self._homogeneous())
        pooled = out["pooled"]
        assert pooled["Q"] == 0.0
        assert pooled["Q_p"] == pytest.approx(1.0)
        assert pooled["I2"] == 0.0
        assert pooled["tau2"] == 0.0
        assert pooled["model"] == "fixed"
        assert out["primary_model"] == "fixed"

    def test_tau2_zero_fixed_equals_random(self):
        """τ²=0 时随机效应权重退化为固定效应权重 → 两模型合并 t 一致。"""
        studies = self._homogeneous()
        out = meta_proportion(studies)
        # 主模型为 fixed；独立计算随机效应（τ²=0）应与固定效应 t 一致
        ref = _ref_meta(studies)
        assert ref["tau2"] == 0.0
        assert ref["t_re"] == pytest.approx(ref["t_fe"], rel=1e-12)
        # 且合并率在两模型下相同（注意 rate 为百分数，逆变换结果需 ×100）
        assert out["pooled"]["rate"] == pytest.approx(
            meta_proportion_with_re_only_for_test(studies) * 100.0, abs=1e-4
        )


def meta_proportion_with_re_only_for_test(studies):
    """仅用随机效应（τ²=0）计算的合并率，用于验证随机==固定。"""
    ts = [_ref_ft(x, n) for x, n, _ in studies]
    vs = [1.0 / (n + 0.5) for _, n, _ in studies]
    w_re = [1.0 / v for v in vs]  # τ²=0 → w_re = w_fe
    t_re = sum(w * t for w, t in zip(w_re, ts)) / sum(w_re)
    n_rep = len(studies) / sum(1.0 / n for _, n, _ in studies)
    return _ft_inverse_p(t_re, n_rep)


def _ft_inverse_p(t: float, n: float) -> float:
    """数值逆变换（与 stats_engine._ft_inverse 同口径）。"""
    from scipy.optimize import brentq

    t = max(0.0, min(float(t), math.pi))
    n1 = n + 1.0
    t0 = math.asin(math.sqrt(1.0 / n1))
    t1 = math.asin(math.sqrt(n / n1)) + math.pi / 2.0
    if t <= t0:
        return 0.0
    if t >= t1:
        return 1.0

    def _f(p):
        return _ref_ft(p * n, n) - t

    return brentq(_f, 0.0, 1.0, xtol=1e-6)


class TestHeterogeneity:
    """异质性数据 → 随机效应。"""

    def test_random_selected_when_heterogeneous(self):
        # 故意制造强异质性：p 从 0.05 到 0.90 拉大差异
        studies = [
            (5, 100, "A"), (10, 100, "B"), (30, 100, "C"), (50, 100, "D"),
            (70, 100, "E"), (90, 100, "F"),
        ]
        out = meta_proportion(studies)
        ref = _ref_meta(studies)
        pooled = out["pooled"]
        assert ref["I2"] > 50.0
        # I2 在实现中被 round 到 2 位小数
        assert pooled["I2"] == pytest.approx(ref["I2"], abs=0.01)
        assert pooled["tau2"] > 0.0
        assert out["primary_model"] == "random"
        assert pooled["model"] == "random"
        # 随机效应主结果
        assert pooled["rate"] > 0 and pooled["rate"] < 100
        assert pooled["ci_lower"] <= pooled["rate"] <= pooled["ci_upper"]

    def test_heterogeneous_returns_fixed_too(self):
        """随机效应为主时同时返回 pooled_fixed 供比对。"""
        studies = [
            (5, 100, "A"), (10, 100, "B"), (30, 100, "C"), (50, 100, "D"),
            (70, 100, "E"), (90, 100, "F"),
        ]
        out = meta_proportion(studies)
        assert out["primary_model"] == "random"
        assert "pooled_fixed" in out
        assert out["pooled_fixed"]["model"] == "fixed"


class TestEdgeCases:
    def test_k1_returns_binomial_ci(self):
        out = meta_proportion([(30, 100, "单研究")])
        pooled = out["pooled"]
        assert pooled["k"] == 1
        assert pooled["model"] == "single_study"
        assert out["primary_model"] == "single_study"
        assert pooled["rate"] == pytest.approx(30.0, abs=0.1)
        # 30/100 的 95% Wilson CI ≈ [21.7, 39.9]
        assert 21.0 < pooled["ci_lower"] < 22.5
        assert 38.0 < pooled["ci_upper"] < 41.0
        assert out["per_study"][0]["weight"] == 100.0
        assert "transformed" in out["per_study"][0]

    def test_k0_returns_none(self):
        out = meta_proportion([])
        assert out["pooled"]["rate"] is None
        assert out["pooled"]["k"] == 0
        assert out["per_study"] == []
        assert out["notes"]

    def test_invalid_rows_skipped(self):
        # 非法样本量 / 非法比例被跳过，不抛异常
        studies = [(30, 100, "A"), (None, 50, "B"), (10, 0, "C"), (0.5, 100, "D"), (5, -1, "E")]
        out = meta_proportion(studies)
        # 仅 A(30,100) 与 D(0.5,100) 有效；B(x=None)、C(n=0)、E(n<0) 被跳过
        assert out["pooled"]["k"] == 2

    def test_k10_funnel_and_egger(self):
        # 12 项研究 → 附带漏斗图与 Egger 检验
        studies = [(5, 100, f"S{i}") for i in range(12)]
        out = meta_proportion(studies)
        assert out["funnel"] is not None
        assert len(out["funnel"]) == 12
        assert all("t" in pt and "sqrt_n" in pt for pt in out["funnel"])
        assert out["egger"] is not None
        assert "intercept" in out["egger"] and "p_value" in out["egger"]

    def test_k_lt10_no_funnel(self):
        out = meta_proportion(STUDIES_8)
        assert out["funnel"] is None
        assert out["egger"] is None


# ════════════════════════════════════════════════════════════
# get_meta_analysis service（FakeDB）
# ════════════════════════════════════════════════════════════

class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, *row_batches):
        self._batches = list(row_batches)
        self.executed_queries = []

    async def execute(self, query):
        self.executed_queries.append(query)
        if self._batches:
            return FakeResult(self._batches.pop(0))
        return FakeResult([])


def _sp_dp(lit_id, value, ss, province="广东", year=2020, age_min=None, age_max=None,
           data_type="seroprevalence", quality_grade="A"):
    return SimpleNamespace(
        literature_id=lit_id, value=value, sample_size=ss, province=province,
        collection_year=year, age_min=age_min, age_max=age_max,
        data_type=data_type, review_status="approved", quality_grade=quality_grade,
    )


class TestGetMetaAnalysis:
    def test_no_group_by_merges_all(self):
        l1, l2 = uuid4(), uuid4()
        rows = [
            _sp_dp(l1, 15.0, 100, province="广东"),
            _sp_dp(l1, 30.0, 200, province="广东"),   # 同文献多个估计
            _sp_dp(l2, 8.0, 50, province="浙江"),
        ]
        title_rows = [(l1, "文献甲"), (l2, "文献乙")]
        db = FakeDB(rows, title_rows)
        out = asyncio_run(get_meta_analysis(db=db, disease="measles"))

        assert out["group_by"] is None
        assert len(out["groups"]) == 1
        group = out["groups"][0]
        meta = group["meta"]
        assert meta["pooled"]["k"] == 3
        assert "I2" in meta["pooled"]
        assert len(meta["per_study"]) == 3
        # 标签来自标题表（带采集年份后缀）
        labels = {s["label"] for s in meta["per_study"]}
        assert any(l.startswith("文献甲") for l in labels)
        assert any(l.startswith("文献乙") for l in labels)

    def test_group_by_province_with_q_between(self):
        l1, l2, l3 = uuid4(), uuid4(), uuid4()
        rows = [
            _sp_dp(l1, 15.0, 100, province="广东"),
            _sp_dp(l2, 40.0, 100, province="浙江"),
            _sp_dp(l3, 60.0, 100, province="四川"),
        ]
        title_rows = [(l1, "A"), (l2, "B"), (l3, "C")]
        db = FakeDB(rows, title_rows)
        out = asyncio_run(get_meta_analysis(db=db, disease="measles", group_by="province"))

        assert out["group_by"] == "province"
        groups = {g["group"]: g for g in out["groups"]}
        assert set(groups.keys()) == {"广东", "浙江", "四川"}
        # 每组 k==1（单研究）→ 直接返回二项 CI
        for g in out["groups"]:
            assert g["meta"]["pooled"]["model"] == "single_study"
        # 组间 Q_between
        assert out["q_between"] is not None
        assert "Q_between" in out["q_between"]
        assert out["q_between"]["df"] == 2
        # Cochran 分解不变式：Q_total = Q_within + Q_between
        qb = out["q_between"]
        assert qb["Q_between"] == pytest.approx(qb["Q_total"] - qb["Q_within"], abs=1e-2)
        assert qb["Q_between"] >= 0

    def test_no_valid_studies(self):
        db = FakeDB([])
        out = asyncio_run(get_meta_analysis(db=db, disease="measles"))
        assert out["groups"][0]["meta"]["pooled"]["rate"] is None
        assert out["groups"][0]["n_studies"] == 0


# ════════════════════════════════════════════════════════════
# 波及改造：get_trend / get_region_compare / get_age_stratify
# ════════════════════════════════════════════════════════════

class TestRefactoredCells:
    def test_get_trend_has_legacy_and_meta(self):
        l1, l2 = uuid4(), uuid4()
        rows = [
            _sp_dp(l1, 10.0, 100, year=2020),
            _sp_dp(l2, 20.0, 100, year=2020),
            _sp_dp(l1, 15.0, 100, year=2021),
        ]
        db = FakeDB(rows)
        out = asyncio_run(get_trend(db=db, disease="measles"))
        assert len(out["trend"]) == 2
        for t in out["trend"]:
            assert "rate_weighted_legacy" in t  # @deprecated 旧样本量加权值
            assert "meta" in t
            assert t["weighted_positivity"] is not None
        assert out["trend"][0]["meta"]["k"] == 2

    def test_get_region_compare_has_legacy_and_meta(self):
        l1, l2 = uuid4(), uuid4()
        rows = [
            _sp_dp(l1, 10.0, 100, province="广东"),
            _sp_dp(l2, 30.0, 100, province="广东"),
            _sp_dp(l1, 20.0, 100, province="浙江"),
        ]
        db = FakeDB(rows)
        out = asyncio_run(get_region_compare(db=db, disease="measles"))
        gd = next(r for r in out if r["province"] == "广东")
        assert gd["avg_positivity"] is not None
        assert "rate_weighted_legacy" in gd
        assert gd["meta"]["k"] == 2

    def test_get_age_stratify_has_legacy_and_meta(self):
        l1, l2 = uuid4(), uuid4()
        rows = [
            _sp_dp(l1, 10.0, 100, age_min=1, age_max=4),
            _sp_dp(l2, 30.0, 100, age_min=1, age_max=4),
        ]
        db = FakeDB(rows)
        out = asyncio_run(get_age_stratify(db=db, disease="measles"))
        assert len(out) == 1
        row = out[0]
        assert row["avg_positivity"] is not None
        assert "rate_weighted_legacy" in row
        assert row["meta"]["k"] == 2


# ════════════════════════════════════════════════════════════
# 工具：同步执行 async 函数
# ════════════════════════════════════════════════════════════

def asyncio_run(coro):
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # 已存在事件循环（pytest-asyncio 环境）：用独立线程
    import threading

    result, err = {}, {}

    def _run():
        try:
            result["v"] = asyncio.run(coro)
        except Exception as e:  # noqa: BLE001
            err["e"] = e

    t = threading.Thread(target=_run)
    t.start()
    t.join()
    if "e" in err:
        raise err["e"]
    return result["v"]

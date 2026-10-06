"""V3-04 守护: 报告正文数值可溯源校验。"""
from __future__ import annotations

from pathlib import Path


class TestCollectExpectedNumbers:
    """从 DataPoint 行里收集预期 KPI。"""

    def test_basic_kpi_always_present(self):
        class Fake:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        rows = [
            Fake(data_type="seroprevalence", value=0.95, sample_size=100),
            Fake(data_type="seroprevalence", value=0.88, sample_size=200),
        ]
        from app.services.report_service import _collect_expected_numbers
        expected = _collect_expected_numbers(rows, lit_count=3)

        assert expected["data_point_count"] == 2
        assert expected["literature_count"] == 3
        assert expected["total_sample_size"] == 300
        assert "sp_mean" in expected
        assert "sp_median" in expected
        assert abs(expected["sp_mean"] - 0.915) < 0.01

    def test_empty_rows(self):
        from app.services.report_service import _collect_expected_numbers
        e = _collect_expected_numbers([])
        assert e == {"data_point_count": 0}


class TestVerifyReportNumbers:
    """正文数值 vs 预期 KPI 自动比对。"""

    def test_matched_numbers(self):
        from app.services.report_service import _verify_report_numbers

        report = (
            "## 抗体水平分析\n"
            "本次分析涵盖 **3 篇文献**，共 **2 个数据点**，"
            "总计样本量 300 人。\n"
            "血清阳性率均值为 91.5%，中位数 91.5%。\n"
            "范围从 88% 到 95%。\n"
            "数据来源：[1] [2]。\n"
        )
        expected = {
            "data_point_count": 2,
            "literature_count": 3,
            "total_sample_size": 300,
            "sp_mean": 91.5,
            "sp_median": 91.5,
            "sp_min": 88.0,
            "sp_max": 95.0,
        }
        result = _verify_report_numbers(report, expected)
        assert result["matched"] >= result["checked"] - 1  # 大部分应匹配
        assert result["warnings"] == [] or all("未匹配" not in w for w in result["warnings"])

    def test_llm_hallucination_detected(self):
        """LLM 报告了预期 KPI 里没有的数值 → 应警告。"""
        from app.services.report_service import _verify_report_numbers

        report = (
            "## 分析\n"
            "数据点 2 个，文献 3 篇。\n"
            "抗体水平高达 99.9%，总样本量 300。\n"
            "某个完全虚构的指标 = 42.7。\n"
        )
        expected = {
            "data_point_count": 2,
            "literature_count": 3,
            "total_sample_size": 300,
            "sp_mean": 91.5,
            "sp_max": 95.0,
        }
        result = _verify_report_numbers(report, expected)
        # 42.7 这个虚构数值应该被标记为未匹配
        assert len(result["unmatched"]) >= 1
        assert any("42" in u or "42.7" in u for u in result["unmatched"])
        assert len(result["warnings"]) >= 1

    def test_tolerance_half_percent(self):
        """±0.5% 相对误差内应视为匹配。"""
        from app.services.report_service import _verify_report_numbers

        expected = {"kpi_x": 95.43}
        report_plus = "数值是 95.8%。"
        report_minus = "数值是 95.0%。"
        # 95.43 * 1.005 = 95.907; 95.43 * 0.995 = 94.953
        # 95.8 在区间内 (95.907) — 其实超出了? 让我算:
        # 95.8 vs 95.43 → rel = 0.00387 → < 0.005 ✅
        # 95.0 vs 95.43 → rel = 0.00451 → < 0.005 ✅
        r_plus = _verify_report_numbers(report_plus, expected)
        r_minus = _verify_report_numbers(report_minus, expected)
        assert r_plus["matched"] == 1, f"+0.4% 应匹配: {r_plus}"
        assert r_minus["matched"] == 1, f"-0.4% 应匹配: {r_minus}"

    def test_percent_and_decimal_equivalent(self):
        """95% 和 0.95 应视为同一值（自动双向换算）。"""
        from app.services.report_service import _verify_report_numbers

        expected_pct = {"kpi": 95.0}       # 百分比形式
        expected_dec = {"kpi": 0.95}       # 小数形式

        report_dec = "抗体水平 0.95。"
        report_pct = "抗体水平 95%。"

        # 报告写 0.95 → 应匹配 95.0
        r1 = _verify_report_numbers(report_dec, expected_pct)
        assert r1["matched"] == 1, f"decimal 应匹配 percent: {r1}"

        # 报告写 95% → 应匹配 0.95
        r2 = _verify_report_numbers(report_pct, expected_dec)
        assert r2["matched"] == 1, f"percent 应匹配 decimal: {r2}"

    def test_references_excluded(self):
        """[1] [2] 参考文献编号不应被当作正文数值。"""
        from app.services.report_service import _verify_report_numbers

        report = "根据文献 [1] 和 [2]，抗体水平为 95%。"
        expected = {"kpi": 95.0}
        result = _verify_report_numbers(report, expected)
        # [1] [2] 应被剥离, 不产生 unmatche
        assert result["unmatched"] == [], \
            f"参考文献编号应被剥离: {result['unmatched']}"
        assert result["matched"] == 1


class TestV304InReports:
    """两个报告函数都应调用 V3-04 校验。"""

    def test_verify_called_in_generate_report(self):
        import inspect
        from app.services import report_service
        src = inspect.getsource(report_service.generate_report)
        assert "_collect_expected_numbers" in src, \
            "generate_report 未调用 _collect_expected_numbers"
        assert "_verify_report_numbers" in src, \
            "generate_report 未调用 _verify_report_numbers"

    def test_verify_called_in_immune_barrier(self):
        import inspect
        from app.services import report_service
        src = inspect.getsource(report_service.generate_immune_barrier_report)
        assert "_collect_expected_numbers" in src, \
            "immune_barrier 未调用 _collect_expected_numbers"
        assert "_verify_report_numbers" in src, \
            "immune_barrier 未调用 _verify_report_numbers"

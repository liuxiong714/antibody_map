"""Test LLMClientMixin._record_timing / get_timing_summary

单元测试，无 DB 依赖。验证效率指标统计逻辑的正确性与边界防护。
"""
import pytest
from app.core.extraction.llm_client import LLMClientMixin


class _DummyExtractor(LLMClientMixin):
    """最小子类：只继承 LLMClientMixin 的 timing 功能。"""

    def __init__(self):
        self._timing = None  # 初始为 None，让 _record_timing 自己初始化


class TestRecordTiming:
    """_record_timing 累加逻辑"""

    def test_initial_state(self):
        """空实例返回全零/None。"""
        e = _DummyExtractor()
        s = e.get_timing_summary()
        assert s["calls"] == 0
        assert s["avg_first_token_ms"] is None
        assert s["gen_seconds"] == 0.0
        assert s["completion_tokens"] == 0
        assert s["tokens_per_sec"] is None

    def test_single_call_full(self):
        """单次调用，所有字段都有值。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=500, gen_ms=2000, completion_tokens=100)
        s = e.get_timing_summary()
        assert s["calls"] == 1
        assert s["avg_first_token_ms"] == 500
        assert s["gen_seconds"] == 2.0
        assert s["completion_tokens"] == 100
        assert s["tokens_per_sec"] == 50.0  # 100 / 2.0

    def test_multiple_calls_average(self):
        """多次调用：平均首token延迟正确，tokens_per_sec 基于累计。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=400, gen_ms=1000, completion_tokens=50)
        e._record_timing(first_token_ms=600, gen_ms=2000, completion_tokens=100)
        e._record_timing(first_token_ms=500, gen_ms=1000, completion_tokens=50)
        s = e.get_timing_summary()
        assert s["calls"] == 3
        assert s["avg_first_token_ms"] == 500  # (400+600+500)/3 = 500
        assert s["gen_seconds"] == 4.0          # (1000+2000+1000)/1000 = 4.0
        assert s["completion_tokens"] == 200
        assert s["tokens_per_sec"] == 50.0       # 200 / 4.0 = 50.0

    def test_first_token_ms_none_skipped(self):
        """部分调用无 first_token_ms 时，avg 正确忽略 None。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=300, gen_ms=1000, completion_tokens=50)
        e._record_timing(first_token_ms=None, gen_ms=500, completion_tokens=30)
        e._record_timing(first_token_ms=500, gen_ms=1500, completion_tokens=70)
        s = e.get_timing_summary()
        assert s["calls"] == 3
        assert s["avg_first_token_ms"] == 400  # (300+500)/2 = 400（忽略 None 的那一次）
        assert s["gen_seconds"] == 3.0          # 1000+500+1500 = 3000ms
        assert s["completion_tokens"] == 150
        assert s["tokens_per_sec"] == 50.0

    def test_all_first_token_ms_none(self):
        """所有调用都没有 first_token_ms → avg_first_token_ms 为 None。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=None, gen_ms=1000, completion_tokens=50)
        e._record_timing(first_token_ms=None, gen_ms=1000, completion_tokens=50)
        s = e.get_timing_summary()
        assert s["calls"] == 2
        assert s["avg_first_token_ms"] is None
        assert s["completion_tokens"] == 100
        assert s["tokens_per_sec"] == 50.0

    def test_gen_ms_zero_tokens_per_sec_none(self):
        """gen_ms=0 时 tokens_per_sec=None（除零防护）。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=100, gen_ms=0, completion_tokens=50)
        s = e.get_timing_summary()
        assert s["gen_seconds"] == 0.0
        assert s["tokens_per_sec"] is None

    def test_completion_tokens_zero(self):
        """completion_tokens=0 时 tokens_per_sec=0.0（0 token / 非零秒 = 0.0）。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=100, gen_ms=2000, completion_tokens=0)
        s = e.get_timing_summary()
        assert s["tokens_per_sec"] == 0.0

    def test_gen_ms_none_treated_as_zero(self):
        """gen_ms=None 按 0 处理，gen_seconds=0 → tokens_per_sec=None。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=100, gen_ms=None, completion_tokens=50)
        s = e.get_timing_summary()
        assert s["gen_seconds"] == 0.0
        assert s["tokens_per_sec"] is None

    def test_negative_values_clamped_by_callers(self):
        """_record_timing 本身不做负值防护——实际负值防护在 _chat_once 等调用处用 max(0, ...) 完成。
        这里验证：如果真传入负值，不会崩溃但结果不可信（调用者责任）。"""
        e = _DummyExtractor()
        # 此用例仅验证不崩溃，不验证数学正确性
        try:
            e._record_timing(first_token_ms=-500, gen_ms=-1000, completion_tokens=-10)
            s = e.get_timing_summary()
            assert s["calls"] == 1
        except Exception:
            pytest.fail("_record_timing 不应因负值崩溃")

    def test_zero_all(self):
        """全零输入。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=0, gen_ms=0, completion_tokens=0)
        s = e.get_timing_summary()
        assert s["calls"] == 1
        assert s["avg_first_token_ms"] == 0
        assert s["gen_seconds"] == 0.0
        assert s["completion_tokens"] == 0
        assert s["tokens_per_sec"] is None

    def test_very_large_numbers(self):
        """大数值下无溢出/精度丢失。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=10**9, gen_ms=10**12, completion_tokens=10**9)
        s = e.get_timing_summary()
        assert s["calls"] == 1
        assert s["avg_first_token_ms"] == 10**9
        assert s["gen_seconds"] == 10**9  # 10^12 ms = 10^9 s
        assert s["completion_tokens"] == 10**9
        assert s["tokens_per_sec"] == 1.0


class TestTimingSummaryContract:
    """验证 get_timing_summary 返回 dict 的字段契约不变——下游（合成任务/API层）依赖此结构。"""

    def test_return_keys(self):
        """返回 dict 必须包含 calls / avg_first_token_ms / gen_seconds / completion_tokens / tokens_per_sec。"""
        e = _DummyExtractor()
        keys = set(e.get_timing_summary().keys())
        expected = {"calls", "avg_first_token_ms", "gen_seconds", "completion_tokens", "tokens_per_sec"}
        assert keys == expected, f"timing_summary keys 不匹配: 差集 expected={expected - keys}, 多集={keys - expected}"

    def test_return_types_after_record(self):
        """record 后各字段类型正确。"""
        e = _DummyExtractor()
        e._record_timing(first_token_ms=100, gen_ms=1000, completion_tokens=50)
        s = e.get_timing_summary()
        assert isinstance(s["calls"], int)
        assert isinstance(s["avg_first_token_ms"], int)
        assert isinstance(s["gen_seconds"], float)
        assert isinstance(s["completion_tokens"], int)
        # tokens_per_sec 是 float（round 后），值 = 50.0
        assert isinstance(s["tokens_per_sec"], float)


class TestExtractionHistoryModel:
    """timing_detail 字段在 ORM 上存在且为 JSON 类型。"""

    def test_timing_detail_column_exists(self):
        from app.models.extraction_history import ExtractionHistory
        col = ExtractionHistory.__table__.c.get("timing_detail")
        assert col is not None, "ExtractionHistory.timing_detail 列缺失"
        from sqlalchemy.dialects.postgresql import JSON
        assert isinstance(col.type, JSON), f"timing_detail 应为 JSON 类型，实际: {col.type}"

    def test_model_can_be_instantiated_with_timing_detail(self):
        from app.models.extraction_history import ExtractionHistory
        import uuid
        h = ExtractionHistory(
            literature_id=uuid.uuid4(),
            timing_detail={"calls": 1, "avg_first_token_ms": 500, "gen_seconds": 2.0,
                           "completion_tokens": 100, "tokens_per_sec": 50.0},
        )
        assert h.timing_detail is not None
        assert h.timing_detail["tokens_per_sec"] == 50.0

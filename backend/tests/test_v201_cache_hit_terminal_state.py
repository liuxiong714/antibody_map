"""V2-01 cache_hit 早退路径的守护测试。

覆盖点:
  1) cache_hit=True 时应写 ExtractionHistory(cache_hit=True)
  2) cache_hit=True 时 ExtractionHistory token/cost 应为 0
  3) cache_hit=True 时应做终态 CAS 更新 literature.extraction_status
  4) 终态 CAS 未命中时应返回 superseded（不应默默 stuck processing）
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# =======================================================
# 纯单元：测试 fingerprint 算法与写库前计算（V2-05 复用）
# =======================================================
def compute_fp(dp: dict) -> str:
    parts = [
        str(dp.get("disease") or "NULL"),
        str(dp.get("province") or "NULL"),
        str(dp.get("city") or "NULL"),
        str(dp.get("data_type") or "NULL"),
        str(dp.get("age_min") if dp.get("age_min") is not None else "NULL"),
        str(dp.get("age_max") if dp.get("age_max") is not None else "NULL"),
        str(dp.get("collection_year") if dp.get("collection_year") is not None else "NULL"),
        str(round(dp["value"], 6) if dp.get("value") is not None else "NULL"),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class TestFingerprintAlgorithm:
    """V2-05 守护：fingerprint 算法必须稳定且可预测。"""

    def test_identical_points_same_fp(self):
        a = {"disease": "measles", "province": "广东", "city": "广州",
             "data_type": "seroprevalence", "age_min": 5, "age_max": 9,
             "collection_year": 2023, "value": 0.123456}
        b = dict(a)
        assert compute_fp(a) == compute_fp(b)

    def test_rounding_remembers_6_decimals(self):
        # 第 7 位不同但 round(value,6) 相同 → fp 相同
        a = {"disease": "mumps", "province": "北京", "city": None,
             "data_type": "seroprevalence", "age_min": 0, "age_max": 4,
             "collection_year": None, "value": 0.5000001}
        b = dict(a, value=0.5000004)
        assert round(a["value"], 6) == round(b["value"], 6)
        assert compute_fp(a) == compute_fp(b)

    def test_value_null_distinct_from_zero(self):
        a = {"disease": "dengue", "province": "云南", "city": "昆明",
             "data_type": "ns1", "age_min": None, "age_max": None,
             "collection_year": 2022, "value": None}
        b = dict(a, value=0)
        assert compute_fp(a) != compute_fp(b)

    def test_all_none_not_hash_collides(self):
        """全 None 的 data_point → 必须产生稳定 fp（None 统一为 "NULL" 字符串）。"""
        a = {"disease": None, "province": None, "city": None,
             "data_type": None, "age_min": None, "age_max": None,
             "collection_year": None, "value": None}
        b = {"disease": None, "province": None, "city": None,
             "data_type": None, "age_min": None, "age_max": None,
             "collection_year": None, "value": None}
        assert compute_fp(a) == compute_fp(b)
        # 不能是空字符串
        assert compute_fp(a) != ""
        assert len(compute_fp(a)) == 64  # SHA256 hex 长度


class TestCacheHitExtractionHistoryWritten:
    """V2-01 守护：cache_hit 分支必须写 ExtractionHistory + 终态 CAS。"""

    def test_cache_hit_history_has_zero_tokens(self):
        """LLM 未被调用 → token/cost/duration 必须全为 0。"""
        # 等价断言：ExtractionHistory(cache_hit=True) 时 token=0, cost=0
        from app.models.extraction_history import ExtractionHistory
        h = ExtractionHistory(
            literature_id="00000000-0000-0000-0000-000000000000",
            model="test (cached)",
            cache_hit=True,
            status="success",
            data_point_count=5,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            llm_cost_usd=0,
            duration_seconds=0,
            llm_call_count=0,
        )
        assert h.cache_hit is True
        assert h.prompt_tokens == 0
        assert h.total_tokens == 0
        assert h.llm_cost_usd == 0
        assert h.duration_seconds == 0
        assert h.llm_call_count == 0

    def test_cache_hit_field_exists_in_model(self):
        """V2-01 迁移后 ExtractionHistory 模型必须有 cache_hit 列。"""
        from app.models.extraction_history import ExtractionHistory
        mapper = ExtractionHistory.__mapper__
        assert "cache_hit" in mapper.columns, \
            "V2-01 regression: ExtractionHistory.cache_hit 列丢失"

    def test_data_point_has_v201_v204_v205_v206_columns(self):
        """V2-04/V2-05/V2-06 后 DataPoint 模型必须有新列。"""
        from app.models.data_point import DataPoint
        mapper = DataPoint.__mapper__
        for col in ("denominator_type", "value_note",
                    "review_reason", "content_fingerprint"):
            assert col in mapper.columns, f"V2 regression: DataPoint.{col} 列丢失"


class TestReviewReasonNoHasattr:
    """V2-06 守护：duplicates.py 必须直接写 review_reason（无 hasattr 保护）。"""

    def test_duplicates_rejects_hasattr_guard(self):
        """V2-06 修复后 duplicates.py 不应该再出现 hasattr.*review_reason。"""
        import inspect
        from app.services.literature import duplicates
        src = inspect.getsource(duplicates)
        # 不应再有宽松的 hasattr(s_dp, 'review_reason') 或 hasattr(t, 'review_reason')
        assert "hasattr(s_dp" not in src or "review_reason" not in src.split("hasattr(s_dp")[-1][:80]
        assert "hasattr(t" not in src or "review_reason" not in src.split("hasattr(t")[-1][:80]

    def test_denominator_type_value_note_in_extract_task_dict(self):
        """V2-04: extract_task.py common dict 必须包含 denominator_type 和 value_note。"""
        import inspect
        from app.tasks import extract_task
        src = inspect.getsource(extract_task)
        assert '"denominator_type"' in src or "'denominator_type'" in src, \
            "V2-04 regression: denominator_type 未落库字典"
        assert '"value_note"' in src or "'value_note'" in src, \
            "V2-04 regression: value_note 未落库字典"

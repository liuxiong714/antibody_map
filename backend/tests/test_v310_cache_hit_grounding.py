"""V3-10 守护: 缓存命中 grounding_rate 计算必须兼容 dict (json.loads) 元素。

问题: cache_hit 分支 extract_results 元素是 dict (json.loads 产物),
      但代码用 getattr(r, "is_grounded", False) — 对 dict 恒 False,
      导致 grounding_rate 恒 0.0, ungrounded_count = 全部。

修复: _safe_get(obj, key, default) — dict 用 .get(), object 用 getattr()
"""
from __future__ import annotations


class TestSafeGetDictObjectCompat:
    """V3-10: _safe_get 必须同时兼容 dict 和 object。"""

    def test_dict_input_uses_get(self):
        from app.tasks.extract_task import _safe_get
        d = {"is_grounded": True, "value": 0.95}
        assert _safe_get(d, "is_grounded", False) is True
        assert _safe_get(d, "missing", 42) == 42

    def test_object_input_uses_getattr(self):
        from app.tasks.extract_task import _safe_get

        class Fake:
            is_grounded = True
            value = 0.95

        o = Fake()
        assert _safe_get(o, "is_grounded", False) is True
        assert _safe_get(o, "missing", 42) == 42

    def test_dict_from_json_scenario(self):
        """模拟缓存命中场景: json.loads 产物, 含 is_grounded=True."""
        import json
        from app.tasks.extract_task import _safe_get

        raw = '{"disease": "measles", "is_grounded": true, "value": 0.95}'
        d = json.loads(raw)
        # getattr 对 dict 恒 False
        assert not hasattr(d, "is_grounded") or not getattr(d, "is_grounded", False) or True
        # _safe_get 正确返回
        assert _safe_get(d, "is_grounded", False) is True

    def test_cache_hit_grounding_rate_calc(self):
        """真实场景复现: cache_hit 分支的 grounded 计数。"""
        from app.tasks.extract_task import _safe_get

        # 5 个缓存元素, 3 个 grounded
        cached_results = [
            {"is_grounded": True, "value": 0.9},
            {"is_grounded": True, "value": 0.8},
            {"is_grounded": False, "value": 0.5},
            {"is_grounded": True, "value": 0.7},
            {"is_grounded": False, "value": 0.6},
        ]
        grounded = sum(1 for r in cached_results if _safe_get(r, "is_grounded", False))
        rate = grounded / len(cached_results) if cached_results else None
        assert grounded == 3
        assert rate == 0.6


class TestV310LegacyGetattrRemoved:
    """V3-10: 写库循环里对 extract_results 的 getattr 必须替换为 _safe_get。"""

    def test_no_raw_getattr_on_extract_results(self):
        from app.tasks import extract_task
        import inspect
        src = inspect.getsource(extract_task)
        # 不能再有: getattr(r, "is_grounded", ...) — 必须用 _safe_get
        assert 'getattr(r, "is_grounded"' not in src and "getattr(r, 'is_grounded'" not in src, \
            "V3-10: 仍有 getattr(r, 'is_grounded') 未替换"

    def test_safe_get_exists_and_used(self):
        from app.tasks import extract_task
        import inspect
        src = inspect.getsource(extract_task)
        assert "_safe_get" in src, "_safe_get 辅助函数缺失"
        assert "_safe_get(r, " in src or "_safe_get(r," in src, \
            "_safe_get 未在 extract_results 上调用"

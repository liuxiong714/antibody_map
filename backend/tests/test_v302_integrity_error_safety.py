"""V3-02 守护: DataPoint 写库循环必须有 IntegrityError 兜底。

测试内容:
  1) _compute_dp_fingerprint 模块级函数存在且可 import
  2) IntegrityError + begin_nested + rollback 三件套在写库循环里存在
  3) _skipped_by_constraint 计数器存在（冲突可观测）
"""
from __future__ import annotations

import inspect


class TestComputeDpFingerprintImportable:
    """V3-02: 指纹函数必须是模块级 (backfill 可 import)。"""

    def test_function_exists_and_importable(self):
        """_compute_dp_fingerprint 必须在 app.tasks.extract_task 模块顶层。"""
        from app.tasks.extract_task import _compute_dp_fingerprint
        assert callable(_compute_dp_fingerprint), "_compute_dp_fingerprint 不是可调用函数"

    def test_algorithm_stable(self):
        """验证算法与 backfill 脚本一致 (round(value,6) + 8 字段)."""
        from app.tasks.extract_task import _compute_dp_fingerprint

        class FakeDP:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        a = FakeDP(disease="measles", province="北京", city="朝阳",
                    data_type="seroprevalence", age_min=1, age_max=5,
                    collection_year=2023, value=0.123456)
        b = FakeDP(disease="measles", province="北京", city="朝阳",
                    data_type="seroprevalence", age_min=1, age_max=5,
                    collection_year=2023, value=0.1234564)
        c = FakeDP(disease="measles", province="北京", city="朝阳",
                    data_type="seroprevalence", age_min=1, age_max=5,
                    collection_year=2023, value=None)
        # round(value,6) 后 a == b
        assert _compute_dp_fingerprint(a) == _compute_dp_fingerprint(b)
        # None vs 0 应不同（V2-05 算法: None 统一为 "NULL" 字符串）
        assert _compute_dp_fingerprint(a) != _compute_dp_fingerprint(c)


class TestIntegrityErrorSafetyNet:
    """V3-02: 写库循环必须有 savepoint + IntegrityError + rollback。"""

    def test_integrity_error_imported(self):
        """sqlalchemy.exc.IntegrityError 必须在 extract_task.py 顶层 import。"""
        from app.tasks import extract_task
        src = inspect.getsource(extract_task)
        assert "IntegrityError" in src, "IntegrityError 未 import"

    def test_savepoint_in_write_loop(self):
        """写库循环必须用 begin_nested 做 savepoint 隔离。"""
        from app.tasks import extract_task
        src = inspect.getsource(extract_task)
        assert "begin_nested" in src, "begin_nested savepoint 缺失"
        assert "async with db.begin_nested()" in src, "async with db.begin_nested() 缺失"

    def test_integrity_error_caught(self):
        """写库循环必须有 except IntegrityError 捕获。"""
        from app.tasks import extract_task
        src = inspect.getsource(extract_task)
        assert "except IntegrityError" in src or "except IntegrityError as" in src, \
            "IntegrityError 未在写库循环捕获"

    def test_rollback_in_error_path(self):
        """IntegrityError 分支里必须显式 rollback。"""
        from app.tasks import extract_task
        src = inspect.getsource(extract_task)
        # 找 "except IntegrityError" 分支位置 (而非 import 行)
        idx = src.find("except IntegrityError")
        if idx == -1:
            idx = src.find("except IntegrityError as")
        assert idx != -1, "IntegrityError 分支未找到"
        window = src[idx:idx + 800]  # 后 800 字足以覆盖整个 except 块
        assert "rollback" in window, \
            "IntegrityError 分支里无 rollback (savepoint 回滚)"

    def test_skipped_counter_exists(self):
        """_skipped_by_constraint 计数器必须存在。"""
        from app.tasks import extract_task
        src = inspect.getsource(extract_task)
        assert "_skipped_by_constraint" in src, \
            "冲突跳过计数器缺失 (无法观测)"

    def test_fingerprint_function_used_in_loop(self):
        """写库循环必须用 _compute_dp_fingerprint (而非内联算法)。"""
        from app.tasks import extract_task
        src = inspect.getsource(extract_task)
        # 不应再有内联的 hashlib.sha256("|".join(_fp_parts)) 硬编码
        assert "_compute_dp_fingerprint(dp)" in src, \
            "写库循环未使用模块级 _compute_dp_fingerprint"
        # 旧内联算法不应残留
        assert '"|".join(_fp_parts)' not in src and "'|'.join(_fp_parts)" not in src, \
            "旧内联指纹算法仍残留 (应改用模块级函数)"

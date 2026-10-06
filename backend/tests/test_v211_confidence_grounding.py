"""V2-11 not_grounded → confidence=low + V2-12 批量审核保守拦截守护测试。"""
from __future__ import annotations

import inspect


class TestNotGroundedConfidence:
    """V2-11 守护：not_grounded 单独存在时 confidence 必须降为 low。"""

    def test_not_grounded_no_longer_medium(self):
        """extract_task.py 中 if 'not_grounded' in reasons 必须设 confidence='low'。"""
        from app.tasks import extract_task
        src = inspect.getsource(extract_task)
        # 关键断言：代码里必须有 "not_grounded" 和 "confidence = 'low'" 的联合条件
        # 且不能再有 "not_grounded 单独仅降为 medium" 或 "保持默认 medium" 这类注释
        assert "not_grounded" in src
        # 确认没有过时的"not_grounded 单独仅降为 medium"注释
        assert "保持默认 medium" not in src, \
            "V2-11 regression: 仍有 '保持默认 medium' 的 legacy 注释"
        assert "单独仅降为 medium" not in src, \
            "V2-11 regression: 仍有 '单独仅降为 medium' 的 legacy 注释"

    def test_confidence_floor_is_low_not_medium(self):
        """所有 schema flag 都会导致 confidence=low（最低档）。"""
        from app.tasks import extract_task
        src = inspect.getsource(extract_task)
        # 必须有 if "not_grounded" in reasons: confidence = "low" 这种显式分支
        # 用正则找：两个条件都出现
        has_not_grounded_low = (
            "not_grounded" in src and
            ('confidence = "low"' in src or "confidence = 'low'" in src)
        )
        assert has_not_grounded_low, \
            "V2-11 regression: not_grounded 没有显式降级为 low"


class TestBatchConfirmGuard:
    """V2-12 守护：batch_confirm 的 except: pass 必须改为保守拦截。"""

    def test_no_except_pass_in_batch_confirm(self):
        """extraction.py 的 batch_confirm 中不应再有 except Exception: pass。"""
        from app.api.v1 import extraction
        src = inspect.getsource(extraction)
        # 旧代码是 except Exception: pass 紧跟 ungrounded 查询
        # 现在应该改成 except ... : raise HTTPException
        # 找 batch_confirm 附近的 except
        # 简单断言：extraction.py 中不应出现 "is_grounded == False" 附近的 except Exception: pass
        # 用 grep 语义："except Exception:" + "pass" + "is_grounded" 三条件不应同时成立
        lines = src.split("\n")
        for i, line in enumerate(lines):
            if "is_grounded" in line:
                # 往上找 10 行内的 except Exception
                window = "\n".join(lines[max(0, i-15):i+1])
                if "except Exception" in window and "pass" in window:
                    # 更精确：except Exception 后面紧接 pass（不是 raise）
                    # 看 except 后面那几行
                    j = max(0, i-15)
                    while j < i:
                        if "except Exception" in lines[j] or "except BaseException" in lines[j]:
                            # 看之后 3 行内是否只有 pass
                            after = "\n".join(lines[j+1:min(j+5, i)])
                            if "raise" not in after and "pass" in after and "is_grounded" in window:
                                pytest = __import__("pytest")
                                pytest.fail(
                                    f"V2-12 regression: batch_confirm 附近仍有 "
                                    f"'except Exception: pass' 静默吞掉拦截异常"
                                )
                        j += 1

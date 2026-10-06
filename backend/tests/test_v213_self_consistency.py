"""V2-13 synthetic 评测去自证检测守护测试 + V2-07/V2-08/V2-09 守护。"""
from __future__ import annotations

import inspect


class TestSyntheticSelfConsistency:
    """V2-13 守护：合成评测必须检测并警告自证偏差。"""

    def test_synthetic_has_self_consistency_check(self):
        from app.services import synthetic_service
        src = inspect.getsource(synthetic_service)
        # 必须同时出现 "reference_model" + "self_ref" + "existing" 或 "gt_source" 模式
        self_ref_patterns = [
            "self_ref",
            "self_consistency",
            "自证",
        ]
        found = any(p in src for p in self_ref_patterns)
        assert found, \
            "V2-13 regression: synthetic_service 缺自证偏差检测"

    def test_warnings_field_exists_in_report(self):
        from app.services import synthetic_service
        src = inspect.getsource(synthetic_service)
        assert '"warnings"' in src or "'warnings'" in src, \
            "V2-13 regression: synthetic report 缺 warnings 字段"


class TestSchemaArticleNotes:
    """V2-07 守护：article JSON Schema 必须有 notes 字段。"""

    def test_article_notes_in_json_schema(self):
        from app.core.extraction import schema
        # 直接读 schema.py 文件中的 JSON Schema 定义（PROMPT_ZH 里也有 notes 但那是 Prompt，不是 JSON Schema）
        import os
        p = os.path.dirname(schema.__file__) + "/schema.py"
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        # JSON Schema 版本里必须有 "notes" + "maxLength"
        # 用正向后向匹配：找 JSON Schema 中的 article.notes 定义
        # 简单断言：content 里同时出现 '"notes"' 和 'maxLength'
        assert '"notes"' in content or "'notes'" in content, \
            "V2-07 regression: article.properties 缺 notes"
        # 更关键：notes 字段定义旁边必须有 maxLength
        # 找 notes 定义附近
        idx = content.find("\"notes\"")
        if idx == -1:
            idx = content.find("'notes'")
        assert idx != -1, "notes 字段未找到"
        window = content[idx:idx+200]  # 后面 200 字
        assert "maxLength" in window, \
            f"V2-07 regression: notes 字段缺 maxLength（周围: ...{window[:100]}...）"


class TestReportTracingVerify:
    """V2-08 守护：report_service 必须有溯源校验函数。"""

    def test_report_service_has_tracing_verify(self):
        from app.services import report_service
        src = inspect.getsource(report_service)
        assert "_verify_report_tracing" in src, \
            "V2-08 regression: report_service 缺 _verify_report_tracing"

    def test_tracing_checks_ungrounded(self):
        from app.services import report_service
        src = inspect.getsource(report_service)
        assert "is_grounded" in src, \
            "V2-08 regression: 溯源校验未检查 is_grounded"


class TestDbBackupFcFormat:
    """V2-09 守护：pg_dump 必须用 -Fc 自定义压缩格式。"""

    def test_pg_dump_fc_flag(self):
        from app.services import db_backup_service
        src = inspect.getsource(db_backup_service)
        assert '"-Fc"' in src or "'-Fc'" in src, \
            "V2-09 regression: pg_dump 缺 -Fc 压缩格式标志"

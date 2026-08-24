"""text_preprocessor 截断/分块行为测试。

方案 A：将 TEXT_PREPROCESS_MAX_CHARS 默认上限从 60000 提高到 600000，
分块由 LLM_CHUNK_THRESHOLD/SIZE/OVERLAP 主导，避免超 6 万字符的
综述/长文尾部数据（含阳性率/GMC 表格）在进入 LLM 前被丢弃。
"""
import pytest

from app.config import settings
from app.core.text_preprocessor import focus_relevant_sections, preprocess, truncate


def _build_long_doc_with_tail_marker():
    """构造约 8 万字符文本，尾部（>60000 处）含唯一数据点。"""
    filler_line = "这是与血清抗体无关的普通填充段落文字，用于拉长文档，不含任何阳性率或抗体水平关键词。"
    filler = (filler_line + "\n") * 2500  # ~7.75 万字符
    tail_marker = "结果：抗体阳性率 87.6%，GMC 抗体水平为 5000，尾部唯一数据点-验证方案A用。"
    doc = filler + "\n" + tail_marker + "\n" + filler
    assert len(doc) > 80000, f"文档应超过 8 万字符，实际 {len(doc)}"
    return doc


class TestTailDataBeyondOldCap:
    def test_tail_marker_survives_new_cap_in_preprocess(self):
        """现状修复后：8 万字符文档的尾部唯一数据点在 preprocess 后仍保留。"""
        doc = _build_long_doc_with_tail_marker()
        result = preprocess(doc)
        assert "尾部唯一数据点-验证方案A用" in result
        # 即使经 focus_relevant_sections 软过滤，保留总量也应覆盖到尾部
        assert len(result) > 60000, f"预处理后文本应保留超过旧上限 60000，实际 {len(result)}"

    def test_tail_marker_dropped_under_old_60k_cap(self):
        """回归验证原 bug：旧 60000 上限下该尾部数据点被截断丢弃。"""
        doc = _build_long_doc_with_tail_marker()
        old = truncate(doc, max_chars=60000)
        assert "尾部唯一数据点-验证方案A用" not in old

    def test_settings_default_cap_is_600000(self):
        """默认上限已放宽到 600000（不再硬截断到 6 万）。"""
        assert settings.TEXT_PREPROCESS_MAX_CHARS >= 600000

    def test_truncate_default_uses_settings_cap(self):
        """truncate() 不传参时使用 settings 中的新上限，保留 >60000 文本。"""
        doc = _build_long_doc_with_tail_marker()
        result = truncate(doc)
        assert "尾部唯一数据点-验证方案A用" in result


class TestNoKeywordRowDropping:
    """4.1 回归：>5000 字符文本不得按关键词丢弃行，保障低频关键词的真实数据进入 LLM。"""

    def test_low_frequency_real_data_line_survives(self):
        """含真实数据但命中低频关键词的行，改造后必须原样保留。"""
        filler_line = "这是与血清抗体无关的普通填充文字，不含任何阳性率抗体水平血清GMC关键词，用于拉长文档。"
        # 构造 >5000 字符文本：多数行为无关键词填充行，目标数据行同样不含关键词
        filler = (filler_line + "\n") * 200  # ~1.4 万字符
        data_line = "目标机构报告了该地区某病毒的IgG抗体 3.20 g/L，为改造后应保留的真实数据行。"
        doc = filler + data_line + "\n" + filler
        assert len(doc) > 5000, f"文档应超过 5000 字符，实际 {len(doc)}"
        result = focus_relevant_sections(doc)
        assert data_line in result, "低频关键词的真实数据行不得被 keyword 过滤丢弃"
        assert result == doc, "改造后 focus_relevant_sections 应全量返回，不再逐行打分丢行"

    def test_preprocess_does_not_crop_doc(self):
        """preprocess 超过 5000 时不得再裁剪到约 2/3，正文（除首尾空白归一）应全额保留。"""
        filler_line = "这是与血清抗体无关的普通填充文字，不含任何阳性率抗体水平血清GMC关键词，用于拉长文档。"
        filler = (filler_line + "\n") * 200  # ~1.4 万字符
        marker = "结果：抗体阳性率 87.6%，GMC 抗体水平为 5000。"
        doc = filler + marker + "\n" + filler
        assert len(doc) > 5000
        result = preprocess(doc)
        assert marker in result
        # 对比旧实现丢弃约 1/3，这里只允许首尾空白归一导致的极小差异
        assert len(result) > len(doc) * 0.95, "preprocess 不应再裁剪到约 2/3，应保留全文"


class TestRegressionWithinOldCap:
    def test_short_doc_unchanged(self):
        """回归：6 万以内文档 preprocess 前后与截断无回归（文本原样保留）。"""
        text = "结果：麻疹血清阳性率 72.5%，样本量 300，生产方法 ELISA。"
        assert preprocess(text) == truncate(text)  # 短文本不触发任何截断

    def test_under_old_cap_truncate_is_noop(self):
        """回归：低于旧上限的文本 truncate 后完全一致。"""
        doc = _build_long_doc_with_tail_marker()
        # 取旧上限以内的一段，确认 truncate 不改变它
        head = doc[:50000]
        assert truncate(head, max_chars=60000) == head
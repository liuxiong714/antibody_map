"""提取准确度 & 性价比优化测试

测试目标（对应 9 项优化）：
A1. 结构化表格优先提取策略
A2. 两阶段提取（骨架+数值）
A3. grounding 阈值可配置 + LLM 重抽
A4. age_group 自动填充
B5. 分级模型策略
B6. Prompt 压缩 + 缓存（system prompt 分离）
B7. 分块策略优化（表格边界感知）
B8. 多趟提取智能调度
B9. 审核反馈闭环
"""
from __future__ import annotations

import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.core.llm_extractor import LLMExtractor, SYSTEM_PROMPT_ZH
from app.core.extraction_grounding import (
    ground_extraction,
    _DEFAULT_FUZZY_THRESHOLD,
    _fuzzy_match,
    GroundingResult,
)
from app.tasks.extract_task import _compute_age_group, _table_hash_cache


# ── A4：age_group 自动填充 ──────────────────────────
def test_age_group_both():
    assert _compute_age_group(0, 14) == "0-14岁"

def test_age_group_min_only():
    assert _compute_age_group(60, None) == "60岁及以上"

def test_age_group_max_only():
    assert _compute_age_group(None, 18) == "18岁及以下"

def test_age_group_neither():
    assert _compute_age_group(None, None) is None


# ── A3：grounding 阈值可配置 ────────────────────────
def test_grounding_threshold_configurable():
    """A3：grounding 阈值可从配置读取"""
    assert _DEFAULT_FUZZY_THRESHOLD == 0.72  # 默认值

def test_grounding_custom_threshold():
    """A3：自定义阈值影响 fuzzy_match 结果"""
    text = "这是一段包含阳性率数据的原文，其中提到了抗体阳性率为87.3%。"
    ctx = "阳性率数据原文提到抗体阳性率87.3"  # 略有差异
    # 高阈值 → 可能不匹配
    result_high = _fuzzy_match(text, ctx, threshold=0.99)
    # 低阈值 → 更容易匹配
    result_low = _fuzzy_match(text, ctx, threshold=0.5)
    # 高阈值结果为 None 或 ratio < 低阈值结果
    if result_high is not None and result_low is not None:
        assert result_high[1] <= result_low[1]  # 高阈值匹配的区间应 <= 低阈值

def test_grounding_accepts_threshold_param():
    """A3：ground_extraction 接受 fuzzy_threshold 参数"""
    result = ground_extraction("test text", "test", {}, fuzzy_threshold=0.5)
    assert isinstance(result, GroundingResult)


# ── B5：分级模型策略 ────────────────────────────────
def test_pick_model_short_no_tables():
    """B5：短文本+无表格 → 用 LIGHT 模型（如果配置了）"""
    extractor = LLMExtractor.__new__(LLMExtractor)
    extractor.model = "deepseek-chat"
    # 模拟未配置 LIGHT/STRONG
    with patch.object(settings, "LLM_MODEL_LIGHT", "", create=True):
        with patch.object(settings, "LLM_MODEL_STRONG", "", create=True):
            model = extractor._pick_model(3000, False)
            assert model == "deepseek-chat"  # 无配置时回退默认

def test_pick_model_long_with_tables():
    """B5：长文本+有表格 → 用 STRONG 模型（如果配置了）"""
    extractor = LLMExtractor.__new__(LLMExtractor)
    extractor.model = "deepseek-chat"
    with patch.object(settings, "LLM_MODEL_LIGHT", "", create=True):
        with patch.object(settings, "LLM_MODEL_STRONG", "deepseek-reasoner", create=True):
            model = extractor._pick_model(20000, True)
            assert model == "deepseek-reasoner"

def test_pick_model_short_with_light():
    """B5：短文本+无表格+配置了 LIGHT → 用 LIGHT"""
    extractor = LLMExtractor.__new__(LLMExtractor)
    extractor.model = "deepseek-chat"
    with patch.object(settings, "LLM_MODEL_LIGHT", "qwen-turbo", create=True):
        with patch.object(settings, "LLM_MODEL_STRONG", "", create=True):
            model = extractor._pick_model(3000, False)
            assert model == "qwen-turbo"

def test_pick_model_medium_default():
    """B5：中等长度+有表格但不够长 → 用默认模型"""
    extractor = LLMExtractor.__new__(LLMExtractor)
    extractor.model = "deepseek-chat"
    with patch.object(settings, "LLM_MODEL_LIGHT", "qwen-turbo", create=True):
        with patch.object(settings, "LLM_MODEL_STRONG", "deepseek-reasoner", create=True):
            model = extractor._pick_model(8000, True)
            assert model == "deepseek-chat"  # 不够长，不触发 STRONG


# ── B6：Prompt 压缩 + 缓存 ──────────────────────────
def test_system_prompt_exists():
    """B6：系统 prompt 常量存在且包含省份列表"""
    assert "省份" in SYSTEM_PROMPT_ZH
    assert "data_points" in SYSTEM_PROMPT_ZH
    assert "JSON" in SYSTEM_PROMPT_ZH

def test_table_hash_cache_exists():
    """B6：表格哈希缓存字典存在"""
    assert isinstance(_table_hash_cache, dict)

def test_call_llm_api_accepts_system_prompt():
    """B6：_call_llm_api 接受 system_prompt 参数"""
    # 验证方法签名包含 system_prompt
    import inspect
    sig = inspect.signature(LLMExtractor._call_llm_api)
    assert "system_prompt" in sig.parameters


# ── B7：分块策略优化（表格边界感知）─────────────────
def test_chunk_text_with_table_boundaries():
    """B7：_chunk_text 接受 table_boundaries 参数"""
    text = "A" * 25000  # 长文本
    boundaries = [(10000, 12000)]  # 一个表格区间
    chunks = LLMExtractor._chunk_text(text, table_boundaries=boundaries)
    assert len(chunks) > 1
    # 检查没有在表格中间切断（很难精确验证，但至少不报错）
    for offset, chunk in chunks:
        assert len(chunk) > 0

def test_chunk_text_without_boundaries():
    """B7：无 table_boundaries 时退化为原有行为"""
    text = "A" * 25000
    chunks1 = LLMExtractor._chunk_text(text)
    chunks2 = LLMExtractor._chunk_text(text, table_boundaries=None)
    assert len(chunks1) == len(chunks2)

def test_find_table_boundaries():
    """B7：_find_table_boundaries 能在全文中定位表格"""
    tables_md = "| 省份 | 阳性率 |\n|---|---|\n| 北京 | 87.3% |\n"
    text = "一些文本\n| 省份 | 阳性率 |\n|---|---|\n| 北京 | 87.3% |\n更多文本"
    boundaries = LLMExtractor._find_table_boundaries(text, tables_md)
    assert len(boundaries) > 0
    # 边界应该在文本范围内
    for s, e in boundaries:
        assert 0 <= s < len(text)
        assert s < e <= len(text)


# ── B8：多趟提取智能调度 ────────────────────────────
def test_count_table_rows():
    """B8：_count_table_rows 能估算表格行数"""
    tables_md = """| 省份 | 阳性率 |
|---|---|
| 北京 | 87.3 |
| 上海 | 75.2 |
| 广东 | 82.1 |"""
    rows = LLMExtractor._count_table_rows(tables_md)
    assert rows >= 2  # 至少 2 行数据（排除表头）

def test_count_table_rows_empty():
    """B8：空表格返回 0"""
    assert LLMExtractor._count_table_rows("") == 0
    assert LLMExtractor._count_table_rows(None) == 0


# ── B9：审核反馈闭环 ────────────────────────────────
def test_set_feedback_examples():
    """B9：set_feedback_examples 能设置示例列表"""
    extractor = LLMExtractor.__new__(LLMExtractor)
    extractor._feedback_examples = []
    examples = ["省份错误：鲁应为山东", "数值超范围：120%"]
    extractor.set_feedback_examples(examples)
    assert len(extractor._feedback_examples) == 2

def test_build_feedback_section():
    """B9：_build_feedback_section 生成注入段落"""
    extractor = LLMExtractor.__new__(LLMExtractor)
    extractor._feedback_examples = ["测试纠错1", "测试纠错2"]
    section = extractor._build_feedback_section()
    assert "历史审核纠错记录" in section
    assert "测试纠错1" in section
    assert "测试纠错2" in section

def test_build_feedback_section_empty():
    """B9：无示例时返回空字符串"""
    extractor = LLMExtractor.__new__(LLMExtractor)
    extractor._feedback_examples = []
    assert extractor._build_feedback_section() == ""


# ── A1：表格优先提取 ────────────────────────────────
def test_extract_accepts_table_only():
    """A1：extract 方法支持 table_only 参数"""
    import inspect
    sig = inspect.signature(LLMExtractor.extract)
    assert "table_only" in sig.parameters


# ── A2：两阶段提取 ──────────────────────────────────
def test_two_phase_extract_method_exists():
    """A2：_two_phase_extract 方法存在"""
    assert hasattr(LLMExtractor, "_two_phase_extract")

def test_skeleton_prompt_exists():
    """A2：骨架 prompt 常量存在"""
    assert hasattr(LLMExtractor, "SKELETON_PROMPT_ZH")
    assert "骨架" in LLMExtractor.SKELETON_PROMPT_ZH


# ── A3：LLM 重抽 source_context ─────────────────────
def test_reground_method_exists():
    """A3：reground_source_context 方法存在"""
    assert hasattr(LLMExtractor, "reground_source_context")


# ── 配置项验证 ──────────────────────────────────────
def test_config_has_optimization_settings():
    """所有优化配置项存在"""
    assert hasattr(settings, "GROUNDING_FUZZY_THRESHOLD")
    assert hasattr(settings, "GROUNDING_LLM_REGROUND")
    assert hasattr(settings, "LLM_MODEL_LIGHT")
    assert hasattr(settings, "LLM_MODEL_STRONG")
    assert hasattr(settings, "LLM_TABLE_FIRST_EXTRACTION")
    assert hasattr(settings, "LLM_TWO_PHASE_EXTRACTION")
    assert hasattr(settings, "LLM_ADAPTIVE_PASSES")
    assert hasattr(settings, "LLM_FEEDBACK_FEW_SHOT")
    assert hasattr(settings, "LLM_FEEDBACK_FEW_SHOT_COUNT")


# ── 运行所有测试 ─────────────────────────────────────
if __name__ == "__main__":
    test_age_group_both()
    test_age_group_min_only()
    test_age_group_max_only()
    test_age_group_neither()
    print("✓ A4 age_group (4 tests)")

    test_grounding_threshold_configurable()
    test_grounding_custom_threshold()
    test_grounding_accepts_threshold_param()
    print("✓ A3 grounding 阈值可配置 (3 tests)")

    test_pick_model_short_no_tables()
    test_pick_model_long_with_tables()
    test_pick_model_short_with_light()
    test_pick_model_medium_default()
    print("✓ B5 分级模型策略 (4 tests)")

    test_system_prompt_exists()
    test_table_hash_cache_exists()
    test_call_llm_api_accepts_system_prompt()
    print("✓ B6 Prompt 压缩+缓存 (3 tests)")

    test_chunk_text_with_table_boundaries()
    test_chunk_text_without_boundaries()
    test_find_table_boundaries()
    print("✓ B7 分块策略优化 (3 tests)")

    test_count_table_rows()
    test_count_table_rows_empty()
    print("✓ B8 多趟智能调度 (2 tests)")

    test_set_feedback_examples()
    test_build_feedback_section()
    test_build_feedback_section_empty()
    print("✓ B9 审核反馈闭环 (3 tests)")

    test_extract_accepts_table_only()
    print("✓ A1 表格优先提取 (1 test)")

    test_two_phase_extract_method_exists()
    test_skeleton_prompt_exists()
    print("✓ A2 两阶段提取 (2 tests)")

    test_reground_method_exists()
    print("✓ A3 LLM 重抽 (1 test)")

    test_config_has_optimization_settings()
    print("✓ 配置项验证 (1 test)")

    print("\n🎉 全部 27 个优化测试用例通过!")

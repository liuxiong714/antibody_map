"""P0-2 多趟提取 + LCS 动态规划对齐升级溯源 测试。

验证：
1. LCS 对齐算法（_lcs_ratio）正确性
2. _fuzzy_match 升级后能匹配 OCR 噪声文本
3. extraction_passes=1 时行为与原有一致（单趟）
4. extraction_passes=2 时调用两次 LLM 并合并去重（mock LLM）
5. complement_mode prompt 注入正确
6. 回归：原有 grounding 测试仍通过
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.extraction_grounding import (
    _lcs_ratio,
    _fuzzy_match,
    ground_extraction,
    GroundingResult,
)
from app.core.llm_extractor import LLMExtractor


# ========== 1. LCS 对齐算法正确性 ==========

def test_lcs_ratio_identical():
    """完全相同字符串比率为 1.0"""
    assert _lcs_ratio("abcde", "abcde") == 1.0
    print("✓ test_lcs_ratio_identical")


def test_lcs_ratio_empty():
    """空字符串比率为 0"""
    assert _lcs_ratio("", "abc") == 0.0
    assert _lcs_ratio("abc", "") == 0.0
    assert _lcs_ratio("", "") == 0.0
    print("✓ test_lcs_ratio_empty")


def test_lcs_ratio_partial():
    """部分匹配"""
    # LCS of "abcXY" and "abcZ" = "abc" = 3, max(5,4)=5, ratio=0.6
    r = _lcs_ratio("abcXY", "abcZ")
    assert abs(r - 0.6) < 0.01, f"expected 0.6, got {r}"
    print("✓ test_lcs_ratio_partial")


def test_lcs_ratio_disorder():
    """乱序字符：LCS 保持顺序，乱序降低比率"""
    # "abc" vs "cba": LCS=1 (任一单字符), max=3, ratio=1/3
    r = _lcs_ratio("abc", "cba")
    assert abs(r - 1/3) < 0.01, f"expected {1/3}, got {r}"
    print("✓ test_lcs_ratio_disorder")


def test_lcs_ratio_ocr_noise():
    """OCR 噪声场景：少量插入/替换仍能保持高比率"""
    original = "阳性率87.3%样本量1234"
    ocr_noisy = "阳性率87.3%样本量1234。"  # 末尾多一个句号（OCR 常见）
    r = _lcs_ratio(original, ocr_noisy)
    assert r >= 0.9, f"OCR 噪声场景比率应 >=0.9, got {r}"
    print("✓ test_lcs_ratio_ocr_noise")


# ========== 2. _fuzzy_match 升级后能匹配 OCR 噪声 ==========

def test_fuzzy_match_with_ocr_noise():
    """LCS 模糊匹配能定位含 OCR 噪声的上下文"""
    # 原文含 OCR 变体（百分号变句号）
    text = "本研究在广东省开展，共检测样本1234例，阳性者1082例，阳性率87。3%。结果显示免疫水平良好。"
    ctx = "阳性率87.3%"  # LLM 提取的干净版本
    result = _fuzzy_match(text, ctx)
    assert result is not None, "OCR 噪声场景应能模糊匹配"
    s, e, matched = result
    assert s < e
    assert "87" in matched or "3" in matched
    print(f"✓ test_fuzzy_match_with_ocr_noise (matched @[{s},{e}): {matched[:40]!r})")


def test_fuzzy_match_no_match():
    """完全不相关的上下文返回 None"""
    text = "这是一段关于天气的文本，今天阳光明媚。"
    ctx = "阳性率87.3%样本量1234"
    result = _fuzzy_match(text, ctx)
    assert result is None
    print("✓ test_fuzzy_match_no_match")


def test_fuzzy_match_short_ctx():
    """过短上下文（<6字符）返回 None"""
    assert _fuzzy_match("abcdefg", "ab") is None
    print("✓ test_fuzzy_match_short_ctx")


# ========== 3. ground_extraction 集成测试 ==========

def test_ground_extraction_with_ocr_noise():
    """ground_extraction 集成：OCR 噪声文本仍能 grounding 成功"""
    source_text = "本研究在广东省开展，共检测样本1234例，阳性者1082例，阳性率87。3%。"
    extract_item = {
        "positivity_rate": 87.3,
        "province": "广东",
        "sample_size": 1234,
    }
    source_context = "阳性率87.3%"
    result = ground_extraction(source_text, source_context, extract_item)
    assert result.is_grounded, "OCR 噪声场景应能 grounding"
    assert result.source_char_start is not None
    assert result.source_char_end is not None
    print(f"✓ test_ground_extraction_with_ocr_noise (method={result.method})")


def test_ground_extraction_exact_still_works():
    """回归：精确匹配仍然优先且工作正常"""
    source_text = "本研究在广东省开展，阳性率87.3%。"
    source_context = "阳性率87.3%"
    result = ground_extraction(source_text, source_context, {})
    assert result.is_grounded
    assert result.method == "exact"
    print("✓ test_ground_extraction_exact_still_works")


# ========== 4. 多趟提取（extraction_passes）==========

def test_multi_pass_extract_merges_and_dedups():
    """extraction_passes=2 时调用两次 LLM，结果合并去重"""
    extractor = LLMExtractor(model="deepseek-chat")

    call_count = {"n": 0}

    async def mock_call(prompt, system_prompt=""):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 第一趟：2 个数据点
            return json.dumps({
                "data_points": [
                    {"disease_name": "麻疹", "province": "广东", "positivity_rate": 87.3,
                     "source_context": "广东阳性率87.3%"},
                    {"disease_name": "麻疹", "province": "北京", "positivity_rate": 92.1,
                     "source_context": "北京阳性率92.1%"},
                ]
            }, ensure_ascii=False)
        else:
            # 第二趟：1 个新数据点 + 1 个重复（与第一趟相同）
            return json.dumps({
                "data_points": [
                    {"disease_name": "麻疹", "province": "上海", "positivity_rate": 85.0,
                     "source_context": "上海阳性率85%"},
                    {"disease_name": "麻疹", "province": "广东", "positivity_rate": 87.3,
                     "source_context": "广东阳性率87.3%"},  # 重复
                ]
            }, ensure_ascii=False)

    with patch.object(extractor, "_call_llm_api", side_effect=mock_call):
        result = asyncio.run(extractor.extract_with_retry(
            text="短文本",
            extraction_passes=2,
            max_retries=1,
        ))

    assert call_count["n"] == 2, f"应调用 2 次 LLM，实际 {call_count['n']}"
    # 合并后 3 个数据点（广东、北京、上海），广东重复的被去掉
    assert len(result) == 3, f"去重后应有 3 个数据点，实际 {len(result)}"
    provinces = {p["province"] for p in result}
    assert provinces == {"广东", "北京", "上海"}
    print("✓ test_multi_pass_extract_merges_and_dedups")


def test_single_pass_when_extraction_passes_1():
    """extraction_passes=1 时只调用 1 次 LLM（回归测试）"""
    extractor = LLMExtractor(model="deepseek-chat")

    call_count = {"n": 0}

    async def mock_call(prompt, system_prompt=""):
        call_count["n"] += 1
        return json.dumps({
            "data_points": [
                {"disease_name": "麻疹", "province": "广东", "positivity_rate": 87.3,
                 "source_context": "广东阳性率87.3%"}
            ]
        }, ensure_ascii=False)

    with patch.object(extractor, "_call_llm_api", side_effect=mock_call):
        result = asyncio.run(extractor.extract_with_retry(
            text="短文本",
            extraction_passes=1,
            max_retries=1,
        ))

    assert call_count["n"] == 1, f"单趟应只调用 1 次，实际 {call_count['n']}"
    assert len(result) == 1
    print("✓ test_single_pass_when_extraction_passes_1")


def test_complement_mode_injects_prompt():
    """complement_mode=True 时 prompt 包含查漏补缺指令"""
    extractor = LLMExtractor(model="deepseek-chat")

    captured_prompts = []

    async def mock_call(prompt, system_prompt=""):
        captured_prompts.append(prompt)
        return json.dumps({"data_points": []}, ensure_ascii=False)

    with patch.object(extractor, "_call_llm_api", side_effect=mock_call):
        asyncio.run(extractor.extract(text="文本", complement_mode=True))

    assert len(captured_prompts) == 1
    assert "查漏补缺模式" in captured_prompts[0]
    print("✓ test_complement_mode_injects_prompt")


def test_complement_mode_false_no_prefix():
    """complement_mode=False 时 prompt 不含查漏补缺指令"""
    extractor = LLMExtractor(model="deepseek-chat")

    captured_prompts = []

    async def mock_call(prompt, system_prompt=""):
        captured_prompts.append(prompt)
        return json.dumps({"data_points": []}, ensure_ascii=False)

    with patch.object(extractor, "_call_llm_api", side_effect=mock_call):
        asyncio.run(extractor.extract(text="文本", complement_mode=False))

    assert "查漏补缺模式" not in captured_prompts[0]
    print("✓ test_complement_mode_false_no_prefix")


def test_multi_pass_continues_on_pass_failure():
    """某趟提取失败时不阻塞其他趟"""
    extractor = LLMExtractor(model="deepseek-chat")

    call_count = {"n": 0}

    async def mock_call(prompt, system_prompt=""):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("第一趟 API 超时")
        return json.dumps({
            "data_points": [
                {"disease_name": "麻疹", "province": "广东", "positivity_rate": 87.3,
                 "source_context": "广东阳性率87.3%"}
            ]
        }, ensure_ascii=False)

    with patch.object(extractor, "_call_llm_api", side_effect=mock_call):
        result = asyncio.run(extractor.extract_with_retry(
            text="短文本",
            extraction_passes=2,
            max_retries=1,
        ))

    # 第一趟失败，第二趟成功，最终应返回第二趟的结果
    assert len(result) == 1
    assert result[0]["province"] == "广东"
    print("✓ test_multi_pass_continues_on_pass_failure")


if __name__ == "__main__":
    print("=" * 60)
    print("P0-2 多趟提取 + LCS 对齐测试")
    print("=" * 60)
    test_lcs_ratio_identical()
    test_lcs_ratio_empty()
    test_lcs_ratio_partial()
    test_lcs_ratio_disorder()
    test_lcs_ratio_ocr_noise()
    test_fuzzy_match_with_ocr_noise()
    test_fuzzy_match_no_match()
    test_fuzzy_match_short_ctx()
    test_ground_extraction_with_ocr_noise()
    test_ground_extraction_exact_still_works()
    test_multi_pass_extract_merges_and_dedups()
    test_single_pass_when_extraction_passes_1()
    test_complement_mode_injects_prompt()
    test_complement_mode_false_no_prefix()
    test_multi_pass_continues_on_pass_failure()
    print("=" * 60)
    print("P0-2 全部测试通过 ✓")

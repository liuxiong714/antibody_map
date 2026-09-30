"""P0-4 回归测试：数值回验的边界感知匹配 + 千分位支持。

根因（旧朴素 in 匹配）：
  - "84.3" in "184.35" 误通过（子串命中，但 84.3 在原文是 184.35 的子串不是独立数）
  - 原文 "共 1,234 名" 与回验值 1234 不匹配（千分位逗号漏匹配）

修复：
  1. _numeric_grounding_forms 整数追加千分位形态 1234 → ["1234", "1,234"]
  2. validate_numeric_grounding 用正则 (?<![0-9.]){form}(?![0-9]) 替代 in
     ——前后不能跟其他数字/小数点，但允许 %、％、空格、汉字等
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.extraction_grounding import (  # noqa: E402
    _numeric_grounding_forms,
    validate_numeric_grounding,
)


# ---------- Test 1: 边界感知 —— "184.35" 不应命中 "84.3" ----------

def test_boundary_rejects_substring_in_longer_number():
    """dp value=84.3，text 含 '184.35%' → 边界感知下应 False。"""
    dp = {"positivity_rate": 84.3, "source_context": ""}
    text = "阳性率为184.35%，样本量200"
    ok = validate_numeric_grounding(dp, text)
    assert ok is False, (
        f"84.3 在 '184.35%' 中是子串，边界感知下应 False，实际 {ok}"
    )
    print("  ✓ '184.35%' 不匹配 '84.3'（边界感知生效）")


def test_boundary_accepts_standalone_number():
    """dp value=84.3，text 含 '阳性率84.3%（' → True（独立数值）。"""
    dp = {"positivity_rate": 84.3, "source_context": ""}
    text = "血清阳性率84.3%（95% CI 80.0-88.7），样本量200"
    ok = validate_numeric_grounding(dp, text)
    assert ok is True, (
        f"'84.3%（' 中的 84.3 是独立数值，应 True，实际 {ok}"
    )
    print("  ✓ 独立数值 '84.3%' 正确命中")


def test_boundary_accepts_number_followed_by_chinese():
    """后跟汉字也应通过（lookahead 仅拦截数字）。"""
    dp = {"positivity_rate": 50.0, "source_context": ""}
    text = "该年龄段阳性率50.0以上"
    ok = validate_numeric_grounding(dp, text)
    assert ok is True, f"'50.0以上' 后跟汉字应命中，实际 {ok}"
    print("  ✓ 后跟汉字正确命中")


# ---------- Test 2: 千分位支持 ----------

def test_thousands_separator_integer():
    """dp sample_size=1234，text 含 '共 1,234 名' → True（千分位形态）。"""
    dp = {"sample_size": 1234, "source_context": ""}
    text = "本次调查共 1,234 名受试者，血清阳性率 15.5%"
    ok = validate_numeric_grounding(dp, text)
    assert ok is True, (
        f"千分位 '1,234' 应匹配整数 1234，实际 {ok}"
    )
    print("  ✓ 千分位 '1,234' 正确匹配 1234")


def test_nice_integer_form_still_works():
    """纯整数形态（无千分位）仍能命中。"""
    dp = {"sample_size": 215, "source_context": ""}
    text = "共215份血清样本"
    ok = validate_numeric_grounding(dp, text)
    assert ok is True
    print("  ✓ 纯整数匹配仍正常")


def test_small_integer_no_thousands_form():
    """小于 1000 的整数不生成千分位形态（4 位以上才生成）。"""
    forms = _numeric_grounding_forms(999)
    assert forms == ["999"], f"999 不应有千分位形态，实际 {forms}"
    forms2 = _numeric_grounding_forms(1234)
    assert "1,234" in forms2, f"1234 应有千分位形态，实际 {forms2}"
    print("  ✓ 千分位形态仅对 ≥4 位整数生成")


# ---------- Test 3: 与 P0-1 联动（extra_values + 边界感知） ----------

def test_extra_values_with_boundary():
    """P0-1 联动：dp value=0.0965、extra_values=[96.5]、text 含 '96.5 mIU/ml' → True。"""
    dp = {
        "gmc_value": 0.0965,
        "source_context": "",
    }
    text = "血清麻疹IgG抗体GMC为96.5 mIU/ml，阳性率85.0%"
    ok = validate_numeric_grounding(dp, text, extra_values=[96.5])
    assert ok is True, (
        f"extra_values=[96.5] 应命中 '96.5 mIU/ml'，实际 {ok}"
    )
    print("  ✓ P0-1 联动：extra_values 与边界感知协同生效")


def test_extra_values_extra_numeric_in_context():
    """extra_values 若本身也是被其他数字包围，不应误通过。"""
    dp = {"gmc_value": 0.0965, "source_context": ""}
    # 原文有 "196.5" 而非 "96.5"，extra_values=[96.5] 不应命中
    text = "GMC为196.5 mIU/ml"
    ok = validate_numeric_grounding(dp, text, extra_values=[96.5])
    assert ok is False, (
        f"'196.5' 不应命中 extra_values=[96.5]，实际 {ok}"
    )
    print("  ✓ extra_values 边界感知也正确拦截子串")


# ---------- Test 4: _numeric_grounding_forms 直接验证 ----------

def test_forms_no_scientific_notation():
    """浮点数不要生成 8.43e+01 这种科学计数法的 forms。"""
    forms = _numeric_grounding_forms(84.3)
    assert "84.3" in forms
    assert not any("e" in f.lower() for f in forms), f"不应有科学计数法 forms: {forms}"
    print("  ✓ 无科学计数法 forms")


def test_forms_edge_cases():
    """边界值：None / bool / 负数 / 0。"""
    assert _numeric_grounding_forms(None) == []
    assert _numeric_grounding_forms(True) == []
    forms_zero = _numeric_grounding_forms(0)
    assert "0" in forms_zero
    forms_neg = _numeric_grounding_forms(-5)
    # 负数也应正常生成
    assert "-5" in forms_neg
    print("  ✓ 边界值 forms 正确")


if __name__ == "__main__":
    print("=" * 60)
    print("P0-4 回归测试：数值回验边界感知匹配 + 千分位支持")
    print("=" * 60)

    print("\n--- Test 1a: '184.35%' 不匹配 '84.3' ---")
    test_boundary_rejects_substring_in_longer_number()

    print("\n--- Test 1b: '84.3%（' 匹配 '84.3' ---")
    test_boundary_accepts_standalone_number()

    print("\n--- Test 1c: 后跟汉字 ---")
    test_boundary_accepts_number_followed_by_chinese()

    print("\n--- Test 2a: 千分位 '1,234' ---")
    test_thousands_separator_integer()

    print("\n--- Test 2b: 纯整数 ---")
    test_nice_integer_form_still_works()

    print("\n--- Test 2c: 小整数无千分位 ---")
    test_small_integer_no_thousands_form()

    print("\n--- Test 3a: P0-1 联动 extra_values ---")
    test_extra_values_with_boundary()

    print("\n--- Test 3b: extra_values 也做边界检查 ---")
    test_extra_values_extra_numeric_in_context()

    print("\n--- Test 4a: 无科学计数法 ---")
    test_forms_no_scientific_notation()

    print("\n--- Test 4b: 边界值 ---")
    test_forms_edge_cases()

    print("\n" + "=" * 60)
    print("所有 P0-4 回归测试通过 ✓")
    print("=" * 60)

"""P0-1 回归测试：GMC 单位换算不得破坏数值回验。

根因：_post_process 把 mIU/ml 换算为 IU/ml（÷1000）后，ground_extraction 用
换算值 0.965 在原文找 —— 但原文只有 965 mIU/ml → 必然失败 → is_grounded=False、
confidence 降级。

修复：换算前保存原始值到 _gmc_value_raw，ground_extraction 调用
validate_numeric_grounding 时把原始值传入 extra_values。

本测试覆盖：
  1. 换算后 dp 中 _gmc_value_raw / _gmc_unit_raw 被正确保存
  2. ground_extraction 用换算后 dp + 原始值，在含 mIU 的原文中成功回验
  3. 换算后的 gmc_value / gmc_unit 仍正确（÷1000 + IU/ml）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.extraction.post_processor import PostProcessorMixin  # noqa: E402
from app.core.extraction_grounding import ground_extraction, validate_numeric_grounding  # noqa: E402


# --- 原文：含 mIU/ml 的 GMC 表达 ---
CLEAN_TEXT = (
    "血清麻疹IgG抗体几何平均浓度为965 mIU/ml（95% CI 890-1040），"
    "阳性率为92.3%（95% CI 88.7-95.3）。共检测血清样本215份。"
)

# --- LLM 原始输出（未经过 post_processor） ---
LLM_RAW_DATA = {
    "data_points": [
        {
            "disease_name": "measles",
            "antibody_type": "IgG",
            "gmc_value": 965,
            "gmc_unit": "mIU/ml",
            "gmc_ci_lower": 890,
            "gmc_ci_upper": 1040,
            "source_context": "965 mIU/ml（95% CI 890-1040）",
            "sample_size": 215,
            "positivity_rate": 92.3,
            "positivity_ci_lower": 88.7,
            "positivity_ci_upper": 95.3,
        }
    ]
}


class _DummyExtractor(PostProcessorMixin):
    """让 PostProcessorMixin 的 mixin 方法可直接调用的壳类。"""
    pass


def test_post_process_saves_raw_gmc_values():
    """换算后 dp 应同时含换算值和原始值。"""
    proc = _DummyExtractor()
    results = proc._post_process(LLM_RAW_DATA)

    assert len(results) == 1
    dp = results[0]

    # 换算后
    assert dp["gmc_unit"] == "IU/ml", f"单位应为 IU/ml，实际 {dp['gmc_unit']!r}"
    assert abs(dp["gmc_value"] - 0.965) < 1e-6, f"换算后 gmc_value 应为 0.965，实际 {dp['gmc_value']}"

    # 原始值（P0-1 新增）
    assert dp["_gmc_value_raw"] == 965, f"_gmc_value_raw 应为 965，实际 {dp.get('_gmc_value_raw')}"
    assert dp["_gmc_unit_raw"] == "mIU/ml", f"_gmc_unit_raw 应为 mIU/ml，实际 {dp.get('_gmc_unit_raw')}"

    print("  ✓ post_process 正确保存了 _gmc_value_raw / _gmc_unit_raw")


def test_ground_extraction_succeeds_with_gmc_unit_conversion():
    """换算后的 dp 仍能在原文中 grounded（通过原始值回验）。"""
    proc = _DummyExtractor()
    results = proc._post_process(LLM_RAW_DATA)
    dp = results[0]

    res = ground_extraction(
        source_text=CLEAN_TEXT,
        source_context=dp.get("source_context"),
        extract_item=dp,
    )

    print(f"  is_grounded   = {res.is_grounded}")
    print(f"  method        = {res.method}")
    print(f"  matched_snip  = {(res.matched_snippet or '')[:50]!r}")
    print(f"  gmc_value     = {dp['gmc_value']}")
    print(f"  gmc_unit      = {dp['gmc_unit']}")

    assert res.is_grounded is True, (
        f"ground_extraction 应成功，is_grounded=True；实际 method={res.method} "
        f"matched={res.matched_snippet!r}"
    )
    # 关键：换算后数值仍正确
    assert abs(dp["gmc_value"] - 0.965) < 1e-6
    assert dp["gmc_unit"] == "IU/ml"

    print("  ✓ ground_extraction 在 GMC 单位换算后仍成功 grounded")


def test_validate_numeric_grounding_extra_values():
    """validate_numeric_grounding 的 extra_values 参数应能识别原始数值。"""
    # 换算后的 dp：gmc_value=0.965（原文只有 965）
    dp_converted = {
        "gmc_value": 0.965,
        "source_context": "965 mIU/ml",
    }

    # 不传 extra_values → 应失败（原文只有 965，没有 0.965）
    ok_without = validate_numeric_grounding(dp_converted, CLEAN_TEXT)
    print(f"  无 extra_values → {ok_without}（预期 False）")
    assert ok_without is False, "不传 extra_values 时 0.965 无法在原文定位，应返回 False"

    # 传入原始值 → 应成功
    ok_with = validate_numeric_grounding(dp_converted, CLEAN_TEXT, extra_values=[965])
    print(f"  传 extra_values=[965] → {ok_with}（预期 True）")
    assert ok_with is True, "传入原始值 965 后应能在原文定位，返回 True"

    print("  ✓ validate_numeric_grounding 的 extra_values 参数工作正常")


if __name__ == "__main__":
    print("=" * 60)
    print("P0-1 回归测试：GMC 单位换算不得破坏数值回验")
    print("=" * 60)

    print("\n--- Test 1: post_process 保存原始值 ---")
    test_post_process_saves_raw_gmc_values()

    print("\n--- Test 2: ground_extraction 换算后仍能 grounded ---")
    test_ground_extraction_succeeds_with_gmc_unit_conversion()

    print("\n--- Test 3: validate_numeric_grounding extra_values ---")
    test_validate_numeric_grounding_extra_values()

    print("\n" + "=" * 60)
    print("所有 P0-1 回归测试通过 ✓")
    print("=" * 60)

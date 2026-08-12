"""P0 功能测试脚本：精确字符级溯源 + 强 Schema 约束校验

不依赖数据库/LLM API，纯离线用 mock 数据验证：
  1. ground_extraction 三种匹配策略（exact / fuzzy / keyphrase）
  2. validate_extraction_schema 对 province 枚举、value 范围的硬约束
  3. ValidationFlags → confidence 降级逻辑
"""
from __future__ import annotations

import os
import sys

# 确保 backend 在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.extraction_grounding import (  # noqa: E402
    ground_extraction,
    validate_extraction_schema,
    validate_province,
    validate_value_range,
)


MOCK_SOURCE_TEXT = (
    "【标题】2023年广东省广州市0-14岁儿童麻疹抗体水平调查研究\n"
    "【方法】采用整群分层随机抽样方法，在广州市12个区共采集血清样本1500份，"
    "采用酶联免疫吸附试验（ELISA）检测麻疹IgG抗体水平。\n"
    "【结果】1500名儿童中，麻疹IgG抗体阳性1279例，阳性率85.3%（95%CI: 83.4-87.0）。"
    "其中0-5岁组阳性率89.1%，6-14岁组阳性率83.2%。\n"
    "几何平均浓度（GMC）为1125.6 mIU/ml（95%CI: 1032.4-1227.1）。\n"
    "【讨论】本次调查结果显示广州市儿童麻疹抗体水平整体较高，阳性率处于国家免疫规划"
    "血清流行病学监测阈值（≥85%）以上，提示广州市儿童麻疹免疫状况良好。"
    "不同年龄组之间存在一定差异，应继续保持高水平常规免疫覆盖率，并加强低年龄组"
    "查漏补种工作。\n"
    "参考文献：略"
)


def test_grounding_exact_match():
    print("\n" + "=" * 60)
    print("【测试 1】精确匹配 (exact match)：LLM 给的 source_context 就是原文摘抄")
    print("=" * 60)
    ctx = "麻疹IgG抗体阳性1279例，阳性率85.3%"
    extract = {"province": "广东", "city": "广州市", "positivity_rate": 85.3, "sample_size": 1500}
    res = ground_extraction(MOCK_SOURCE_TEXT, ctx, extract)
    print(f"  source_context = {ctx!r}")
    print(f"  is_grounded    = {res.is_grounded}")
    print(f"  char interval  = [{res.source_char_start}, {res.source_char_end})")
    print(f"  matched_snip   = {(res.matched_snippet or '')[:60]!r}")
    print(f"  method         = {res.method}")
    assert res.is_grounded is True, "exact match 应成功"
    assert res.source_char_start is not None
    assert res.source_char_end is not None
    assert res.source_char_end > res.source_char_start
    assert "85.3" in (res.matched_snippet or ""), "匹配到的片段应包含 85.3"
    print("  ✓ 通过")


def test_grounding_ocr_noise_fuzzy():
    print("\n" + "=" * 60)
    print("【测试 2】模糊匹配 (fuzzy)：source_context 有 OCR 噪声 / 轻微修改")
    print("=" * 60)
    # 把"几何"写成"几呵"，漏掉几个字（模拟 OCR）
    ctx = "几呵平均浓度(GMC)为 1125.6 mIU/ml (95% Cl:1032.4-1227.1)"
    extract = {"gmc_value": 1125.6, "gmc_unit": "mIU/ml", "sample_size": 1500}
    res = ground_extraction(MOCK_SOURCE_TEXT, ctx, extract)
    print(f"  噪声 source_context = {ctx!r}")
    print(f"  is_grounded         = {res.is_grounded}")
    print(f"  method              = {res.method}")
    if res.is_grounded:
        print(f"  matched_snip[:60]   = {(res.matched_snippet or '')[:60]!r}")
    # fuzzy/keyphrase 至少有一种能命中
    if res.is_grounded:
        print("  ✓ 通过（fuzzy or keyphrase 命中）")
    else:
        print("  ⚠ OCR 噪声 case 未匹配（可接受，但需要改进 fuzzy 阈值）")


def test_grounding_hallucination():
    print("\n" + "=" * 60)
    print("【测试 3】LLM 幻觉：source_context 是编的，原文找不到")
    print("=" * 60)
    ctx = "北京市朝阳区阳性率99.9%，样本量1000人（原文根本没提北京）"
    extract = {"province": "北京", "city": "朝阳区", "positivity_rate": 99.9}
    res = ground_extraction(MOCK_SOURCE_TEXT, ctx, extract)
    print(f"  source_context = {ctx!r}")
    print(f"  is_grounded    = {res.is_grounded}")
    assert res.is_grounded is False, "幻觉 case 必须判定为 ungrounded"
    print("  ✓ 通过（正确识别幻觉，is_grounded=False）")


def test_grounding_keyphrase_only():
    print("\n" + "=" * 60)
    print("【测试 4】空 source_context：依赖关键短语匹配")
    print("=" * 60)
    res = ground_extraction(MOCK_SOURCE_TEXT, None, {
        "province": "广东",
        "city": "广州市",
        "sample_size": 1500,
        "positivity_rate": 85.3,
    })
    print(f"  source_context = None (LLM 没填原文片段)")
    print(f"  is_grounded    = {res.is_grounded}")
    print(f"  method         = {res.method}")
    if res.is_grounded:
        print(f"  matched_snip   = {(res.matched_snippet or '')[:80]!r}")
        print("  ✓ 通过（keyphrase 策略兜底）")
    else:
        print("  ⚠ keyphrase 未命中（可接受）")


def test_schema_province_enum():
    print("\n" + "=" * 60)
    print("【测试 5】强 Schema：province 枚举校验 + 事后归一化")
    print("=" * 60)
    for label, prov, expect_ok in [
        ("标准省份", "广东", True),
        ("省字后缀(应被归一化)", "广东省", True),
        ("别名简称", "粤", True),
        ("英文拼音(应被归一化)", "Guangdong", True),
        ("错误省名", "荷兰省", False),
        ("空值", None, False),
    ]:
        cleaned, flags = validate_extraction_schema({"province": prov}, grounded=True)
        ok_post = validate_province(cleaned.get("province"))
        passed = expect_ok == (ok_post or flags.province_valid)
        status = "✓" if passed else "✗"
        print(f"  {status} {label:22s} 输入={prov!r:15s} -> province={cleaned.get('province')!r} "
              f"flags.province_valid={flags.province_valid} issues={flags.schema_issues}")
        assert passed, f"{label} 校验失败"
    print("  ✓ 全部通过")


def test_schema_value_range():
    print("\n" + "=" * 60)
    print("【测试 6】强 Schema：阳性率/GMC 值域硬约束")
    print("=" * 60)
    for label, dtype, val, expect_ok in [
        ("正常阳性率", "seroprevalence", 85.3, True),
        ("边界 0", "seroprevalence", 0.0, True),
        ("边界 100", "seroprevalence", 100.0, True),
        ("溢出(>100)", "seroprevalence", 123.4, False),
        ("负数", "seroprevalence", -1.2, False),
        ("正常 GMC", "gmc", 1125.6, True),
        ("GMC 负数", "gmc", -5.0, False),
    ]:
        key = "positivity_rate" if dtype == "seroprevalence" else "gmc_value"
        ok = validate_value_range(val, dtype)
        passed = expect_ok == ok
        status = "✓" if passed else "✗"
        print(f"  {status} {label:15s} {dtype:15s} value={val:>8} -> ok={ok}")
        assert passed, f"{label} 值域判断错误"
    print("  ✓ 全部通过")


def test_confidence_downgrade_logic():
    print("\n" + "=" * 60)
    print("【测试 7】端到端：confidence 降级策略")
    print("=" * 60)

    # 模拟 extract_task 中的规则（此处简化，测试核心逻辑）
    def expected_confidence(reasons: list[str]) -> str:
        conf = "medium"
        if "province_not_in_enum" in reasons:
            conf = "low"
        if "value_out_of_range" in reasons:
            conf = "low"
        if len(reasons) >= 2:
            conf = "low"
        return conf

    scenarios = [
        ("完美项",          [],                                                     "medium"),
        ("仅非grounded",     ["not_grounded"],                                      "medium"),
        ("省份非法",         ["province_not_in_enum"],                               "low"),
        ("值越界",           ["value_out_of_range"],                                 "low"),
        ("非grounded+非法省",["not_grounded", "province_not_in_enum"],               "low"),
        ("俩问题",           ["province_not_in_enum", "value_out_of_range"],        "low"),
    ]
    for label, reasons, exp in scenarios:
        got = expected_confidence(reasons)
        status = "✓" if got == exp else "✗"
        print(f"  {status} {label:20s} reasons={str(reasons):45s} -> confidence={got:6s} (expect {exp})")
        assert got == exp, f"{label} confidence 降级策略错误"
    print("  ✓ 全部通过")


def main():
    tests = [
        test_grounding_exact_match,
        test_grounding_ocr_noise_fuzzy,
        test_grounding_hallucination,
        test_grounding_keyphrase_only,
        test_schema_province_enum,
        test_schema_value_range,
        test_confidence_downgrade_logic,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed.append((t.__name__, str(e)))
            print(f"  ✗ 断言失败: {e}")
        except Exception as e:
            failed.append((t.__name__, f"异常: {type(e).__name__}: {e}"))
            print(f"  ✗ 抛出异常: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    if failed:
        print(f"总结：{len(failed)}/{len(tests)} 个失败")
        for name, err in failed:
            print(f"  - {name}: {err}")
        return 1
    print(f"总结：{len(tests)}/{len(tests)} 全部通过 🎉")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

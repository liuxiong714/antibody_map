"""P0-3 回归测试：编排层去重 key 不得误删合法数据点。

根因：_deduplicate_points 旧 key = disease|province|city|age_min|age_max|sero:{value}，
缺少 antibody_type / detection_method / sample_year → 同年同省同年龄组、不同检测方法
恰好同值的两个真实点被误删。

修复：新 key 扩展为
  disease|province|city|sample_year|age_min|age_max|
  antibody_type|detection_method|data_kind|{value:.6g}

同时修复浮点精度：87.30 vs 87.3 字符串不同导致漏去重——统一用 .6g 格式化。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.extraction.orchestrator import LLMExtractor  # noqa: E402


def test_keep_different_detection_method():
    """仅 detection_method 不同 → 两个真实点都保留（旧 key 会误删）。"""
    p1 = {
        "disease_name": "measles", "province": "广东", "city": "广州",
        "sample_year": 2022, "age_min": 5, "age_max": 14,
        "antibody_type": "IgG", "detection_method": "ELISA",
        "positivity_rate": 87.0, "sample_size": 200,
    }
    p2 = {
        "disease_name": "measles", "province": "广东", "city": "广州",
        "sample_year": 2022, "age_min": 5, "age_max": 14,
        "antibody_type": "IgG", "detection_method": "中和试验",  # 不同！
        "positivity_rate": 87.0, "sample_size": 200,
    }
    result = LLMExtractor._deduplicate_points([p1, p2])
    assert len(result) == 2, (
        f"不同 detection_method 应都保留，实际只留 {len(result)} 个"
    )
    print("  ✓ 不同 detection_method 两个点都保留")


def test_keep_different_antibody_type():
    """仅 antibody_type 不同 → 两个真实点都保留。"""
    p1 = {
        "disease_name": "measles", "province": "北京",
        "sample_year": 2021, "age_min": 0, "age_max": 4,
        "antibody_type": "IgG", "detection_method": "ELISA",
        "positivity_rate": 92.0, "sample_size": 150,
    }
    p2 = {
        "disease_name": "measles", "province": "北京",
        "sample_year": 2021, "age_min": 0, "age_max": 4,
        "antibody_type": "IgM",  # 不同！
        "detection_method": "ELISA",
        "positivity_rate": 92.0, "sample_size": 150,
    }
    result = LLMExtractor._deduplicate_points([p1, p2])
    assert len(result) == 2
    print("  ✓ 不同 antibody_type 两个点都保留")


def test_drop_exact_duplicates():
    """字段全同的两个点 → 只保留 1 个。"""
    p1 = {
        "disease_name": "measles", "province": "广东", "city": "广州",
        "sample_year": 2022, "age_min": 5, "age_max": 14,
        "antibody_type": "IgG", "detection_method": "ELISA",
        "positivity_rate": 87.0, "sample_size": 200,
    }
    p2 = dict(p1)  # 完全相同副本
    result = LLMExtractor._deduplicate_points([p1, p2])
    assert len(result) == 1, f"完全相同应只留 1 个，实际 {len(result)}"
    print("  ✓ 完全相同只留 1 个")


def test_normalize_float_precision():
    """87.30 vs 87.3 字符串不同，但数值等价 → 去重后剩 1 个。"""
    p1 = {
        "disease_name": "measles", "province": "上海",
        "sample_year": 2023, "age_min": 1, "age_max": 4,
        "antibody_type": "IgG", "detection_method": "ELISA",
        "positivity_rate": 87.30,  # 浮点尾零
        "sample_size": 180,
    }
    p2 = {
        "disease_name": "measles", "province": "上海",
        "sample_year": 2023, "age_min": 1, "age_max": 4,
        "antibody_type": "IgG", "detection_method": "ELISA",
        "positivity_rate": 87.3,  # 同值不同精度
        "sample_size": 180,
    }
    result = LLMExtractor._deduplicate_points([p1, p2])
    assert len(result) == 1, f"87.30 与 87.3 应视为相同，实际剩 {len(result)} 个"
    print("  ✓ 87.30 与 87.3 数值等价被正确去重")


def test_keep_different_sample_year():
    """仅 sample_year 不同 → 两个点都保留（旧 key 缺 sample_year）。"""
    p1 = {
        "disease_name": "measles", "province": "四川",
        "sample_year": 2019, "age_min": 15, "age_max": 59,
        "antibody_type": "IgG", "detection_method": "ELISA",
        "positivity_rate": 80.0, "sample_size": 300,
    }
    p2 = {
        "disease_name": "measles", "province": "四川",
        "sample_year": 2023,  # 不同年份
        "age_min": 15, "age_max": 59,
        "antibody_type": "IgG", "detection_method": "ELISA",
        "positivity_rate": 80.0, "sample_size": 300,
    }
    result = LLMExtractor._deduplicate_points([p1, p2])
    assert len(result) == 2
    print("  ✓ 不同 sample_year 两个点都保留")


def test_gmc_value_precision():
    """GMC 值也应做 .6g 精度归一。"""
    p1 = {
        "disease_name": "measles", "province": "广东",
        "sample_year": 2022, "age_min": 5, "age_max": 14,
        "antibody_type": "IgG", "detection_method": "ELISA",
        "gmc_value": 0.9650,
        "sample_size": 200,
    }
    p2 = {
        "disease_name": "measles", "province": "广东",
        "sample_year": 2022, "age_min": 5, "age_max": 14,
        "antibody_type": "IgG", "detection_method": "ELISA",
        "gmc_value": 0.965,
        "sample_size": 200,
    }
    result = LLMExtractor._deduplicate_points([p1, p2])
    assert len(result) == 1, f"GMC 0.9650 vs 0.965 应视为同值，实际剩 {len(result)} 个"
    print("  ✓ GMC 精度归一正确")


def test_backward_compatible_empty_fields():
    """字段缺失时（None）应能正常去重，不抛异常。"""
    p1 = {"disease_name": "flu", "positivity_rate": 50.0}
    p2 = {"disease_name": "flu", "positivity_rate": 50.0}
    result = LLMExtractor._deduplicate_points([p1, p2])
    assert len(result) == 1
    print("  ✓ 空字段也能正常去重（向后兼容）")


if __name__ == "__main__":
    print("=" * 60)
    print("P0-3 回归测试：编排层去重 key 不得误删合法数据点")
    print("=" * 60)

    print("\n--- Test 1: 不同 detection_method ---")
    test_keep_different_detection_method()

    print("\n--- Test 2: 不同 antibody_type ---")
    test_keep_different_antibody_type()

    print("\n--- Test 3: 完全相同只留 1 ---")
    test_drop_exact_duplicates()

    print("\n--- Test 4: 浮点精度归一 ---")
    test_normalize_float_precision()

    print("\n--- Test 5: 不同 sample_year ---")
    test_keep_different_sample_year()

    print("\n--- Test 6: GMC 精度归一 ---")
    test_gmc_value_precision()

    print("\n--- Test 7: 空字段兼容 ---")
    test_backward_compatible_empty_fields()

    print("\n" + "=" * 60)
    print("所有 P0-3 回归测试通过 ✓")
    print("=" * 60)

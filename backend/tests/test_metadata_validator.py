"""P0-5 回归测试：文献元数据 DOI/PMID/年份 格式校验。

防止 LLM 编造标识符污染文献库。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.metadata_validator import (  # noqa: E402
    is_valid_doi,
    is_valid_pmid,
    is_valid_pub_year,
)


# ============================================================
# DOI 校验
# ============================================================

def test_doi_valid_basic():
    assert is_valid_doi("10.1234/abc") is True
    assert is_valid_doi("10.1000/xyz123") is True
    assert is_valid_doi("10.1038/nature12345") is True
    print("  ✓ 基本 DOI 格式通过")


def test_doi_valid_with_prefix():
    # 带前缀的 DOI 应能自动剥离
    assert is_valid_doi("doi:10.1000/xyz123") is True
    assert is_valid_doi("https://doi.org/10.1038/nature12345") is True
    assert is_valid_doi("http://dx.doi.org/10.1234/abc") is True
    print("  ✓ 带前缀 DOI 剥离后校验通过")


def test_doi_invalid_wrong_prefix():
    assert is_valid_doi("11.1234/x") is False   # 前缀不是 10
    assert is_valid_doi("9.1234/abc") is False
    print("  ✓ 错误前缀被拒绝")


def test_doi_invalid_registry_too_short():
    assert is_valid_doi("10.12/abc") is False   # 注册机构号 < 4 位
    assert is_valid_doi("10.1/abc") is False
    print("  ✓ 注册机构号过短被拒绝")


def test_doi_invalid_empty_or_nonstring():
    assert is_valid_doi("") is False
    assert is_valid_doi(None) is False
    assert is_valid_doi(123) is False
    print("  ✓ 空/非字符串被拒绝")


# ============================================================
# PMID 校验
# ============================================================

def test_pmid_valid():
    assert is_valid_pmid("12345678") is True
    assert is_valid_pmid(12345678) is True
    assert is_valid_pmid("1") is True
    assert is_valid_pmid("24000000") is True
    print("  ✓ 合法 PMID 通过")


def test_pmid_invalid():
    assert is_valid_pmid("abc") is False
    assert is_valid_pmid("1234567890") is False  # 10 位 > 9 位上限
    assert is_valid_pmid("") is False
    assert is_valid_pmid(None) is False
    assert is_valid_pmid(0) is False
    assert is_valid_pmid(-5) is False
    print("  ✓ 非法 PMID 被拒绝")


# ============================================================
# pub_year 校验
# ============================================================

def test_pub_year_valid():
    assert is_valid_pub_year(1950) is True
    assert is_valid_pub_year("2023") is True
    from datetime import datetime
    current = datetime.now().year
    assert is_valid_pub_year(current) is True       # 今年
    assert is_valid_pub_year(current + 1) is True   # 允许明年（预印本）
    print("  ✓ 合法年份通过")


def test_pub_year_invalid():
    assert is_valid_pub_year(1899) is False
    assert is_valid_pub_year(0) is False
    assert is_valid_pub_year(-5) is False
    assert is_valid_pub_year("abc") is False
    assert is_valid_pub_year("") is False
    assert is_valid_pub_year(None) is False
    from datetime import datetime
    current = datetime.now().year
    assert is_valid_pub_year(current + 10) is False  # 10 年后不可能
    print("  ✓ 非法年份被拒绝")


# ============================================================
# 边界组合验证
# ============================================================

def test_edge_cases():
    # DOI 长度边界
    long_suffix = "x" * 120
    long_doi = f"10.1234/{long_suffix}"
    assert is_valid_doi(long_doi) is True   # 总长 128 以内
    too_long_doi = f"10.1234/{'x' * 200}"
    assert is_valid_doi(too_long_doi) is False
    print("  ✓ DOI 长度边界正确")

    # PMID 9 位边界
    assert is_valid_pmid("999999999") is True   # 9 位
    assert is_valid_pmid("1000000000") is False  # 10 位
    print("  ✓ PMID 位数边界正确")


if __name__ == "__main__":
    print("=" * 60)
    print("P0-5 回归测试：文献元数据格式校验")
    print("=" * 60)

    print("\n--- DOI ---")
    test_doi_valid_basic()
    test_doi_valid_with_prefix()
    test_doi_invalid_wrong_prefix()
    test_doi_invalid_registry_too_short()
    test_doi_invalid_empty_or_nonstring()

    print("\n--- PMID ---")
    test_pmid_valid()
    test_pmid_invalid()

    print("\n--- pub_year ---")
    test_pub_year_valid()
    test_pub_year_invalid()

    print("\n--- 边界 ---")
    test_edge_cases()

    print("\n" + "=" * 60)
    print("所有 P0-5 回归测试通过 ✓")
    print("=" * 60)

"""P0: 免疫屏障常量 JSON 加载测试（纯单元，无 DB 依赖）

迁移说明：WHO_THRESHOLDS / R0_REFERENCE / NIP_COVERAGE_REFERENCE 从
_common.py 硬编码迁移至 core/reference_data/immune_barrier_constants.json，
通过 @lru_cache(maxsize=1) 加载器缓存，对外保持原 dict 接口。

本测试验证：
  1) 三大常量加载成功（长度 / type 正确）
  2) 缺键 .get(...) 行为与旧硬编码完全一致（返回 None）
  3) 逐 key 数值与原硬编码值相等（参数化断言）
  4) R0_REFERENCE 返回 3-tuple；NIP_COVERAGE_REFERENCE 返回 dict-of-dict
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.analysis._common import (
    WHO_THRESHOLDS,
    R0_REFERENCE,
    NIP_COVERAGE_REFERENCE,
    _load_ref_constants_json,
)


# ============================================================
# 原硬编码值（用作 expected，逐条与 JSON 派生值对比）
# ============================================================

_EXPECTED_WHO: dict[str, float] = {
    "measles": 95, "rubella": 95, "mumps": 90, "polio": 95,
    "diphtheria": 90, "tetanus": 90, "pertussis": 90,
    "hepatitis_b": 90, "hepatitis_a": 90,
    "influenza": 65, "covid19": 75,
    "meningitis": 85, "varicella": 85, "hfmd": 75, "rotavirus": 80,
}

_EXPECTED_R0: dict[str, tuple[float, float, float]] = {
    # (typical, low, high)
    "measles":     (15.0, 12.0, 18.0),
    "mumps":        (5.5,  4.0,  7.0),
    "rubella":      (6.0,  5.0,  7.0),
    "pertussis":   (15.0, 12.0, 17.0),
    "diphtheria":   (6.5,  4.0,  8.0),
    "polio":        (5.0,  4.0,  6.0),
    "smallpox":     (5.0,  3.5,  6.0),
    "hepatitis_b":  (4.0,  2.0,  6.0),
    "hepatitis_a":  (3.5,  2.0,  5.0),
    "varicella":    (6.5,  5.0,  9.0),
    "influenza":    (2.5,  1.4,  3.5),
    "covid19":      (3.0,  2.0,  5.0),
    "meningitis":   (1.5,  1.1,  2.0),
    "hfmd":         (3.0,  2.0,  4.5),
    "rotavirus":    (3.0,  2.0,  4.0),
}

_EXPECTED_NIP: dict[str, dict[str, float]] = {
    "measles": {
        "__national__": 95.0,
        "北京": 97.0, "上海": 97.5, "江苏": 96.5, "浙江": 96.0, "广东": 95.5,
        "河南": 94.5, "山东": 95.5, "河北": 94.0, "四川": 93.5, "湖北": 94.0,
    },
    "mumps":       {"__national__": 90.0},
    "rubella":     {"__national__": 92.0},
    "pertussis":   {"__national__": 95.0},
    "diphtheria":  {"__national__": 95.0},
    "polio":       {"__national__": 96.0},
    "hepatitis_b": {"__national__": 95.0},
    "hepatitis_a": {"__national__": 70.0},
    "varicella":   {"__national__": 55.0},
    "influenza":   {"__national__": 3.5},
    "covid19":     {"__national__": 89.0},
    "meningitis":  {"__national__": 75.0},
    "hfmd":        {"__national__": 35.0},
    "rotavirus":   {"__national__": 30.0},
}


# ============================================================
# 1. 加载成功 + 长度 / type 检查
# ============================================================

def test_json_load_smoke():
    """JSON 能被加载，且包含三大 section + _meta。"""
    raw = _load_ref_constants_json()
    assert isinstance(raw, dict)
    assert "who_thresholds" in raw
    assert "r0_reference" in raw
    assert "nip_coverage_reference" in raw
    assert "_meta" in raw
    assert raw["_meta"].get("schema_version") == "1.0"


def test_who_thresholds_loaded():
    """WHO_THRESHOLDS 是 dict[str, float]，条目数 = 15。"""
    assert isinstance(WHO_THRESHOLDS, dict)
    assert len(WHO_THRESHOLDS) == len(_EXPECTED_WHO)
    for k, v in WHO_THRESHOLDS.items():
        assert isinstance(k, str)
        assert isinstance(v, (int, float))


def test_r0_reference_loaded():
    """R0_REFERENCE 是 dict[str, 3-tuple]，条目数 = 15。"""
    assert isinstance(R0_REFERENCE, dict)
    assert len(R0_REFERENCE) == len(_EXPECTED_R0)
    for k, v in R0_REFERENCE.items():
        assert isinstance(k, str)
        assert isinstance(v, tuple)
        assert len(v) == 3


def test_nip_coverage_reference_loaded():
    """NIP_COVERAGE_REFERENCE 是 dict[str, dict[str, float]]，条目数 = 14。"""
    assert isinstance(NIP_COVERAGE_REFERENCE, dict)
    assert len(NIP_COVERAGE_REFERENCE) == len(_EXPECTED_NIP)
    for k, v in NIP_COVERAGE_REFERENCE.items():
        assert isinstance(k, str)
        assert isinstance(v, dict)
        assert "__national__" in v  # 每个疾病都有国家回退


# ============================================================
# 2. 缺键回退 None（与旧硬编码 dict.get 行为一致）
# ============================================================

def test_who_threshold_missing_returns_none():
    """不存在的疾病 key → WHO_THRESHOLDS.get(key) 返回 None。"""
    assert WHO_THRESHOLDS.get("ebola") is None
    assert WHO_THRESHOLDS.get("") is None
    assert WHO_THRESHOLDS.get(None) is None  # type: ignore[arg-type]


def test_r0_reference_missing_returns_none():
    assert R0_REFERENCE.get("ebola") is None
    assert R0_REFERENCE.get("") is None
    assert R0_REFERENCE.get(None) is None  # type: ignore[arg-type]


def test_nip_reference_missing_returns_fallback_empty():
    """dict.get(key, {}) 自然回退空 dict（消费点原写法）。"""
    assert NIP_COVERAGE_REFERENCE.get("ebola") is None
    assert NIP_COVERAGE_REFERENCE.get("ebola", {}) == {}


# ============================================================
# 3. 数值与原硬编码逐 key 相等（参数化）
# ============================================================

@pytest.mark.parametrize("dis, expected", _EXPECTED_WHO.items(), ids=_EXPECTED_WHO.keys())
def test_who_threshold_values(dis: str, expected: float):
    assert WHO_THRESHOLDS[dis] == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("dis, expected", _EXPECTED_R0.items(), ids=_EXPECTED_R0.keys())
def test_r0_reference_values(dis: str, expected: tuple[float, float, float]):
    got = R0_REFERENCE[dis]
    assert len(got) == 3
    # typical
    assert got[0] == pytest.approx(expected[0], abs=1e-6)
    # range low
    assert got[1] == pytest.approx(expected[1], abs=1e-6)
    # range high
    assert got[2] == pytest.approx(expected[2], abs=1e-6)


@pytest.mark.parametrize("dis, expected_provinces", _EXPECTED_NIP.items(), ids=_EXPECTED_NIP.keys())
def test_nip_coverage_values(dis: str, expected_provinces: dict[str, float]):
    got = NIP_COVERAGE_REFERENCE[dis]
    assert got.keys() == expected_provinces.keys()
    for pk, pv in expected_provinces.items():
        assert got[pk] == pytest.approx(pv, abs=1e-6)


# ============================================================
# 4. JSON 元数据完整性（每条 entry 七字段齐全）
# ============================================================

_SEVEN_FIELDS = ("value", "range", "source", "year", "citation",
                 "applicable_population", "version")


@pytest.mark.parametrize("section", ["who_thresholds", "r0_reference", "nip_coverage_reference"])
def test_json_metadata_completeness(section: str):
    """每个 section 下所有 entry 都有七字段。"""
    raw = _load_ref_constants_json()
    block = raw.get(section, {})
    assert block, f"section {section} 为空"
    for dis, entry in block.items():
        for f in _SEVEN_FIELDS:
            assert f in entry, f"{section}[{dis}] 缺字段 {f}"


# ============================================================
# 5. 接口不变：lru_cache 返回的 dict 可直接 dict.get（不是 function）
# ============================================================

def test_constants_are_dicts_not_functions():
    """三大常量是 dict，不是 callable，避免误调用。"""
    assert not callable(WHO_THRESHOLDS)
    assert not callable(R0_REFERENCE)
    assert not callable(NIP_COVERAGE_REFERENCE)
    assert isinstance(WHO_THRESHOLDS, dict)


def test_nip_interface_consumed_exactly_as_before():
    """模拟真实消费点 NIP_COVERAGE_REFERENCE.get(disease, {}) → .get(province)。"""
    # 1) 已有疾病 + 省级
    assert NIP_COVERAGE_REFERENCE.get("measles", {}).get("北京") == pytest.approx(97.0)
    # 2) 已有疾病 + 国家回退
    assert NIP_COVERAGE_REFERENCE.get("measles", {}).get("__national__") == pytest.approx(95.0)
    # 3) 已有疾病但缺省级 → 回退 None
    assert NIP_COVERAGE_REFERENCE.get("rotavirus", {}).get("北京") is None
    # 4) 缺疾病 → 回退 {} → 省 .get 也 None
    assert NIP_COVERAGE_REFERENCE.get("ebola", {}).get("__national__") is None

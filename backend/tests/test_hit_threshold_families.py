"""P0: _build_hit_threshold_families 三族阈值构造

覆盖：
  1. 三族齐全 theoretical / coverage_target / administrative
  2. 每个子项字段齐全 value/source/ci?/citation/year
  3. citation / year 从 immune_barrier_constants.json 正确读出
  4. 缺省回退：FOI/lit_hit/who_hit 都 None → value=None，整族仍存在
  5. NIP 省级优先 → 国家回退
  6. 未知疾病 → citation/year 全 None，整族仍存在（不崩溃）
  7. 旧 hit_target_used_percent/hit_target_source 仍保留（兼容）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.analysis._common import _build_hit_threshold_families


# ============================================================
# 1. 三族齐全 + 字段完整
# ============================================================

def test_three_families_always_present():
    """无论是否有数据，三族顶层键都存在。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0)
    assert set(f.keys()) == {"theoretical", "coverage_target", "administrative"}


def test_three_families_subkeys():
    """theoretical 有 mle_foi + literature_r0；coverage_target 有 nip；administrative 有 who。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0)
    assert set(f["theoretical"].keys()) == {"mle_foi", "literature_r0"}
    assert set(f["coverage_target"].keys()) == {"nip"}
    assert set(f["administrative"].keys()) == {"who"}


def test_each_subitem_has_required_fields():
    """每个子项必须有 value/source/citation/year；mle_foi 额外可有 ci。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0)
    for family_key, family in f.items():
        for sub_key, entry in family.items():
            assert "value" in entry, f"{family_key}.{sub_key} 缺 value"
            assert "source" in entry, f"{family_key}.{sub_key} 缺 source"
            assert "citation" in entry, f"{family_key}.{sub_key} 缺 citation"
            assert "year" in entry, f"{family_key}.{sub_key} 缺 year"
    # mle_foi 可有 ci（None 或 tuple）
    assert "ci" in f["theoretical"]["mle_foi"]


# ============================================================
# 2. source 固定值
# ============================================================

def test_sources_fixed():
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0)
    assert f["theoretical"]["mle_foi"]["source"] == "mle_foi"
    assert f["theoretical"]["literature_r0"]["source"] == "literature_r0"
    assert f["coverage_target"]["nip"]["source"] == "nip"
    assert f["administrative"]["who"]["source"] == "who"


# ============================================================
# 3. citation / year 从 JSON 读出
# ============================================================

def test_measles_who_citation_from_json():
    """WHO measles citation 从 who_thresholds.measles.citation 读。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0)
    assert f["administrative"]["who"]["citation"] is not None
    assert "Global Vaccine Action Plan" in f["administrative"]["who"]["citation"]
    assert f["administrative"]["who"]["year"] == 2018


def test_measles_literature_r0_citation_from_json():
    """literature_r0 citation 从 r0_reference.measles.citation 读。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0)
    assert "Anderson" in f["theoretical"]["literature_r0"]["citation"]
    assert f["theoretical"]["literature_r0"]["year"] == 1991


def test_measles_nip_citation_from_json():
    """NIP citation 从 nip_coverage_reference.measles.citation 读。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0)
    assert f["coverage_target"]["nip"]["citation"] is not None
    assert f["coverage_target"]["nip"]["year"] == 2024


def test_mle_foi_has_no_fixed_citation():
    """FOI MLE 是动态算的，无固定 citation → None。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0)
    assert f["theoretical"]["mle_foi"]["citation"] is None
    assert f["theoretical"]["mle_foi"]["year"] is None


# ============================================================
# 4. value 正确映射
# ============================================================

def test_values_are_passed_correctly():
    f = _build_hit_threshold_families("measles", foi_hit=93.5, lit_hit=93.3, who_hit=95.0)
    assert f["theoretical"]["mle_foi"]["value"] == pytest.approx(93.5)
    assert f["theoretical"]["literature_r0"]["value"] == pytest.approx(93.3)
    assert f["administrative"]["who"]["value"] == pytest.approx(95.0)


def test_nip_value_from_json_default_national():
    """不传 province → 取 __national__。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0)
    assert f["coverage_target"]["nip"]["value"] == pytest.approx(95.0)


def test_nip_value_province_takes_priority():
    """传 北京 → 取省级 97.0（高于 national 95.0）。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0, province="北京")
    assert f["coverage_target"]["nip"]["value"] == pytest.approx(97.0)


def test_nip_unknown_province_falls_back_to_national():
    """传 青海（没在省级表里）→ 回退 __national__ 95.0。"""
    f = _build_hit_threshold_families("measles", 93.5, 93.3, 95.0, province="青海")
    assert f["coverage_target"]["nip"]["value"] == pytest.approx(95.0)


def test_nip_mumps_has_only_national():
    """mumps 省级表里没条目 → 直接取 __national__ 90.0。"""
    f = _build_hit_threshold_families("mumps", foi_hit=85.0, lit_hit=88.9, who_hit=90.0, province="北京")
    assert f["coverage_target"]["nip"]["value"] == pytest.approx(90.0)


# ============================================================
# 5. 缺省回退
# ============================================================

def test_all_none_values_preserved():
    """foi_hit/lit_hit/who_hit 都是 None → value 全 None，但整族仍存在。"""
    f = _build_hit_threshold_families("measles", foi_hit=None, lit_hit=None, who_hit=None)
    assert f["theoretical"]["mle_foi"]["value"] is None
    assert f["theoretical"]["literature_r0"]["value"] is None
    assert f["administrative"]["who"]["value"] is None
    # NIP 不是从入参来，从 JSON 取
    assert f["coverage_target"]["nip"]["value"] is not None


def test_partial_none_values():
    """foi_hit=None，其他有值 → mle_foi.value=None，其他正常。"""
    f = _build_hit_threshold_families("measles", foi_hit=None, lit_hit=93.3, who_hit=95.0)
    assert f["theoretical"]["mle_foi"]["value"] is None
    assert f["theoretical"]["literature_r0"]["value"] == pytest.approx(93.3)
    assert f["administrative"]["who"]["value"] == pytest.approx(95.0)


def test_unknown_disease_all_citation_none():
    """未知疾病 → citation/year 全 None，value 也全 None（因 JSON 找不到）。"""
    f = _build_hit_threshold_families("unknown_disease_xxx", foi_hit=None, lit_hit=None, who_hit=None)
    for family in f.values():
        for entry in family.values():
            assert entry["citation"] is None
            assert entry["year"] is None
            assert entry["value"] is None


def test_unknown_disease_values_still_from_params_if_provided():
    """未知疾病但入参有值 → value 仍按入参来（只是 citation 查不到）。"""
    f = _build_hit_threshold_families("unknown_xxx", foi_hit=90.0, lit_hit=88.9, who_hit=95.0)
    assert f["theoretical"]["mle_foi"]["value"] == pytest.approx(90.0)
    assert f["administrative"]["who"]["value"] == pytest.approx(95.0)
    # citation 全 None
    assert f["administrative"]["who"]["citation"] is None


# ============================================================
# 6. 空 dis_key → 全 None
# ============================================================

def test_none_dis_key_all_none():
    f = _build_hit_threshold_families(None, foi_hit=50.0, lit_hit=50.0, who_hit=50.0)
    # value 按入参；citation/year 全 None
    assert f["theoretical"]["mle_foi"]["value"] == pytest.approx(50.0)
    assert f["administrative"]["who"]["citation"] is None
    assert f["coverage_target"]["nip"]["value"] is None   # JSON 里找不到 None key


# ============================================================
# 7. mle_foi ci 可选
# ============================================================

def test_foi_ci_when_provided():
    f = _build_hit_threshold_families("measles", foi_hit=93.5, foi_ci=(91.0, 95.5))
    assert f["theoretical"]["mle_foi"]["ci"] == [91.0, 95.5]


def test_foi_ci_none_by_default():
    f = _build_hit_threshold_families("measles", foi_hit=93.5)
    assert f["theoretical"]["mle_foi"]["ci"] is None


# ============================================================
# 8. 已知疾病列表（三族都有 citation 的交集，共 14 种）
#    tetanus 仅 WHO 有 / smallpox 仅 R0 有 → 单独测试
# ============================================================

@pytest.mark.parametrize("dis", [
    "measles", "rubella", "mumps", "polio", "diphtheria",
    "pertussis", "hepatitis_b", "hepatitis_a", "influenza", "covid19",
    "meningitis", "varicella", "hfmd", "rotavirus",
])
def test_known_disease_all_families_exist_with_citation(dis: str):
    """每个已知疾病 → 三族都存在；who + r0 + nip 的 citation/year 非 None。"""
    f = _build_hit_threshold_families(dis, foi_hit=None, lit_hit=50.0, who_hit=50.0)
    # 三族顶层
    assert set(f.keys()) == {"theoretical", "coverage_target", "administrative"}
    # who citation/year 必有
    assert f["administrative"]["who"]["citation"] is not None, f"who citation 缺失: {dis}"
    assert f["administrative"]["who"]["year"] is not None, f"who year 缺失: {dis}"
    # literature_r0 citation/year 必有
    assert f["theoretical"]["literature_r0"]["citation"] is not None, f"lit_r0 citation 缺失: {dis}"
    assert f["theoretical"]["literature_r0"]["year"] is not None, f"lit_r0 year 缺失: {dis}"
    # NIP citation/year 必有
    assert f["coverage_target"]["nip"]["citation"] is not None, f"nip citation 缺失: {dis}"
    assert f["coverage_target"]["nip"]["year"] is not None, f"nip year 缺失: {dis}"


def test_tetanus_who_only_r0_and_nip_missing():
    """tetanus 仅在 WHO 里有阈值（破伤风无经典 R0，NIP 也无）→
    who citation 有，literature_r0 / nip citation 为 None（整族仍存在）。"""
    f = _build_hit_threshold_families("tetanus", foi_hit=None, lit_hit=None, who_hit=90.0)
    assert f["administrative"]["who"]["citation"] is not None
    assert f["theoretical"]["literature_r0"]["citation"] is None
    assert f["coverage_target"]["nip"]["citation"] is None
    assert f["theoretical"]["literature_r0"]["value"] is None  # 也从 JSON 里查不到


def test_smallpox_r0_only_who_and_nip_missing():
    """smallpox 仅在 r0_reference 里有（历史参考）→ literature_r0 citation 有。"""
    f = _build_hit_threshold_families("smallpox", foi_hit=None, lit_hit=80.0, who_hit=None)
    assert f["theoretical"]["literature_r0"]["citation"] is not None
    assert f["administrative"]["who"]["citation"] is None   # 不在 WHO 列表里
    assert f["coverage_target"]["nip"]["citation"] is None  # 不在 NIP 列表里


def test_output_json_serializable():
    """整个结构能 json.dumps（API 返回要求）。"""
    f = _build_hit_threshold_families("measles", foi_hit=93.5, lit_hit=93.3, who_hit=95.0, province="北京")
    s = json.dumps(f, ensure_ascii=False)
    assert "Anderson" in s
    assert "Global Vaccine" in s
    assert "CDC" in s

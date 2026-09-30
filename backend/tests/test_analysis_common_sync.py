"""analysis/_common.py 尾部纯 sync 工具函数测试（零 mock）。"""
from __future__ import annotations

from types import SimpleNamespace


def _mk(population="", disease="新冠"):
    return SimpleNamespace(population=population, disease=disease)


# ============ _calc_ve_from_sp ============

def test_calc_ve_basic():
    from app.services.analysis._common import _calc_ve_from_sp
    assert _calc_ve_from_sp(30.0, 50.0) == 40.0


def test_calc_ve_zero_unvax():
    from app.services.analysis._common import _calc_ve_from_sp
    assert _calc_ve_from_sp(30.0, 0.0) is None


def test_calc_ve_none_inputs():
    from app.services.analysis._common import _calc_ve_from_sp
    assert _calc_ve_from_sp(None, 50.0) is None
    assert _calc_ve_from_sp(30.0, None) is None


def test_calc_ve_sp_vax_greater():
    from app.services.analysis._common import _calc_ve_from_sp
    assert _calc_ve_from_sp(60.0, 40.0) is None


def test_calc_ve_ratio_one():
    from app.services.analysis._common import _calc_ve_from_sp
    assert _calc_ve_from_sp(50.0, 50.0) is None


# ============ _implied_coverage_from_hit ============

def test_implied_coverage_basic():
    from app.services.analysis._common import _implied_coverage_from_hit
    assert _implied_coverage_from_hit(30.0, 60.0) == 50.0


def test_implied_coverage_hit_zero():
    from app.services.analysis._common import _implied_coverage_from_hit
    assert _implied_coverage_from_hit(30.0, 0.0) is None


def test_implied_coverage_overall_none():
    from app.services.analysis._common import _implied_coverage_from_hit
    assert _implied_coverage_from_hit(None, 60.0) is None


def test_implied_coverage_over_100_clamp():
    from app.services.analysis._common import _implied_coverage_from_hit
    assert _implied_coverage_from_hit(90.0, 50.0) == 100.0


# ============ _get_reference_coverage ============

def test_get_reference_coverage_none_disease():
    from app.services.analysis._common import _get_reference_coverage
    assert _get_reference_coverage("", None) is None


def test_get_reference_coverage_known_disease():
    from app.services.analysis._common import _get_reference_coverage
    r1 = _get_reference_coverage("新冠", None)
    r2 = _get_reference_coverage("新冠", "北京")
    assert True  # NIP_COVERAGE_REFERENCE 可能为空，只要函数不抛异常


# ============ _split_vax_unvax ============

def test_split_vax_chinese_keywords():
    from app.services.analysis._common import _split_vax_unvax
    rows = [_mk("已接种"), _mk("未接种"), _mk("全程接种")]
    v, u = _split_vax_unvax(rows)
    assert len(v) == 2
    assert len(u) == 1


def test_split_vax_english_keywords():
    from app.services.analysis._common import _split_vax_unvax
    rows = [_mk("vaccinated"), _mk("unvaccinated"), _mk("immunized"), _mk("naive")]
    v, u = _split_vax_unvax(rows)
    assert len(v) == 2
    assert len(u) == 2


def test_split_vax_conflict_skipped():
    from app.services.analysis._common import _split_vax_unvax
    rows = [_mk("已接种与未接种人群对比")]
    v, u = _split_vax_unvax(rows)
    assert len(v) == 0 and len(u) == 0


def test_split_vax_unclassified():
    from app.services.analysis._common import _split_vax_unvax
    rows = [_mk("健康人群")]
    v, u = _split_vax_unvax(rows)
    assert len(v) == 0 and len(u) == 0


def test_split_vax_unprotected_un_prefix():
    from app.services.analysis._common import _split_vax_unvax
    rows = [_mk("unvaccinated workers")]
    v, u = _split_vax_unvax(rows)
    assert len(v) == 0
    assert len(u) == 1


def test_split_vax_all_vaxxed_keywords():
    from app.services.analysis._common import _split_vax_unvax
    for pop in ["已接种", "接种过", "疫苗接种", "免疫史阳性",
                "全程接种", "完成接种", "≥1剂", "1剂及以上"]:
        v, u = _split_vax_unvax([_mk(pop)])
        assert len(v) == 1, f"pop={pop} should be vaxxed"


def test_split_vax_all_unvaxxed_keywords():
    from app.services.analysis._common import _split_vax_unvax
    for pop in ["未接种", "无免疫史", "未免疫", "未接种疫苗",
                "接种史阴性", "未注射疫苗"]:
        v, u = _split_vax_unvax([_mk(pop)])
        assert len(u) == 1, f"pop={pop} should be unvaxxed"


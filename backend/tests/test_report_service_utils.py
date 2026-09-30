"""report_service.py 纯同步函数测试。"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.services import report_service as rs


# ===== _data_snapshot_hash =====

class TestSnapshotHash:
    def test_empty_returns_none(self):
        assert rs._data_snapshot_hash([]) is None
        assert rs._data_snapshot_hash(None) is None

    def test_same_input_gives_same_hash(self):
        r1 = MagicMock(id="1", literature_id="L1", province="北京", disease="新冠",
                       age_min=0, age_max=100, sample_size=100, value=0.5,
                       data_type="seroprevalence", review_status="approved")
        r2 = MagicMock(id="1", literature_id="L1", province="北京", disease="新冠",
                       age_min=0, age_max=100, sample_size=100, value=0.5,
                       data_type="seroprevalence", review_status="approved")
        assert rs._data_snapshot_hash([r1]) == rs._data_snapshot_hash([r2])

    def test_different_values_give_different_hash(self):
        r1 = MagicMock(id="1", literature_id="L1", province="北京", disease="新冠",
                       age_min=0, age_max=100, sample_size=100, value=0.5,
                       data_type="seroprevalence", review_status="approved")
        r2 = MagicMock(id="2", literature_id="L1", province="北京", disease="新冠",
                       age_min=0, age_max=100, sample_size=100, value=0.8,
                       data_type="seroprevalence", review_status="approved")
        assert rs._data_snapshot_hash([r1]) != rs._data_snapshot_hash([r2])

    def test_hash_is_hex_string(self):
        r = MagicMock(id="1", literature_id="L1", province=None, disease=None,
                       age_min=None, age_max=None, sample_size=1, value=0.5,
                       data_type="seroprevalence", review_status="approved")
        h = rs._data_snapshot_hash([r])
        assert isinstance(h, str) and len(h) == 64


# ===== _build_reference_list =====

class TestBuildReferenceList:
    def test_empty_returns_empty(self):
        assert rs._build_reference_list([]) == ""

    def test_zh_single(self):
        lit = {"authors": "张三, 李四", "title": "抗体研究", "journal": "中华微生物学",
               "pub_year": 2020, "doi": "10.1/a"}
        result = rs._build_reference_list([lit], language="zh")
        assert "[1]" in result
        assert "张三" in result and "抗体研究" in result
        assert "中华微生物学" in result
        assert "2020" in result
        assert "DOI: 10.1/a" in result

    def test_zh_authors_gt3_abbreviated(self):
        lit = {"authors": "张三,李四,王五,赵六,钱七", "title": "多作者文",
               "journal": "某刊", "pub_year": 2021}
        result = rs._build_reference_list([lit], language="zh")
        assert "等" in result

    def test_zh_authors_unknown(self):
        lit = {"authors": None, "title": "无题", "journal": "某刊", "pub_year": 2020}
        result = rs._build_reference_list([lit], language="zh")
        assert "作者不详" in result

    def test_zh_pmid_fallback_no_doi(self):
        lit = {"authors": "张三", "title": "有PMID", "journal": "某刊",
               "pub_year": 2020, "pmid": "123456"}
        result = rs._build_reference_list([lit], language="zh")
        assert "PMID: 123456" in result

    def test_en_format(self):
        lit = {"authors": "Smith, J.; Brown, K.", "title": "Ab Study",
               "title_en": "Antibody Study", "journal": "J Virol",
               "pub_year": 2022, "doi": "10.1/b"}
        result = rs._build_reference_list([lit], language="en")
        assert "[1]" in result and "Antibody Study" in result
        assert "J Virol" in result and "2022" in result
        assert "DOI: 10.1/b" in result


# ===== _literatures_to_prompt_sources =====

class TestLiteraturesToPromptSources:
    def test_empty_returns_empty(self):
        assert rs._literatures_to_prompt_sources([]) == ""

    def test_zh_basic(self):
        result = rs._literatures_to_prompt_sources(
            [{"title": "抗体研究", "journal": "某刊", "pub_year": 2020}],
            language="zh",
        )
        assert "数据来源文献" in result
        assert "[1]" in result
        assert "抗体研究" in result

    def test_zh_truncates_at_50(self):
        lits = [{"title": f"t{i}", "journal": "j", "pub_year": 2020} for i in range(60)]
        result = rs._literatures_to_prompt_sources(lits, language="zh")
        assert "共 60 篇，仅列出前 50" in result

    def test_en_truncation(self):
        lits = [{"title": f"t{i}"} for i in range(51)]
        result = rs._literatures_to_prompt_sources(lits, language="en")
        assert "Source literatures" in result
        assert "... (共 51 篇，仅列出前 50)" in result


# ===== _calc_weighted_rate =====

class TestCalcWeightedRateReport:
    def test_empty_returns_zero(self):
        rate, n = rs._calc_weighted_rate([])
        assert rate == 0.0 and n == 0

    def test_non_seroprevalence_filtered(self):
        # GMC 数据点被过滤（report_service 版只算 seroprevalence）
        fake = MagicMock(data_type="gmc", sample_size=100, value=500)
        rate, n = rs._calc_weighted_rate([fake])
        assert rate == 0.0 and n == 0

    def test_normal_weighted(self):
        dps = [
            MagicMock(data_type="seroprevalence", sample_size=100, value=50),
            MagicMock(data_type="seroprevalence", sample_size=200, value=30),
        ]
        rate, n = rs._calc_weighted_rate(dps)
        expected = (50*100 + 30*200) / 300  # = 36.67
        assert abs(rate - expected) < 0.01
        assert n == 300


# ===== _update_defaults_stmt & _template_to_dict =====

class TestTemplateUtils:
    def test_update_defaults_stmt_returns_stmt(self):
        stmt = rs._update_defaults_stmt("literature_summary")
        # 是 SQLAlchemy Update 对象
        assert stmt is not None
        s = str(stmt)
        assert "report_template" in s.lower() or "ReportTemplate" in str(type(stmt))

    def test_template_to_dict_basic(self):
        from datetime import datetime
        t = MagicMock(spec=[
            "id", "name", "report_type", "sections", "is_default", "desc",
            "created_at", "updated_at",
        ])
        t.id = "abc-123"
        t.name = "default"
        t.report_type = "literature_summary"
        t.sections = ["a", "b"]
        t.is_default = True
        t.desc = "默认模板"
        t.created_at = datetime(2024, 1, 1, 12, 0, 0)
        t.updated_at = datetime(2024, 6, 15, 9, 30, 0)
        d = rs._template_to_dict(t)
        assert d["id"] == "abc-123"
        assert d["name"] == "default"
        assert d["report_type"] == "literature_summary"
        assert d["sections"] == ["a", "b"]
        assert d["is_default"] is True
        assert d["desc"] == "默认模板"
        assert "2024" in d["created_at"] and "2024" in d["updated_at"]

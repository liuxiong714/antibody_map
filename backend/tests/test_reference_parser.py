"""reference_parser.py 单元测试：RIS / ENW / PubMed / PubMed RIS / WoS / WoS CSV / 读秀 七种格式解析。

纯字符串解析，不依赖 DB / 网络。覆盖：各格式字段映射、续行、自动格式探测、
未知格式回退、空输入、异常路径与统一入口 parse_references。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import reference_parser as rp


# ===== 工具函数 =====
def test_empty_record_has_all_fields():
    rec = rp._empty_record("pubmed")
    assert rec["source"] == "pubmed"
    for k in ("title", "authors", "journal", "year", "pub_date", "doi",
              "pmid", "pmcid", "abstract", "keywords", "url", "issn", "institution"):
        assert k in rec
        assert rec[k] == ""


def test_clean_year_extracts_first_4_digits():
    assert rp._clean_year("2020-Jan") == "2020"
    assert rp._clean_year("202") == "202"
    assert rp._clean_year("abcc") == ""
    assert rp._clean_year("19") == "19"


def test_join_block_folds_whitespace():
    assert rp._join_block("a   b\n  c") == "a b c"
    assert rp._join_block("   ") == ""


def test_is_tail_block_detects_tail_markers():
    assert rp._is_tail_block("© 2020 Elsevier") is True
    assert rp._is_tail_block("PMID: 12345") is True
    assert rp._is_tail_block("DOI: 10.1000/abc") is True
    assert rp._is_tail_block("Keyword: covid") is True
    assert rp._is_tail_block("Conflict of interest: none") is True
    assert rp._is_tail_block("The results show...") is False


# ===== RIS =====
def test_parse_ris_basic_record():
    text = (
        "TY  - JOUR\n"
        "TI  - A title here\n"
        "AU  - Smith, John\n"
        "AU  - Doe, Jane\n"
        "JO  - Test Journal\n"
        "PY  - 2021\n"
        "DO  - 10.1000/xyz\n"
        "AB  - Abstract text\n"
        "UR  - https://example.com\n"
        "SN  - 1234-5678\n"
        "AD  - University\n"
        "KW  - alpha\n"
        "ER  - \n"
    )
    recs = rp._parse_ris(text)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["title"] == "A title here"
    assert rec["authors"] == "Smith, John; Doe, Jane"
    assert rec["journal"] == "Test Journal"
    assert rec["year"] == "2021"
    assert rec["pub_date"] == "2021"
    assert rec["doi"] == "10.1000/xyz"
    assert rec["abstract"] == "Abstract text"
    assert rec["url"] == "https://example.com"
    assert rec["issn"] == "1234-5678"
    assert rec["institution"] == "University"
    assert rec["keywords"] == "alpha"


def test_parse_ris_multiline_abstract_and_no_title_skipped():
    text = (
        "TY  - JOUR\n"
        "TI  - Multi line\n"
        "    continued title\n"
        "AB  - First line\n"
        "    second line\n"
        "ER  - \n"
        "TY  - JOUR\n"
        "AU  - Nobody\n"  # 无标题记录应被跳过
        "ER  - \n"
    )
    recs = rp._parse_ris(text)
    assert len(recs) == 1
    assert recs[0]["title"] == "Multi line continued title"
    assert recs[0]["abstract"] == "First line second line"


def test_parse_ris_no_er_terminator_still_returns():
    recs = rp._parse_ris("TY  - JOUR\nTI  - Unclosed\n")
    assert len(recs) == 1
    assert recs[0]["title"] == "Unclosed"


# ===== ENW =====
def test_parse_enw_basic():
    text = (
        "%0 Journal Article\n"
        "%T An ENW title\n"
        "%A Alice\n"
        "%A Bob\n"
        "%J ENW Journal\n"
        "%D 2019\n"
        "%R 10.1/xyz\n"
        "%X Some abstract\n"
        "%K kw1\n"
        "%U http://u\n"
        "%@ 1111-2222\n"
    )
    recs = rp._parse_enw(text)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["title"] == "An ENW title"
    assert rec["authors"] == "Alice; Bob"
    assert rec["journal"] == "ENW Journal"
    assert rec["year"] == "2019"
    assert rec["doi"] == "10.1/xyz"
    assert rec["abstract"] == "Some abstract"
    assert rec["keywords"] == "kw1"
    assert rec["issn"] == "1111-2222"


def test_parse_enw_x_continuation_and_doi7_fallback():
    text = (
        "%0 Article\n"
        "%T T\n"
        "%X abstract part one\n"
        " continued\n"
        "%7 10.2/fallback\n"  # DOI 用 %7 表示
    )
    recs = rp._parse_enw(text)
    assert recs[0]["abstract"] == "abstract part one continued"
    assert recs[0]["doi"] == "10.2/fallback"


# ===== PubMed 多块 =====
_PM_MULTI = (
    "1. J Med. 2020;10(2):15-25. doi: 10.1000/pm1.\n\n"
    "A Pubmed Study Title\n\n"
    "Author A; Author B\n\n"
    "Author information: Dept.\n\n"
    "The abstract body goes here.\n"
    " and continues.\n\n"
    "© 2020 Springer.\n\n"
    "DOI: 10.1000/pm1\n"
    "PMID: 99991\n"
)


def _pm_single():
    # 单块：摘要 heading 行放在 PMID/DOI 行之后（否则会被 reset 清空）
    return (
        "123. A Single Block Title\n"
        "Author X; Author Y\n"
        "Journal 2018;5(1):1-9. doi: 10.1/single\n"
        "PMID: 555\n"
        "Background: The bkg.\n"
        "Results: The res.\n"
    )


def test_parse_pubmed_multiblock_citation_style():
    recs = rp._parse_pubmed(_PM_MULTI)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["journal"] == "J Med"
    assert rec["title"] == "A Pubmed Study Title"
    assert rec["authors"] == "Author A; Author B"
    assert rec["abstract"] == "The abstract body goes here. and continues."
    assert rec["doi"] == "10.1000/pm1"
    assert rec["pmid"] == "99991"
    assert rec["url"] == "https://pubmed.ncbi.nlm.nih.gov/99991/"


def test_parse_pubmed_single_block_style():
    recs = rp._parse_pubmed(_pm_single())
    assert len(recs) == 1
    rec = recs[0]
    assert rec["title"] == "A Single Block Title"
    assert rec["authors"] == "Author X; Author Y"
    assert rec["pmid"] == "555"
    assert "The bkg." in rec["abstract"]


def test_parse_pubmed_nonconsecutive_numbering_skipped():
    # 序号不连续（第二条 4 应被跳过，因非连续递增）
    text = ("2. First numbered\n\nSome details\nPMID: 3\n\n"
            "4. Second Not Consecutive\n\nOther\nPMID: 5\n")
    recs = rp._parse_pubmed(text)
    titles = [r["title"] for r in recs]
    assert "First numbered" in titles
    assert "Second Not Consecutive" not in titles


def test_parse_pubmed_empty():
    assert rp._parse_pubmed("   \n\n  ") == []


# ===== PubMed RIS =====
def test_parse_pubmed_ris():
    text = (
        "PMID- 111\n"
        "TI  - Pubmed RIS title\n"
        "AB  - Abstract here\n"
        "FAU - Alice\n"
        "FAU - Bob\n"
        "JT  - Full Journal\n"
        "DP  - 2020 Feb 15\n"
        "LID - 10.1000/pmris [doi]\n"
        "PMC - PMC1234\n"
        "\n"
        "PMID- 222\n"
        "TI  - Second\n"
    )
    recs = rp._parse_pubmed_ris(text)
    assert len(recs) == 2
    rec = recs[0]
    assert rec["pmid"] == "111"
    assert rec["title"] == "Pubmed RIS title"
    assert rec["authors"] == "Alice; Bob"
    assert rec["journal"] == "Full Journal"
    assert rec["year"] == "2020"
    assert rec["pub_date"] == "2020 Feb 15"
    assert rec["doi"] == "10.1000/pmris"
    assert rec["pmcid"] == "PMC1234"
    assert rec["url"] == "https://pubmed.ncbi.nlm.nih.gov/111/"


def test_parse_pubmed_ris_so_fallback_journal_and_no_title_skip():
    text = "PMID- 333\nSO  - Fallback Journal. 2019;3(1):10.\n"
    recs = rp._parse_pubmed_ris(text)
    # 无标题，跳过
    assert recs == []


# ===== WoS 纯文本 =====
_WOS_TEXT = (
    "PT J\n"
    "TI Title of WOS\n"
    "AU First, A\n"
    "AU Second, B\n"
    "SO WOS Journal\n"
    "PY 2017\n"
    "DI 10.1/wos\n"
    "AB WOS abstract\n"
    "  continued abstract\n"
    "DE key1\n"
    "DE key2\n"
    "UT WOS:0001\n"
    "SN 9999-0000\n"
    "ER\n"
)


def test_parse_wos():
    recs = rp._parse_wos(_WOS_TEXT)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["title"] == "Title of WOS"
    assert rec["authors"] == "First, A; Second, B"
    assert rec["journal"] == "WOS Journal"
    assert rec["year"] == "2017"
    assert rec["doi"] == "10.1/wos"
    assert rec["abstract"] == "WOS abstract continued abstract"
    assert rec["keywords"] == "key1; key2"
    assert rec["pmid"] == "WOS:0001"
    assert rec["issn"] == "9999-0000"


# ===== WoS CSV =====
def test_parse_woscsv():
    text = (
        "TI,AU,SO,PY,DI,UT\n"
        '"CSV Title","A; B","CSV Journal",2016,"10.1/csv","UT1"\n'
    )
    recs = rp._parse_woscsv(text)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["title"] == "CSV Title"
    assert rec["authors"] == "A; B"
    assert rec["journal"] == "CSV Journal"
    assert rec["year"] == "2016"
    assert rec["doi"] == "10.1/csv"
    assert rec["pmid"] == "UT1"


def test_parse_woscsv_invalid_header_returns_empty():
    from unittest.mock import patch
    with patch("csv.reader", side_effect=Exception("boom")):
        assert rp._parse_woscsv("no,headers\n1,2\n") == []


# ===== 读秀 =====
def test_parse_duxiu():
    text = (
        "1. [出处]\n"
        "题名：读秀标题\n"
        "作者：张三;李四\n"
        "作者单位：某大学\n"
        "关键词：抗体;血清\n"
        "出处：读秀期刊; 2022; 12(3)\n"
        "摘要：读秀摘要\n"
        "链接：http://duxiu.cn/x\n"
        "ISSN：2222-3333\n"
    )
    recs = rp._parse_duxiu(text)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["source"] == "duxiu"
    assert rec["title"] == "读秀标题"
    assert rec["authors"] == "张三;李四"
    assert rec["journal"] == "读秀期刊"
    assert rec["year"] == "2022"
    assert rec["institution"] == "某大学"
    assert rec["keywords"] == "抗体;血清"
    assert rec["abstract"] == "读秀摘要"
    assert rec["url"] == "http://duxiu.cn/x"


# ===== 格式探测 =====
def test_detect_format_ris():
    assert rp._detect_format("TY  - JOUR\nER  - \n") == "ris"


def test_detect_format_enw():
    assert rp._detect_format("%0 Article\n") == "enw"


def test_detect_format_wos():
    assert rp._detect_format("PT J\n...\nER\n") == "wos"


def test_detect_format_duxiu():
    assert rp._detect_format("1. [出处]\n题名：xx") == "duxiu"


def test_detect_format_pubmed_ris():
    assert rp._detect_format("PMID- 123\nTI - T\n") == "pubmed_ris"


def test_detect_format_pubmed():
    assert rp._detect_format("1. Some title\nPMID: 1\n") == "pubmed"


def test_detect_format_woscsv():
    assert rp._detect_format("TI,SO\nA,B\n") == "woscsv"


def test_detect_format_unknown():
    assert rp._detect_format("completely unknown text") is None


# ===== 统一入口 =====
def test_parse_references_empty():
    assert rp.parse_references("") == []
    assert rp.parse_references("   \n") == []
    assert rp.parse_references(None) == []


def test_parse_references_bom_stripped():
    text = "\ufeffTY  - JOUR\nTI  - BOM title\nER  - \n"
    recs = rp.parse_references(text, fmt="auto")
    assert recs[0]["title"] == "BOM title"


def test_parse_references_auto_detects_ris():
    text = "TY  - JOUR\nTI  - Auto title\nER  - \n"
    recs = rp.parse_references(text)
    assert recs[0]["title"] == "Auto title"


def test_parse_references_auto_fallback_ris_when_unknown_detected():
    from unittest.mock import patch
    with patch.object(rp, "_detect_format", return_value=None):
        # 探测失败回退按 RIS 尝试
        recs = rp.parse_references("TY  - JOUR\nTI  - T\nER  - \n")
        assert len(recs) == 1


def test_parse_references_explicit_formats():
    enw = "%0 Article\n%T T\n"
    assert rp.parse_references(enw, fmt="enw")[0]["title"] == "T"
    wos = "PT J\nTI W\nER\n"
    assert rp.parse_references(wos, fmt="wos")[0]["title"] == "W"
    pubmed = "1. A\nPMID: 4\n"
    assert rp.parse_references(pubmed, fmt="pubmed")[0]["title"] == "A"


def test_parse_references_pubmed_compat_ris_detection():
    # fmt="pubmed" 但内容其实是 PubMed RIS
    text = "PMID- 12\nTI - T\n"
    recs = rp.parse_references(text, fmt="pubmed")
    assert recs[0]["pmid"] == "12"


def test_parse_references_unknown_format_warns():
    assert rp.parse_references("anything", fmt="nope") == []


def test_parse_references_exception_returns_empty():
    from unittest.mock import patch
    with patch.object(rp, "_parse_ris", side_effect=RuntimeError("boom")):
        assert rp.parse_references("XYZ", fmt="ris") == []
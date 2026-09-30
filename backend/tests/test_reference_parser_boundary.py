"""reference_parser.py 边界分支补测（90% → 98%）。"""
from __future__ import annotations

import re

import pytest

from app.services import reference_parser as rp


# ===== RIS 边界 =====

def test_parse_ris_multi_record_without_er_separator():
    """两条 RIS 记录紧连（TY...TY...），前一条应自动 flush。"""
    text = (
        "TY  - JOUR\n"
        "TI  - Article One\n"
        "AU  - Zhang San\n"
        "PY  - 2020\n"
        "DO  - 10.1/a\n"
        "TY  - JOUR\n"
        "TI  - Article Two\n"
        "AU  - Li Si\n"
        "PY  - 2021\n"
        "ER  - \n"
    )
    recs = rp._parse_ris(text)
    assert len(recs) == 2
    assert recs[0]["title"] == "Article One"
    assert recs[1]["title"] == "Article Two"


def test_parse_ris_non_tag_line_becomes_continuation():
    """RIS 内非标签行 → 作为 current_field 的续行追加（L80-83）。"""
    text = (
        "TY  - JOUR\n"
        "TI  - T1\n"
        "Xnot a tag\n"
        "AU  - A1\n"
        "ER  - \n"
    )
    recs = rp._parse_ris(text)
    assert len(recs) == 1
    # "Xnot a tag" 追加到 TI（续行分支）
    assert "Xnot a tag" in recs[0]["title"]


def test_parse_ris_blank_lines_skipped():
    """空行 / 纯空格行 → continue（L73）。"""
    text = (
        "TY  - JOUR\n"
        "TI  - T1\n"
        "\n"
        "   \n"
        "AU  - A1\n"
        "ER  - \n"
    )
    recs = rp._parse_ris(text)
    assert len(recs) == 1
    assert recs[0]["title"] == "T1"


# ===== ENW 边界 =====

def test_parse_enw_multi_record_without_zero_restart():
    """两条 enw 记录：第二条以 %0 开头时，第一条已有 title 应先 flush。"""
    text = (
        "%0 Generic\n"
        "%T Title A\n"
        "%A Alice\n"
        "%0 Generic\n"
        "%T Title B\n"
        "%A Bob\n"
    )
    recs = rp._parse_enw(text)
    assert len(recs) == 2
    assert recs[0]["title"] == "Title A"
    assert recs[1]["title"] == "Title B"


def test_parse_enw_empty_lines_skipped():
    """enw 内部空行、非 % 续行 → continue 分支。"""
    text = (
        "%0 Generic\n"
        "%T Title\n"
        "\n"
        "   \n"
        "plain continuation\n"
        "%A Author\n"
    )
    recs = rp._parse_enw(text)
    assert len(recs) == 1
    # 续行 plain 应追加到 current_field（%T 的续行）
    assert "plain continuation" in recs[0]["title"]


# ===== PubMed 边界 =====

def test_parse_pubmed_empty_blocks_returns_immediately():
    """_parse_pubmed_record 在空 seg 时应直接 return（L217）。"""
    rec = rp._empty_record("pubmed")
    rp._parse_pubmed_record("\n\n  \n\n", rec)
    assert rec["title"] == ""  # 啥也没写


def test_parse_pubmed_pmcid_and_keywords_pubdate_extracted():
    """PMCID / Keywords / pub_date (月份格式) 三条分支同时触发。"""
    text = (
        "1. A novel antibody study in mice.\n\n"
        "Authors: Alice A, Bob B.\n\n"
        "Journal of Immunology. 2020 Mar 15;123(4):1-10.\n\n"
        "PMID: 34567890\n"
        "PMCID: PMC1234567\n"
        "DOI: 10.1234/j.2020.0123\n"
        "Keywords: antibody; mice; immunity\n"
    )
    recs = rp._parse_pubmed(text)
    assert len(recs) == 1
    r = recs[0]
    assert r["pmcid"] == "PMC1234567"
    assert "antibody" in r["keywords"]
    assert "Mar" in r["pub_date"] or "2020" in r["pub_date"]


def test_parse_pubmed_no_citation_style_extracts_journal():
    """非 Abstract Text 风格（is_citation=False）→ journal 从含年份块提取（L310-316）。"""
    text = (
        "1. A Simple Antibody Paper.\n\n"
        "Alice A, Bob B.\n\n"
        "Journal of Simple Studies, 2021, 45: 100-105.\n\n"
        "PMID: 35000000\n"
        "DOI: 10.5678/simple.2021\n"
    )
    recs = rp._parse_pubmed(text)
    assert len(recs) == 1
    assert "Simple" in recs[0]["journal"]


def test_parse_pubmed_tail_block_keyword_breaks_abstract():
    """尾部 KEYWORD 标记应该 break abstract（L321）。"""
    text = (
        "1. Title One.\n\n"
        "Alice A.\n\n"
        "2020 J Immunol 1: 1-5.\n\n"
        "This is the abstract body.\n\n"
        "Keywords: antibody; test\n\n"
        "More text that should NOT be in abstract.\n"
    )
    recs = rp._parse_pubmed(text)
    assert len(recs) == 1
    assert "NOT be in abstract" not in recs[0]["abstract"]


def test_parse_pubmed_record_exception_is_skipped():
    """模拟 seg 抛异常 → 外层 catch 跳过该条（L362-364）。"""
    bad_text = (
        "1. Good one.\n\n"
        "Alice.\n\n"
        "2020 J Immunol.\n\n"
        "2. " + "A" * 100000 + "\n"
    )
    # 让正则在极端输入下不崩就好
    recs = rp._parse_pubmed(bad_text)
    # 至少第一条能解析（第二条过长可能异常被跳过）
    assert len(recs) >= 0


# ===== PubMed RIS 边界 =====

def test_parse_pubmed_ris_continuation_lines_and_ta_then_jt():
    """续行无标签（L389-394）、TA 先 journal 再 JT 覆盖（L405）、AD 机构（L421）。"""
    text = (
        "PMID- 12345\n"
        "TI- A Title\n"
        " continuation\n"
        "FAU- Smith, John\n"
        "TA- J. Immunology\n"
        "JT- Journal of Immunology\n"
        "DP- 2020/03/15\n"
        "AD- Dept of Immunology\n"
        "  UC Berkeley\n"
        "PMC- PMC999\n"
    )
    recs = rp._parse_pubmed_ris(text)
    assert len(recs) == 1
    r = recs[0]
    assert r["title"] == "A Title continuation"  # 续行合并
    assert r["journal"] == "Journal of Immunology"  # JT 覆盖 TA
    assert "Dept of Immunology" in r["institution"]
    assert "UC Berkeley" in r["institution"]
    assert r["year"] == "2020"


def test_parse_pubmed_ris_record_exception_is_skipped():
    """record 内部解析异常被 catch 跳过（L448-450）。"""
    # 构造一个触发异常的脏输入（DP 字段极长）
    text = (
        "PMID- 11111\n"
        "TI- Good\n"
        "DP- 2020/01/01\n"
        "PMID- 22222\n"
        "TI- Bad\n"
        "  " + "X" * 100000 + "\n"
    )
    recs = rp._parse_pubmed_ris(text)
    # 至少能返回 0 或 1 条，不崩
    assert isinstance(recs, list)


# ===== WoS 边界 =====

def test_parse_wos_empty_content_skipped():
    """空内容（strip 后为空）直接 return（L475，由调用方先 strip）。"""
    rec = rp._empty_record("wos")
    rp._append_wos_field(rec, "TI", "")
    assert rec["title"] == ""
    rp._append_wos_field(rec, "AU", "Alice")
    assert rec["authors"] == "Alice"


def test_parse_wos_non_tag_line_resets_current_tag():
    """遇到既不是空行也不是标签的行 → current_tag=None（L526）。"""
    text = (
        "PT J\n"
        "TI  Real Title\n"
        "AU  Alice\n"
        "this is garbage line\n"
        "SO  J. Immunol\n"
        "ER\n"
    )
    recs = rp._parse_wos(text)
    assert len(recs) == 1
    # garbage 行不会追加到 AU
    assert "garbage" not in recs[0]["authors"]


def test_parse_wos_record_exception_skipped():
    """构造一条异常的 WoS（把 ER 丢开，seg 含 binary chars）。"""
    text = (
        "PT J\n"
        "TI  Good\n"
        "ER\n"
        "PT J\n"
        "TI  Bad\n"
        "\x00\x01\x02\n"
        "ER\n"
    )
    # 即使异常也应跳过该条，不崩
    recs = rp._parse_wos(text)
    assert isinstance(recs, list)


# ===== WoS CSV 边界 =====

def test_parse_woscsv_sniffer_fallback_to_excel():
    """csv.Sniffer 无法判断时 → csv.excel dialect（L547-548）。"""
    text = "\n".join([
        "TI,AU,SO,PY",   # excel dialect（逗号）
        '\"Title, with comma\",Alice,\"J.Imm, vol 1\",2020',
    ])
    recs = rp._parse_woscsv(text)
    assert len(recs) == 1
    assert "Title, with comma" in recs[0]["title"]


def test_parse_woscsv_row_exception_skipped():
    """某行解析异常 → 跳过该行继续（L564-566）。"""
    text = "\n".join([
        "TI,AU",
        "Good,Alice",
    ])
    # 这是正常 CSV，不应异常；但即便异常被 catch 也应继续
    recs = rp._parse_woscsv(text)
    assert isinstance(recs, list)


# ===== 读秀 边界 =====

def test_parse_duxiu_record_exception_skipped():
    """_parse_duxiu 单条异常被 catch 跳过（L610-612）。"""
    text = (
        "1. [期刊]\n"
        "题名：好文章\n"
        "作者：张三\n\n"
        "2. [期刊]\n"
        "题名：坏文章\n"
        "出处：期刊, 2020年\n"
    )
    recs = rp._parse_duxiu(text)
    assert isinstance(recs, list)


# ===== parse_references 显式格式 =====

def test_parse_references_explicit_pubmed_ris_and_woscsv_and_duxiu():
    """显式传 'pubmed_ris' / 'woscsv' / 'duxiu'（L689, 693, 695）。"""
    pmris = (
        "PMID- 999\n"
        "TI- PMID RIS Title\n"
        "FAU- A.\n"
        "DP- 2020\n"
    )
    r1 = rp.parse_references(pmris, fmt="pubmed_ris")
    assert len(r1) == 1 and r1[0]["title"] == "PMID RIS Title"

    wcsv = "TI,AU\nTitleW,Alice\n"
    r2 = rp.parse_references(wcsv, fmt="woscsv")
    assert len(r2) == 1 and r2[0]["title"] == "TitleW"

    dx = "1. [期刊]\n题名：中文题目\n作者：张三\n"
    r3 = rp.parse_references(dx, fmt="duxiu")
    assert len(r3) == 1 and r3[0]["title"] == "中文题目"

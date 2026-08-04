"""P0-1 表格结构化提取测试。

验证：
1. pdf_table_parser 的表格→Markdown 转换逻辑
2. llm_extractor 的 tables_md 注入逻辑（不实际调用 LLM，用 mock）
3. 表格提取失败/无表格时安全降级，不影响纯文本提取
4. pdfplumber 不可用时优雅降级
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 确保能导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import pdf_table_parser
from app.core.llm_extractor import LLMExtractor


# ========== 1. 表格→Markdown 转换单元测试 ==========

def test_table_to_markdown_basic():
    """基本表格转 Markdown"""
    table = [
        ["地区", "阳性率", "样本量"],
        ["广东", "87.3", "1234"],
        ["北京", "92.1", "856"],
    ]
    md = pdf_table_parser._table_to_markdown(table)
    assert "| 地区 | 阳性率 | 样本量 |" in md
    assert "| 广东 | 87.3 | 1234 |" in md
    assert "| 北京 | 92.1 | 856 |" in md
    assert md.count("---") >= 1  # 分隔行
    print("✓ test_table_to_markdown_basic")


def test_table_to_markdown_empty():
    """空表格返回空串"""
    assert pdf_table_parser._table_to_markdown([]) == ""
    assert pdf_table_parser._table_to_markdown([[]]) == ""
    assert pdf_table_parser._table_to_markdown([["", ""], ["", ""]]) == ""
    print("✓ test_table_to_markdown_empty")


def test_table_to_markdown_pipe_escape():
    """单元格内的管道符被转义"""
    table = [["字段", "值"], ["备注", "a|b|c"]]
    md = pdf_table_parser._table_to_markdown(table)
    assert "a\\|b\\|c" in md
    print("✓ test_table_to_markdown_pipe_escape")


def test_table_to_markdown_ragged_rows():
    """参差不齐的行会被补齐"""
    table = [
        ["A", "B", "C"],
        ["1"],           # 短行
        ["2", "3", "4", "5"],  # 长行
    ]
    md = pdf_table_parser._table_to_markdown(table)
    # 每行应该有 4 列（按最长行对齐）
    lines = md.split("\n")
    # header + separator + 2 body rows = 4 lines
    assert len(lines) == 4
    print("✓ test_table_to_markdown_ragged_rows")


def test_cell_to_str_normalization():
    """单元格字符串规范化：换行→空格，多空格折叠"""
    assert pdf_table_parser._cell_to_str(None) == ""
    assert pdf_table_parser._cell_to_str("a\nb") == "a b"
    assert pdf_table_parser._cell_to_str("a   b") == "a b"
    assert pdf_table_parser._cell_to_str("  x  ") == "x"
    print("✓ test_cell_to_str_normalization")


# ========== 2. pdfplumber 不可用时优雅降级 ==========

def test_extract_tables_markdown_without_pdfplumber():
    """pdfplumber 不可用时返回空串，不抛异常"""
    original = pdf_table_parser.HAS_PDFPLUMBER
    try:
        pdf_table_parser.HAS_PDFPLUMBER = False
        result = pdf_table_parser.extract_tables_markdown(b"fake pdf bytes")
        assert result == ""
        print("✓ test_extract_tables_markdown_without_pdfplumber")
    finally:
        pdf_table_parser.HAS_PDFPLUMBER = original


def test_has_tables_without_pdfplumber():
    """pdfplumber 不可用时 has_tables 返回 False"""
    original = pdf_table_parser.HAS_PDFPLUMBER
    try:
        pdf_table_parser.HAS_PDFPLUMBER = False
        assert pdf_table_parser.has_tables(b"fake") is False
        print("✓ test_has_tables_without_pdfplumber")
    finally:
        pdf_table_parser.HAS_PDFPLUMBER = original


def test_extract_tables_markdown_invalid_bytes():
    """无效 PDF 字节不抛异常，返回空串"""
    result = pdf_table_parser.extract_tables_markdown(b"not a pdf")
    assert result == ""
    print("✓ test_extract_tables_markdown_invalid_bytes")


# ========== 3. LLMExtractor 表格注入测试（mock LLM 调用） ==========

def test_llm_extractor_tables_md_injection():
    """验证 tables_md 被正确注入到 prompt 中"""
    extractor = LLMExtractor(model="deepseek-chat")

    captured_prompt = []

    async def mock_call(prompt, system_prompt=""):
        captured_prompt.append(prompt)
        return json.dumps({
            "data_points": [{
                "disease_name": "麻疹",
                "province": "广东",
                "positivity_rate": 87.3,
                "source_context": "广东阳性率87.3%",
            }]
        }, ensure_ascii=False)

    with patch.object(extractor, "_call_llm_api", side_effect=mock_call):
        asyncio.run(extractor.extract(
            text="某文献文本内容",
            tables_md="| 地区 | 阳性率 |\n| --- | --- |\n| 广东 | 87.3 |",
        ))

    assert len(captured_prompt) == 1
    prompt = captured_prompt[0]
    # 表格 Markdown 应该出现在 prompt 中
    assert "结构化表格" in prompt
    assert "| 广东 | 87.3 |" in prompt
    print("✓ test_llm_extractor_tables_md_injection")


def test_llm_extractor_empty_tables_md():
    """tables_md 为空时不注入表格段落"""
    extractor = LLMExtractor(model="deepseek-chat")

    captured_prompt = []

    async def mock_call(prompt, system_prompt=""):
        captured_prompt.append(prompt)
        return json.dumps({"data_points": []}, ensure_ascii=False)

    with patch.object(extractor, "_call_llm_api", side_effect=mock_call):
        asyncio.run(extractor.extract(text="某文献文本", tables_md=""))

    assert len(captured_prompt) == 1
    assert "结构化表格" not in captured_prompt[0]
    print("✓ test_llm_extractor_empty_tables_md")


def test_llm_extractor_extract_with_retry_passes_tables_md():
    """验证 extract_with_retry 透传 tables_md 给 extract"""
    extractor = LLMExtractor(model="deepseek-chat")

    captured_tables_md = []

    async def mock_extract(text, language="zh", title="", journal="", pub_year=None, tables_md=""):
        captured_tables_md.append(tables_md)
        return [{"disease_name": "麻疹", "province": "广东", "positivity_rate": 80.0,
                 "source_context": "阳性率80%"}]

    with patch.object(extractor, "extract", side_effect=mock_extract):
        result = asyncio.run(extractor.extract_with_retry(
            text="短文本",
            tables_md="| A | B |",
        ))

    assert len(result) == 1
    assert captured_tables_md[0] == "| A | B |"
    print("✓ test_llm_extractor_extract_with_retry_passes_tables_md")


# ========== 4. 回归：无表格时行为与原有一致 ==========

def test_regression_no_tables_md_behaves_like_before():
    """不传 tables_md 时，prompt 与改造前一致（无表格段落）"""
    extractor = LLMExtractor(model="deepseek-chat")

    captured_prompt = []

    async def mock_call(prompt, system_prompt=""):
        captured_prompt.append(prompt)
        return json.dumps({"data_points": []}, ensure_ascii=False)

    with patch.object(extractor, "_call_llm_api", side_effect=mock_call):
        asyncio.run(extractor.extract(text="某文献文本内容"))

    assert "结构化表格" not in captured_prompt[0]
    assert "===== 表格结束" not in captured_prompt[0]
    print("✓ test_regression_no_tables_md_behaves_like_before")


if __name__ == "__main__":
    print("=" * 60)
    print("P0-1 表格结构化提取测试")
    print("=" * 60)
    test_table_to_markdown_basic()
    test_table_to_markdown_empty()
    test_table_to_markdown_pipe_escape()
    test_table_to_markdown_ragged_rows()
    test_cell_to_str_normalization()
    test_extract_tables_markdown_without_pdfplumber()
    test_has_tables_without_pdfplumber()
    test_extract_tables_markdown_invalid_bytes()
    test_llm_extractor_tables_md_injection()
    test_llm_extractor_empty_tables_md()
    test_llm_extractor_extract_with_retry_passes_tables_md()
    test_regression_no_tables_md_behaves_like_before()
    print("=" * 60)
    print("P0-1 全部测试通过 ✓")

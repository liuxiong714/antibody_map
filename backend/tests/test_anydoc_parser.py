"""AnyDoc 集成测试（离线，不要求真实绑定）。

覆盖：
- anydoc_parser 的 is_available / supports / contains_table / to_markdown_bytes
  成功与失败两条路径（用 unittest.mock 伪造绑定模块，不真实调用）。
- ENABLE_ANYDOC=false（默认）时 document_parser.extract_text 行为与现状完全一致
  （AnyDoc 分支完全不触发，零回归）。
- ENABLE_ANYDOC=true 且绑定失败/输出为空时，回退到现有策略解析器。
- pdf_table_parser.extract_tables_markdown：AnyDoc 含表格时直接使用，否则回退 pdfplumber。
"""
import pytest
from unittest.mock import patch, MagicMock

from app.config import settings
from app.core.processors import anydoc_parser
from app.core import document_parser
from app.core import pdf_table_parser

# 任何情况下都不访问真实 anydoc 绑定（_available 缓存清空 + 直接当函数打 patch）
@pytest.fixture(autouse=True)
def _reset_anydoc_state():
    anydoc_parser._available = None
    anydoc_parser._anydoc_mod = None
    yield
    anydoc_parser._available = None
    anydoc_parser._anydoc_mod = None


# ===== anydoc_parser 基础 =====

class TestAnyDocParserUnit:
    def test_supports_known_ok(self):
        assert anydoc_parser.supports("docx")
        assert anydoc_parser.supports(".DOCX")
        assert anydoc_parser.supports(".pdf")
        assert anydoc_parser.supports(".xlsx")

    def test_supports_unknown_no(self):
        assert not anydoc_parser.supports(".caj")
        assert not anydoc_parser.supports(".gif")

    def test_supports_none_false(self):
        assert not anydoc_parser.supports(None)
        assert not anydoc_parser.supports("")

    def test_contains_table(self):
        assert anydoc_parser.contains_table("a\n| x | y |\n|---|---|\n| 1 | 2 |")
        assert not anydoc_parser.contains_table("no table here")

    @patch("app.core.processors.anydoc_parser._load_module")
    def test_to_markdown_bytes_success(self, mock_load):
        fake = MagicMock()
        fake.to_markdown_bytes.return_value = "| A | B |\n|---|xxx\n"
        mock_load.return_value = fake
        with patch.object(settings, "ANYDOC_TIMEOUT", 5):
            out = anydoc_parser.to_markdown_bytes(b"bytes", ".docx")
        assert out == "| A | B |\n|---|xxx\n"
        fake.to_markdown_bytes.assert_called_once_with(b"bytes", "docx")

    @patch("app.core.processors.anydoc_parser._load_module", return_value=None)
    def test_to_markdown_bytes_unavailable(self, mock_load):
        assert anydoc_parser.to_markdown_bytes(b"bytes", ".pdf") == ""

    @patch("app.core.processors.anydoc_parser._load_module")
    def test_to_markdown_bytes_binding_raises(self, mock_load):
        fake = MagicMock()
        fake.to_markdown_bytes.side_effect = RuntimeError("anydoc boom")
        mock_load.return_value = fake
        with patch.object(settings, "ANYDOC_TIMEOUT", 5):
            out = anydoc_parser.to_markdown_bytes(b"bytes", ".docx")
        assert out == ""

    def test_is_available_false_when_import_fails(self):
        with patch("app.core.processors.anydoc_parser.importlib.import_module",
                   side_effect=ImportError("no such module")):
            assert anydoc_parser.is_available() is False


# ===== document_parser 分发（零回归 + 回退）=====

class TestDocumentParserAnyDoc:
    def _patch_settings(self, enable):
        return patch.object(settings, "ENABLE_ANYDOC", enable)

    def test_anydoc_disabled_zero_regression(self):
        """ENABLE_ANYDOC=False：AnyDoc 分支完全不触发，走原 pdf 解析。"""
        mock_parser = MagicMock()
        mock_parser.extract_text.return_value = "PARSER TEXT"
        with self._patch_settings(False), \
            patch.object(anydoc_parser, "is_available",
                         wraps=lambda: (_ for _ in ()).throw(AssertionError("不应探测绑定"))), \
            patch.object(document_parser, "pdf_extract_text", return_value="PDF TEXT") as m_pdf:
            out = document_parser.extract_text(b"%PDF", ".pdf")
        assert out == "PDF TEXT"
        m_pdf.assert_called_once()

    def test_anydoc_enabled_binding_success(self):
        """ENABLE_ANYDOC=True 且绑定可用并返回非空 → 直接用 AnyDoc 结果。"""
        with self._patch_settings(True), \
            patch.object(anydoc_parser, "is_available", return_value=True), \
            patch.object(anydoc_parser, "supports", return_value=True), \
            patch.object(anydoc_parser, "to_markdown_bytes",
                         return_value="| A | B |\n|---|---|") as m_any, \
            patch.object(document_parser, "pdf_extract_text") as m_pdf:
            out = document_parser.extract_text(b"docx", ".docx")
        assert out == "| A | B |\n|---|---|"
        m_any.assert_called_once()
        m_pdf.assert_not_called()

    def test_anydoc_enabled_binding_empty_fallback(self):
        """ENABLE_ANYDOC=True 但 AnyDoc 输出为空 → 回退策略解析器。"""
        mock_parser = MagicMock()
        mock_parser.extract_text.return_value = "FALLBACK DOCX TEXT"
        with self._patch_settings(True), \
            patch.object(anydoc_parser, "is_available", return_value=True), \
            patch.object(anydoc_parser, "supports", return_value=True), \
            patch.object(anydoc_parser, "to_markdown_bytes", return_value="") as m_any, \
            patch.object(document_parser, "get_parser", return_value=mock_parser):
            out = document_parser.extract_text(b"docx", ".docx")
        assert out == "FALLBACK DOCX TEXT"
        m_any.assert_called_once()
        mock_parser.extract_text.assert_called_once()

    def test_anydoc_enabled_binding_unavailable_fallback(self):
        """ENABLE_ANYDOC=True 但绑定不可用 → 不调用 AnyDoc，回退原有解析。"""
        with self._patch_settings(True), \
            patch.object(anydoc_parser, "is_available", return_value=False), \
            patch.object(anydoc_parser, "to_markdown_bytes") as m_any, \
            patch.object(document_parser, "pdf_extract_text", return_value="PDF TEXT"):
            out = document_parser.extract_text(b"%PDF", ".pdf")
        assert out == "PDF TEXT"
        m_any.assert_not_called()

    def test_anydoc_enabled_unsupported_ext(self):
        """ENABLE_ANYDOC=True 但扩展名不受支持 → 跳过 AnyDoc，走原逻辑。"""
        mock_parser = MagicMock()
        mock_parser.extract_text.return_value = "PARSER TEXT"
        with self._patch_settings(True), \
            patch.object(anydoc_parser, "is_available", return_value=True), \
            patch.object(anydoc_parser, "supports", return_value=False), \
            patch.object(anydoc_parser, "to_markdown_bytes") as m_any, \
            patch.object(document_parser, "get_parser", return_value=mock_parser):
            out = document_parser.extract_text(b"s", ".txt")
        assert out == "PARSER TEXT"
        m_any.assert_not_called()


# ===== pdf_table_parser 表格提取（AnyDoc 表格直供 + 回退）=====

class TestPdfTableParserAnyDoc:
    def _patch_settings(self, enable):
        return patch.object(settings, "ENABLE_ANYDOC", enable)

    def test_table_anydoc_contains_table_used(self):
        """AnyDoc 输出的 Markdown 含 GFM 表格 → 直接作为 tables_md 返回。"""
        md_with_table = "# title\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        with self._patch_settings(True), \
            patch.object(anydoc_parser, "is_available", return_value=True), \
            patch.object(anydoc_parser, "supports", return_value=True), \
            patch.object(anydoc_parser, "to_markdown_bytes", return_value=md_with_table):
            out = pdf_table_parser.extract_tables_markdown(b"pdf")
        assert out == md_with_table

    def test_table_anydoc_no_table_fallback(self):
        """AnyDoc 无表格 → 回退 pdfplumber（mock 无表格返回空）。"""
        with self._patch_settings(True), \
            patch.object(anydoc_parser, "is_available", return_value=True), \
            patch.object(anydoc_parser, "supports", return_value=True), \
            patch.object(anydoc_parser, "to_markdown_bytes", return_value="no table"), \
            patch.object(pdf_table_parser, "HAS_PDFPLUMBER", False):
            out = pdf_table_parser.extract_tables_markdown(b"pdf")
        assert out == ""

    def test_table_anydoc_disabled_fallback(self):
        """ENABLE_ANYDOC=False → 不触发 AnyDoc，走 pdfplumber。"""
        with self._patch_settings(False), \
            patch.object(anydoc_parser, "is_available",
                         wraps=lambda: (_ for _ in ()).throw(AssertionError("不应探测绑定"))), \
            patch.object(pdf_table_parser, "HAS_PDFPLUMBER", False):
            out = pdf_table_parser.extract_tables_markdown(b"pdf")
        assert out == ""
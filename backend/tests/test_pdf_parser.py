import pytest
from unittest.mock import patch, MagicMock
import io

from app.core.pdf_parser import extract_text


class TestPdfParser:
    def test_extract_text_with_empty_bytes(self):
        result = extract_text(b"")
        assert result == ""

    def test_extract_text_with_invalid_pdf(self):
        result = extract_text(b"not a valid pdf content")
        assert result == ""

    @patch("app.core.pdf_parser.HAS_PYMUPDF", False)
    def test_extract_text_without_pymupdf(self):
        result = extract_text(b"some content")
        assert result == ""

    @patch("app.core.pdf_parser.fitz")
    def test_extract_text_with_valid_pdf(self, mock_fitz):
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "2022年3月在广东省采集1245份血清样本"
        mock_doc.__len__.return_value = 1
        mock_doc.__getitem__.return_value = mock_page
        mock_fitz.open.return_value = mock_doc

        result = extract_text(b"valid pdf bytes")

        assert "广东省" in result
        assert "1245" in result
        mock_doc.close.assert_called_once()

    @patch("app.core.pdf_parser.fitz")
    def test_extract_text_with_scanned_pdf(self, mock_fitz):
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = ""
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"png image data"
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__len__.return_value = 1
        mock_doc.__getitem__.return_value = mock_page
        mock_fitz.open.return_value = mock_doc

        with patch("app.core.pdf_parser.ocr_pdf_pages") as mock_ocr:
            mock_ocr.return_value = "OCR extracted text"
            result = extract_text(b"scanned pdf bytes")

            mock_ocr.assert_called_once()
            assert result == "OCR extracted text"

    @patch("app.core.pdf_parser.fitz")
    def test_extract_text_with_partial_text(self, mock_fitz):
        mock_doc = MagicMock()
        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "第一页文本"
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = ""
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"png image data"
        mock_page2.get_pixmap.return_value = mock_pix
        mock_doc.__len__.return_value = 2
        mock_doc.__getitem__.side_effect = [mock_page1, mock_page2]
        mock_fitz.open.return_value = mock_doc

        with patch("app.core.pdf_parser.ocr_pdf_pages") as mock_ocr:
            mock_ocr.return_value = "第二页OCR文本"
            result = extract_text(b"mixed pdf bytes")

            assert "第二页OCR文本" in result
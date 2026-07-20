import logging
import io
from typing import Optional

try:
    import fitz  # PyMuPDF

    # 验证是否为真正的 PyMuPDF（而非冲突的 fitz 包）
    if not hasattr(fitz, "open"):
        raise ImportError("fitz module is not PyMuPDF")
    HAS_PYMUPDF = True
except ImportError:
    fitz = None
    HAS_PYMUPDF = False

from app.core.ocr_service import ocr_pdf_pages

logger = logging.getLogger("uvicorn")


def extract_text(file_bytes: bytes) -> str:
    """从 PDF 文件字节中提取文本"""
    if not HAS_PYMUPDF:
        logger.warning("PyMuPDF 不可用，PDF 解析被跳过")
        return ""

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text_parts = []
        page_images_for_ocr = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            # 先尝试直接提取文本
            page_text = page.get_text("text")
            if page_text.strip():
                full_text_parts.append(page_text.strip())
            else:
                # 该页无文本，记录用于 OCR
                pix = page.get_pixmap(dpi=200)
                page_images_for_ocr.append(pix.tobytes("png"))

        doc.close()

        combined_text = "\n\n".join(full_text_parts)

        # 如果提取的文本过短（<100 字符），尝试 OCR
        if len(combined_text.strip()) < 100 and page_images_for_ocr:
            logger.info("PyMuPDF 提取文本过短，尝试 OCR 兜底...")
            ocr_text = ocr_pdf_pages(page_images_for_ocr)
            if ocr_text:
                return ocr_text

        return combined_text if combined_text.strip() else ""

    except Exception as e:
        logger.error(f"PDF 解析失败: {e}")
        return ""

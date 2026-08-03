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
from app.config import settings

logger = logging.getLogger("uvicorn")


def extract_text(file_bytes: bytes) -> str:
    """从 PDF 文件字节中提取文本"""
    if not HAS_PYMUPDF:
        logger.warning("PyMuPDF 不可用，PDF 解析被跳过")
        return ""

    # 单页有效文本少于该字符数 → 判定为扫描页/文字层损坏页，交给 OCR
    PAGE_TEXT_MIN = 100

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text_parts = []
        page_images_for_ocr = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            # 先尝试直接提取文本
            page_text = page.get_text("text").strip()
            if len(page_text) >= PAGE_TEXT_MIN:
                full_text_parts.append(page_text)
            else:
                # 无文本或文本过短（扫描件/文字层损坏），整页交给 OCR
                # 同时保留少量文本作为 OCR 失败时的兜底
                if page_text:
                    full_text_parts.append(page_text)
                pix = page.get_pixmap(dpi=200)
                page_images_for_ocr.append(pix.tobytes("png"))

        doc.close()

        combined_text = "\n\n".join(full_text_parts)

        # 存在扫描页/文字层损坏页时，执行 OCR 兜底并合并结果
        if page_images_for_ocr:
            logger.info(
                f"检测到 {len(page_images_for_ocr)} 个页面文本过短，尝试 OCR 兜底..."
            )
            ocr_text = ocr_pdf_pages(
                page_images_for_ocr,
                fallback_to_baidu=settings.OCR_FALLBACK_TO_BAIDU,
                baidu_api_key=settings.BAIDU_OCR_API_KEY,
                baidu_secret_key=settings.BAIDU_OCR_SECRET_KEY,
            )
            if ocr_text:
                parts = full_text_parts + [ocr_text] if full_text_parts else [ocr_text]
                return "\n\n".join(parts)

        return combined_text if combined_text.strip() else ""

    except Exception as e:
        logger.error(f"PDF 解析失败: {e}")
        return ""

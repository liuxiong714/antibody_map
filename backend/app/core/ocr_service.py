import logging
from typing import Optional

try:
    import pytesseract
    from PIL import Image
    import io

    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

logger = logging.getLogger("uvicorn")


def ocr_image(image_bytes: bytes, lang: str = "chi_sim+eng") -> Optional[str]:
    """对单张图片执行 OCR"""
    if not HAS_TESSERACT:
        logger.warning("pytesseract 未安装，OCR 不可用")
        return None

    try:
        image = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(image, lang=lang)
        return text.strip()
    except Exception as e:
        logger.error(f"OCR 失败: {e}")
        return None


def ocr_pdf_pages(
    page_images: list[bytes], lang: str = "chi_sim+eng"
) -> Optional[str]:
    """对 PDF 各页图片执行 OCR，拼接结果"""
    if not HAS_TESSERACT:
        logger.warning("pytesseract 未安装，OCR 不可用")
        return None

    results = []
    for i, page_bytes in enumerate(page_images):
        page_text = ocr_image(page_bytes, lang=lang)
        if page_text:
            results.append(page_text)
        logger.debug(f"OCR page {i + 1}/{len(page_images)} done")

    if results:
        return "\n\n".join(results)
    return None

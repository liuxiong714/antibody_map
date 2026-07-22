import logging
import io
from typing import Optional, List, Dict, Any

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter
    HAS_TESSERACT = True
    PIL_IMAGE_TYPE = Image.Image
except ImportError:
    HAS_TESSERACT = False
    PIL_IMAGE_TYPE = Any

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logger = logging.getLogger("uvicorn")

LANGUAGE_MAP = {
    "zh": "chi_sim",
    "en": "eng",
    "ja": "jpn",
    "ko": "kor",
    "fr": "fra",
    "de": "deu",
    "es": "spa",
}


def preprocess_image(image_bytes: bytes) -> PIL_IMAGE_TYPE:
    """
    图片预处理：提高 OCR 识别率
    步骤：灰度化 → 对比度增强 → 二值化 → 降噪
    """
    image = Image.open(io.BytesIO(image_bytes))

    if image.mode != 'L':
        image = image.convert('L')

    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(1.5)

    threshold = 128
    image = image.point(lambda x: 255 if x > threshold else 0)

    image = image.filter(ImageFilter.MedianFilter(size=3))

    return image


def ocr_tesseract(image_bytes: bytes, lang: str = "chi_sim+eng") -> Optional[str]:
    """使用 Tesseract 执行 OCR"""
    if not HAS_TESSERACT:
        logger.warning("pytesseract 未安装，跳过 Tesseract OCR")
        return None

    try:
        image = preprocess_image(image_bytes)
        text = pytesseract.image_to_string(image, lang=lang)
        result = text.strip()
        if result:
            logger.debug(f"Tesseract OCR 成功，提取 {len(result)} 字符")
        return result
    except Exception as e:
        logger.error(f"Tesseract OCR 失败: {e}")
        return None


def ocr_baidu(image_bytes: bytes, api_key: str, secret_key: str, lang: str = "CHN_ENG") -> Optional[str]:
    """使用百度 OCR API（备选方案）"""
    if not HAS_REQUESTS:
        logger.warning("requests 未安装，跳过百度 OCR")
        return None

    try:
        import base64
        import json

        access_token = _get_baidu_access_token(api_key, secret_key)
        if not access_token:
            logger.error("获取百度 OCR access_token 失败")
            return None

        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        url = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"
        params = {
            "image": base64_image,
            "language_type": lang,
            "access_token": access_token,
        }

        resp = requests.post(url, data=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("words_result"):
            text = "\n".join([item["words"] for item in data["words_result"]])
            logger.debug(f"百度 OCR 成功，提取 {len(text)} 字符")
            return text
        return None

    except Exception as e:
        logger.error(f"百度 OCR 失败: {e}")
        return None


def _get_baidu_access_token(api_key: str, secret_key: str) -> Optional[str]:
    """获取百度 API access_token"""
    try:
        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret_key,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("access_token")
    except Exception as e:
        logger.error(f"获取百度 access_token 失败: {e}")
        return None


def ocr_image(image_bytes: bytes, lang: str = "zh", fallback_to_baidu: bool = False,
              baidu_api_key: str = "", baidu_secret_key: str = "") -> Optional[str]:
    """
    对单张图片执行 OCR（主入口）
    
    Args:
        image_bytes: 图片字节数据
        lang: 语言代码 (zh/en/ja/ko/fr/de/es)
        fallback_to_baidu: 是否在 Tesseract 失败时使用百度 OCR
        baidu_api_key: 百度 API Key
        baidu_secret_key: 百度 Secret Key
    
    Returns:
        识别到的文本，失败返回 None
    """
    lang_code = LANGUAGE_MAP.get(lang, "chi_sim")
    if lang == "zh":
        lang_code = "chi_sim+eng"
    else:
        lang_code = f"{lang_code}+eng"

    result = ocr_tesseract(image_bytes, lang=lang_code)

    if result:
        return result

    if fallback_to_baidu and baidu_api_key and baidu_secret_key:
        logger.info("Tesseract 未提取到文本，尝试百度 OCR...")
        baidu_lang = "CHN_ENG" if lang == "zh" else "ENG"
        result = ocr_baidu(image_bytes, baidu_api_key, baidu_secret_key, lang=baidu_lang)
        return result

    return None


def ocr_pdf_pages(page_images: list[bytes], lang: str = "zh",
                  fallback_to_baidu: bool = False,
                  baidu_api_key: str = "", baidu_secret_key: str = "") -> Optional[str]:
    """
    对 PDF 各页图片执行 OCR，拼接结果
    
    Args:
        page_images: 每页图片的字节数据列表
        lang: 语言代码
        fallback_to_baidu: 是否使用百度 OCR 兜底
        baidu_api_key: 百度 API Key
        baidu_secret_key: 百度 Secret Key
    
    Returns:
        拼接后的文本，失败返回 None
    """
    results = []
    for i, page_bytes in enumerate(page_images):
        page_text = ocr_image(
            page_bytes,
            lang=lang,
            fallback_to_baidu=fallback_to_baidu,
            baidu_api_key=baidu_api_key,
            baidu_secret_key=baidu_secret_key,
        )
        if page_text:
            results.append(page_text)
            logger.debug(f"OCR page {i + 1}/{len(page_images)}: {len(page_text)} 字符")
        else:
            logger.debug(f"OCR page {i + 1}/{len(page_images)}: 未识别到文本")

    if results:
        return "\n\n--- PAGE SEPARATOR ---\n\n".join(results)
    return None


def get_ocr_status() -> Dict[str, bool]:
    """获取 OCR 服务状态"""
    return {
        "tesseract_available": HAS_TESSERACT,
        "requests_available": HAS_REQUESTS,
    }
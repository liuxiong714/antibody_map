import asyncio
import logging
import io
import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter
    HAS_PYTESSERACT = True
    PIL_IMAGE_TYPE = Image.Image
except ImportError:
    pytesseract = None
    HAS_PYTESSERACT = False
    PIL_IMAGE_TYPE = Any

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from app.config import settings

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


def _resolve_tesseract_cmd() -> Optional[str]:
    """解析 tesseract 可执行文件路径：配置 > PATH > Windows 常见安装位置"""
    cmd = (settings.TESSERACT_CMD or "").strip()
    if cmd:
        if Path(cmd).exists() or shutil.which(cmd):
            return cmd
        logger.warning(f"配置的 TESSERACT_CMD 不可用，尝试自动探测: {cmd}")

    found = shutil.which("tesseract")
    if found:
        return found

    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _resolve_tessdata_dir() -> Optional[str]:
    """解析 tessdata 目录：配置 > 可执行文件同目录下的 tessdata"""
    data_dir = (settings.TESSERACT_DATA_DIR or "").strip()
    if data_dir:
        if Path(data_dir).is_dir():
            return data_dir
        logger.warning(f"配置的 TESSERACT_DATA_DIR 不存在: {data_dir}")

    if TESSERACT_CMD_PATH:
        candidate = Path(TESSERACT_CMD_PATH).parent / "tessdata"
        if candidate.is_dir():
            return str(candidate)
    return None


def _tessdata_config() -> str:
    """生成 pytesseract 需要的 tessdata 配置参数"""
    tessdata_dir = _resolve_tessdata_dir()
    if tessdata_dir:
        # 注意：pytesseract 在 Windows 上使用 shlex.split(config, posix=False)，
        # 双引号会被原样保留进参数导致路径无效，因此这里不加引号。
        # 含空格路径由 TESSDATA_PREFIX 环境变量兜底（见模块底部）。
        return f"--tessdata-dir {tessdata_dir}"
    return ""


TESSERACT_CMD_PATH = _resolve_tesseract_cmd()
if TESSERACT_CMD_PATH and HAS_PYTESSERACT:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD_PATH

TESSDATA_DIR = _resolve_tessdata_dir()
if TESSDATA_DIR:
    # 环境变量被 tesseract 子进程继承，可绕过命令行引号问题（兼容含空格的路径）
    os.environ.setdefault("TESSDATA_PREFIX", TESSDATA_DIR)

# 仅当 pytesseract 可导入且 tesseract 可执行文件存在时才视为可用
HAS_TESSERACT = HAS_PYTESSERACT and TESSERACT_CMD_PATH is not None


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
        logger.warning("Tesseract OCR 不可用（pytesseract 或 tesseract 可执行文件缺失），跳过 Tesseract OCR")
        return None

    try:
        image = preprocess_image(image_bytes)
        text = pytesseract.image_to_string(image, lang=lang, config=_tessdata_config())
        result = text.strip()
        if result:
            logger.debug(f"Tesseract OCR 成功，提取 {len(result)} 字符")
        return result
    except Exception as e:
        logger.error(f"Tesseract OCR 失败: {e}")
        return None


async def ocr_tesseract_with_timeout(
    image_bytes: bytes,
    lang: str = "chi_sim+eng",
    timeout: float = 60,
) -> Optional[str]:
    """带超时的 Tesseract OCR 包装：超时返回 None，不抛异常中断整篇。

    ocr_tesseract 是阻塞同步调用，用 asyncio.to_thread 放到独立线程中执行，
    使 asyncio.wait_for 的超时真正生效（否则阻塞调用无法被取消/超时）。
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(ocr_tesseract, image_bytes, lang),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Tesseract OCR 超时（>{timeout}s），该页返回 None")
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


def get_ocr_status() -> Dict[str, Any]:
    """获取 OCR 服务状态"""
    return {
        "tesseract_available": HAS_TESSERACT,
        "tesseract_cmd": TESSERACT_CMD_PATH or "",
        "tessdata_dir": _resolve_tessdata_dir() or "",
        "requests_available": HAS_REQUESTS,
    }
"""pdf-inspector PDF 解析增强（firecrawl/pdf-inspector：PDF → Markdown）。

纯 Rust 实现的 PDF 分类与文本提取库，支持智能分类（text_based/scanned/mixed）、
位置感知提取、双模式表格检测（TEDS 0.814）、多栏阅读顺序、CID 中文字体解码。

接入策略：
1. 直接调用 pdf-inspector 解析 PDF 文件字节
2. 若 pdf-inspector 因 PDF 文件尾部损坏（invalid file trailer）失败，
   使用 PyMuPDF 重新保存修复（garbage=4, deflate=True, clean=True），
   再调用 pdf-inspector 解析修复版
3. 修复后在一个临时目录中操作，不污染原始文件

注意：本模块不在 import 时加载 pdf-inspector（惰性加载），便于在绑定缺失时
容器仍能正常启动并回退到现有解析器。
"""
import importlib
import logging
import os
import tempfile
import threading
from typing import Optional

logger = logging.getLogger("uvicorn")

_pdf_inspector_mod = None
_available: Optional[bool] = None


def _load_module():
    """惰性加载 pdf-inspector 绑定并缓存可用状态。"""
    global _pdf_inspector_mod, _available
    if _available is not None:
        return _pdf_inspector_mod
    try:
        mod = importlib.import_module("pdf_inspector")
        if not hasattr(mod, "process_pdf") or not hasattr(mod, "process_pdf_bytes"):
            raise ImportError("pdf-inspector 缺少 process_pdf/process_pdf_bytes 接口")
        _pdf_inspector_mod = mod
        _available = True
        logger.info("[pdf-inspector] Python 绑定已加载（firecrawl/pdf-inspector）")
    except Exception as e:
        _pdf_inspector_mod = None
        _available = False
        logger.info(f"[pdf-inspector] Python 绑定不可用，将跳过 pdf-inspector 解析: {e}")
    return _pdf_inspector_mod


def is_available() -> bool:
    """探测 pdf-inspector 绑定可导入且可用。"""
    return _load_module() is not None


def _repair_with_pymupdf(file_bytes: bytes) -> Optional[bytes]:
    """使用 PyMuPDF 重新保存 PDF，修复损坏的尾部结构。

    输入损坏的 PDF 字节，用 PyMuPDF 打开并重新保存（garbage=4, deflate=True,
    clean=True），生成一个全新的规范 PDF 字节。返回修复后的字节，失败返回 None。
    """
    try:
        import fitz
        if not hasattr(fitz, "open"):
            raise ImportError("fitz module is not PyMuPDF")
    except ImportError:
        logger.warning("[pdf-inspector] PyMuPDF 不可用，无法修复 PDF")
        return None

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        doc.save(tmp_path, garbage=4, deflate=True, clean=True)
        doc.close()
        with open(tmp_path, "rb") as f:
            repaired = f.read()
        os.unlink(tmp_path)
        logger.info(f"[pdf-inspector] PyMuPDF 修复成功: 原大小={len(file_bytes)}, 修复后={len(repaired)}")
        return repaired
    except Exception as e:
        logger.warning(f"[pdf-inspector] PyMuPDF 修复失败: {e}")
        return None


def to_markdown_bytes(file_bytes: bytes, timeout: Optional[int] = None) -> str:
    """使用 pdf-inspector 将 PDF 字节转为 Markdown。

    解析流程：
    1. 直接调用 pdf-inspector 的 process_pdf_bytes()
    2. 若失败且错误为 invalid file trailer，用 PyMuPDF 修复后重试
    3. 任何异常返回空字符串

    返回 Markdown 字符串，失败返回空字符串。
    """
    mod = _load_module()
    if mod is None:
        return ""

    if timeout is None:
        timeout = 30

    result: dict = {}

    def _run():
        try:
            # 第一步：直接尝试
            res = mod.process_pdf_bytes(file_bytes)
            result["md"] = res.markdown or ""
            result["pdf_type"] = res.pdf_type
        except Exception as e:
            result["error"] = e
            result["error_msg"] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        logger.warning(f"[pdf-inspector] 解析超时（>{timeout}s），回退")
        return ""

    if "error" not in result:
        # 首次成功
        md = result.get("md", "")
        if md:
            logger.info(f"[pdf-inspector] 直接解析成功: 类型={result.get('pdf_type')}, 输出={len(md)} 字符")
        return md

    # 首次失败，检查是否为 invalid file trailer
    error_msg = result.get("error_msg", "")
    if "invalid file trailer" not in error_msg:
        logger.warning(f"[pdf-inspector] 解析失败（{type(result['error']).__name__}: {error_msg[:100]}），跳过修复")
        return ""

    logger.info("[pdf-inspector] 检测到 invalid file trailer，尝试 PyMuPDF 修复...")
    repaired = _repair_with_pymupdf(file_bytes)
    if repaired is None:
        return ""

    # 修复后重试
    result2: dict = {}

    def _run2():
        try:
            res = mod.process_pdf_bytes(repaired)
            result2["md"] = res.markdown or ""
            result2["pdf_type"] = res.pdf_type
        except Exception as e:
            result2["error"] = e

    t2 = threading.Thread(target=_run2, daemon=True)
    t2.start()
    t2.join(timeout=timeout)

    if t2.is_alive():
        logger.warning(f"[pdf-inspector] 修复后解析超时（>{timeout}s），回退")
        return ""

    if "error" in result2:
        logger.warning(f"[pdf-inspector] 修复后仍解析失败（{type(result2['error']).__name__}: {result2['error']}），回退")
        return ""

    md = result2.get("md", "")
    if md:
        logger.info(f"[pdf-inspector] 修复后解析成功: 类型={result2.get('pdf_type')}, 输出={len(md)} 字符")
    return md
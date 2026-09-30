"""AnyDoc 文档解析增强（firecrawl/anydoc：任意文档 → GitHub-Flavored Markdown）。

纯 Rust 实现的文档转 Markdown 库，重点提升 表格 → Markdown 质量（合并单元格、
嵌套列表等），直接提升 LLM 数据提取准确率。作为策略解析器之前的增强路径接入
document_parser 与 pdf_table_parser。

接入原则（渐进式、零回归）：
- 由 settings.ENABLE_ANYDOC 控制总开关，默认关闭；
- is_available() 探测绑定可导入可用，不可用则调用方直接跳过；
- to_markdown_bytes() 任何异常/超时返回空字符串（触发调用方降级到现有解析链）。

注意：本模块不在 import 时加载 anydoc（惰性加载），便于在绑定缺失/损坏时
容器仍能正常启动并回退到现有解析器。
"""
import importlib
import logging
import re
import threading

logger = logging.getLogger("uvicorn")

# AnyDoc 支持格式（扩展名带点小写）
ANYDOC_EXTS = {
    ".pdf",
    ".doc", ".docx", ".docm",
    ".ppt", ".pps", ".pot", ".pptx", ".pptm", ".ppsx", ".ppsm",
    ".xls", ".xlsx", ".xlsm", ".xlsb",
    ".odt", ".ods", ".odp",
    ".rtf", ".epub", ".csv",
}

# 带点扩展名 → anydoc 内部格式名（不含点，小写）
_EXT_TO_FORMAT = {
    ".pdf": "pdf",
    ".doc": "docx", ".docx": "docx", ".docm": "docx",
    ".ppt": "pptx", ".pps": "pptx", ".pot": "pptx",
    ".pptx": "pptx", ".pptm": "pptx", ".ppsx": "pptx", ".ppsm": "pptx",
    ".xls": "xlsx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".xlsb": "xlsx",
    ".odt": "odt", ".ods": "ods", ".odp": "odp",
    ".rtf": "rtf", ".epub": "epub", ".csv": "csv",
}

_anydoc_mod = None
_available: bool | None = None


def _load_module():
    """惰性加载 anydoc 绑定并缓存可用状态。失败返回 None 且不抛异常。"""
    global _anydoc_mod, _available
    if _available is not None:
        return _anydoc_mod
    try:
        mod = importlib.import_module("anydoc")
        if not hasattr(mod, "to_markdown_bytes"):
            raise ImportError("anydoc 缺少 to_markdown_bytes 接口")
        _anydoc_mod = mod
        _available = True
        logger.info("[AnyDoc] Python 绑定已加载（firecrawl/anydoc）")
    except Exception as e:
        _anydoc_mod = None
        _available = False
        logger.info(f"[AnyDoc] Python 绑定不可用，将跳过 AnyDoc 解析: {e}")
    return _anydoc_mod


def is_available() -> bool:
    """探测 anydoc 绑定可导入且可用；不可用返回 False，调用方跳过。"""
    return _load_module() is not None


def supports(ext: str) -> bool:
    """判断某扩展名是否在 AnyDoc 支持集合内。"""
    ext = (ext or "").lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return ext in ANYDOC_EXTS


# GFM 表格检测：表头行 + 分隔行（| --- |）
_TABLE_RE = re.compile(
    r"^\s*\|.*\|\s*\n\s*\|[\s:|-]+\|",
    re.MULTILINE,
)


def contains_table(md: str) -> bool:
    """粗略判断 AnyDoc 输出的 Markdown 是否包含 GFM 表格。"""
    return bool(md and _TABLE_RE.search(md))


def to_markdown_bytes(file_bytes: bytes, ext: str, timeout: int | None = None) -> str:
    """调用 anydoc 将文件字节转为 GFM Markdown。

    任何异常/超时返回空字符串并记录日志（触发调用方降级）。
    timeout 缺省时取 settings.ANYDOC_TIMEOUT。
    """
    from app.config import settings

    mod = _load_module()
    if mod is None:
        return ""
    if timeout is None:
        timeout = int(getattr(settings, "ANYDOC_TIMEOUT", 60))

    ext = (ext or "").lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    fmt: str | None = _EXT_TO_FORMAT.get(ext)

    result: dict = {}

    def _run():
        try:
            if fmt:
                # 显式格式名：CSV 等无签名字节格式依赖扩展名/格式名识别
                result["md"] = mod.to_markdown_bytes(file_bytes, fmt)
            else:
                # 其余格式按字节内容自动识别（PDF 头/OLE 流名/ZIP mimetype）
                result["md"] = mod.to_markdown_bytes(file_bytes)
        except Exception as e:
            result["error"] = e

    # 独立线程运行 + join 超时：AnyDoc 释放 GIL，且避免单文档卡死阻塞 worker
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        logger.warning(f"[AnyDoc] 解析超时（>{timeout}s）: 格式={ext}，回退现有解析链")
        return ""

    if "error" in result:
        err = result["error"]
        logger.warning(
            f"[AnyDoc] 解析失败（{type(err).__name__}: {err}）：格式={ext}，回退现有解析链"
        )
        return ""

    return result.get("md") or ""
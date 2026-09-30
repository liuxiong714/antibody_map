"""文档解析引擎可用性探测。

集中汇总 8 个解析引擎的「配置开关 + 运行时依赖」状态，供 /system/info 等
诊断端点一次性返回，避免排查解析问题时逐个模块翻代码。
所有重引擎（MinerU/PyMuPDF 等）均在函数内惰性导入，避免启动时被迫加载。
"""
from typing import Any


def get_parser_status() -> list[dict[str, Any]]:
    """返回所有解析引擎的可用性/开关状态（只读，无副作用）。

    每个元素：{name, enabled, available, note}。
    - enabled：配置开关或是否为默认始终启用的引擎
    - available：运行时依赖（绑定/可执行文件/模型）是否就绪
    - note：补充说明
    """
    from app.config import settings

    statuses: list[dict[str, Any]] = []

    # AnyDoc：配置开关 ENABLE_ANYDOC，默认关
    try:
        from app.core.processors.anydoc_parser import is_available as anydoc_avail
        anydoc_ok = anydoc_avail()
    except Exception:
        anydoc_ok = False
    statuses.append({
        "name": "AnyDoc",
        "enabled": bool(getattr(settings, "ENABLE_ANYDOC", False)),
        "available": anydoc_ok,
        "note": "任意文档→GFM Markdown，默认关闭，失败自动回退现有解析链",
    })

    # pdf-inspector：配置开关 ENABLE_PDF_INSPECTOR，默认开
    try:
        from app.core.processors.pdf_inspector_parser import is_available as pdfinsp_avail
        pdfinsp_ok = pdfinsp_avail()
    except Exception:
        pdfinsp_ok = False
    statuses.append({
        "name": "pdf-inspector",
        "enabled": bool(getattr(settings, "ENABLE_PDF_INSPECTOR", False)),
        "available": pdfinsp_ok,
        "note": "PDF→Markdown，Rust 实现，默认开启",
    })

    # MinerU：配置开关 ENABLE_MINERU_PDF_PARSER，默认关（需 PyTorch+模型）
    try:
        from app.core.pdf_parser import HAS_MINERU
    except Exception:
        HAS_MINERU = False
    statuses.append({
        "name": "MinerU",
        "enabled": bool(getattr(settings, "ENABLE_MINERU_PDF_PARSER", False)),
        "available": bool(HAS_MINERU),
        "note": "增强PDF解析，依赖 PyTorch+模型，默认关闭",
    })

    # PyMuPDF：始终启用
    try:
        from app.core.pdf_parser import HAS_PYMUPDF
    except Exception:
        HAS_PYMUPDF = False
    statuses.append({
        "name": "PyMuPDF",
        "enabled": True,
        "available": bool(HAS_PYMUPDF),
        "note": "PDF 文本提取与扫描页渲染兜底，始终启用",
    })

    # pdfplumber：始终启用
    try:
        from app.core.pdf_table_parser import HAS_PDFPLUMBER
    except Exception:
        HAS_PDFPLUMBER = False
    statuses.append({
        "name": "pdfplumber",
        "enabled": True,
        "available": bool(HAS_PDFPLUMBER),
        "note": "PDF 表格结构化提取兜底，始终启用",
    })

    # Tesseract：扫描页自动，无独立开关
    try:
        from app.core.ocr_service import HAS_TESSERACT
    except Exception:
        HAS_TESSERACT = False
    statuses.append({
        "name": "Tesseract (OCR)",
        "enabled": True,
        "available": bool(HAS_TESSERACT),
        "note": "扫描页/乱码页 OCR 兜底，自动触发，依赖系统 tesseract 可执行文件",
    })

    # 视觉提取器：扫描页自动，无独立开关
    try:
        from app.core.vl_extractor import extract_with_vision  # noqa: F401
        vision_ok = True
    except Exception:
        vision_ok = False
    statuses.append({
        "name": "视觉提取器",
        "enabled": True,
        "available": vision_ok,
        "note": "扫描页视觉理解增强，自动触发，依赖已配置 LLM 模型",
    })

    # 百度 OCR：不再提供配置开关，需显式传参调用 ocr_image
    try:
        from app.core.ocr_service import HAS_REQUESTS
    except Exception:
        HAS_REQUESTS = False
    statuses.append({
        "name": "百度 OCR",
        "enabled": False,
        "available": bool(HAS_REQUESTS),
        "note": "已移除配置开关，需在调用方显式传入密钥才能启用",
    })

    return statuses
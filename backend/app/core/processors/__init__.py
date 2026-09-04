"""文档解析器策略模式包。

每个格式独立一个 Processor 类，统一继承 BaseParser。
新增格式只需在 processors 包下新建文件并注册到 _PARSER_REGISTRY。
"""
from .base import BaseParser, get_parser, list_supported_exts
from .docx_parser import DocxParser
from .epub_parser import EpubParser
from .html_parser import HtmlParser
from .pptx_parser import PptxParser
from .txt_parser import TxtParser
from .xlsx_parser import XlsxParser

__all__ = [
    "BaseParser",
    "DocxParser",
    "EpubParser",
    "HtmlParser",
    "PptxParser",
    "TxtParser",
    "XlsxParser",
    "get_parser",
    "list_supported_exts",
]
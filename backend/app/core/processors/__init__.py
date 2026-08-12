"""文档解析器策略模式包。

每个格式独立一个 Processor 类，统一继承 BaseParser。
新增格式只需在 processors 包下新建文件并注册到 _PARSER_REGISTRY。
"""
from .base import BaseParser, get_parser, list_supported_exts
from .epub_parser import EpubParser
from .docx_parser import DocxParser
from .pptx_parser import PptxParser
from .xlsx_parser import XlsxParser
from .txt_parser import TxtParser
from .html_parser import HtmlParser

__all__ = [
    "BaseParser", "get_parser", "list_supported_exts",
    "EpubParser", "DocxParser", "PptxParser",
    "XlsxParser", "TxtParser", "HtmlParser",
]
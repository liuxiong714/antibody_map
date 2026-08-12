"""TXT 解析器：utf-8 → gbk → gb18030 解码。"""
from .base import BaseParser, register_parser


@register_parser(".txt")
class TxtParser(BaseParser):
    supported_ext = ".txt"

    def extract(self, file_bytes: bytes) -> str:
        for enc in ("utf-8", "gbk", "gb18030"):
            try:
                return file_bytes.decode(enc)
            except UnicodeDecodeError:
                continue
        return file_bytes.decode("utf-8", errors="ignore")
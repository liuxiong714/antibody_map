"""EPUB 解析器：ebooklib 读 XHTML → bs4 取文本。"""
import io
import logging

from .base import BaseParser, register_parser


@register_parser(".epub")
class EpubParser(BaseParser):
    supported_ext = ".epub"

    def extract(self, file_bytes: bytes) -> str:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        # 抑制 ebooklib 非致命警告
        logging.getLogger("ebooklib").setLevel(logging.ERROR)

        book = epub.read_epub(io.BytesIO(file_bytes))
        parts = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_body_content() or b"", "html.parser")
            text = soup.get_text(separator="\n")
            if text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts)
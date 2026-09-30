"""HTML 解析器：bs4 去标签取文本。"""
from .base import BaseParser, register_parser


@register_parser(".html")
@register_parser(".htm")
class HtmlParser(BaseParser):
    supported_ext = ".html"

    def extract(self, file_bytes: bytes) -> str:
        from bs4 import BeautifulSoup

        html = None
        for enc in ("utf-8", "gbk"):
            try:
                html = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if html is None:
            html = file_bytes.decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n")
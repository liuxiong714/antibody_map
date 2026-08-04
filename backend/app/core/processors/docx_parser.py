"""DOCX 解析器：python-docx 取段落 + 表格文本。"""
import io

from .base import BaseParser, register_parser


@register_parser(".docx")
class DocxParser(BaseParser):
    supported_ext = ".docx"

    def extract(self, file_bytes: bytes) -> str:
        import docx

        document = docx.Document(io.BytesIO(file_bytes))
        parts = [p.text for p in document.paragraphs if p.text and p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text and cell.text.strip():
                        parts.append(cell.text.strip())
        return "\n".join(parts)
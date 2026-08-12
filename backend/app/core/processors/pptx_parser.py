"""PPTX 解析器：python-pptx 读幻灯片 → 形状文本 + 表格文本。"""
import io

from .base import BaseParser, register_parser


@register_parser(".pptx")
class PptxParser(BaseParser):
    supported_ext = ".pptx"

    def extract(self, file_bytes: bytes) -> str:
        from pptx import Presentation

        prs = Presentation(io.BytesIO(file_bytes))
        parts = []
        for slide_num, slide in enumerate(prs.slides, 1):
            slide_texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        t = para.text.strip()
                        if t:
                            slide_texts.append(t)
                if shape.has_table:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            t = cell.text.strip()
                            if t:
                                slide_texts.append(t)
            if slide_texts:
                parts.append(f"【第{slide_num}页】" + " ".join(slide_texts))
        return "\n\n".join(parts)
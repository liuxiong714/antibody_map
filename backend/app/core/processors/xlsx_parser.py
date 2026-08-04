"""XLSX 解析器：openpyxl 读每个 sheet 的每个单元格。"""
import io

from .base import BaseParser, register_parser


@register_parser(".xlsx")
class XlsxParser(BaseParser):
    supported_ext = ".xlsx"

    def extract(self, file_bytes: bytes) -> str:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        parts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sheet_parts = [f"【工作表: {sheet_name}】"]
            row_texts = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    row_texts.append(" | ".join(cells))
            if row_texts:
                sheet_parts.extend(row_texts)
            parts.append("\n".join(sheet_parts))
        wb.close()
        return "\n\n".join(parts)
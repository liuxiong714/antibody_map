"""PDF 表格结构化提取（P0-1，参考 NanoNets/docstrange 的表格→Markdown 思路）。

用 pdfplumber 提取 PDF 中的表格，转换为干净的 Markdown 表格文本，
供 LLM 在结构化提取时使用，避免表格被拍扁成乱序文本导致行列错位。

核心函数：
- extract_tables_markdown(file_bytes) -> str：返回所有表格的 Markdown 字符串
- has_tables(file_bytes) -> bool：快速判断 PDF 是否包含表格

兼容性：
- pdfplumber 不可用时安全降级返回空串，不影响原有纯文本提取流程
- 表格提取失败不影响主流程，仅记录日志
"""
import logging
import io
from typing import Optional

from app.config import settings
from app.core.processors import anydoc_parser
from app.core.processors import pdf_inspector_parser

logger = logging.getLogger("uvicorn")

try:
    import pdfplumber  # type: ignore
    HAS_PDFPLUMBER = True
except ImportError:
    pdfplumber = None
    HAS_PDFPLUMBER = False
    logger.info("pdfplumber 未安装，PDF 表格结构化提取将被跳过（不影响纯文本提取）")


def _cell_to_str(cell) -> str:
    """把单元格转成干净字符串：None→空串，去除换行和多余空白。"""
    if cell is None:
        return ""
    s = str(cell).replace("\n", " ").replace("\r", " ")
    # 折叠多空格
    while "  " in s:
        s = s.replace("  ", " ")
    return s.strip()


def _table_to_markdown(table: list[list]) -> str:
    """把 pdfplumber 的二维列表表格转成 Markdown 表格字符串。

    规则：
    - 第一行作为表头
    - 空表返回空串
    - 单元格内的 | 转义为 \\|
    """
    if not table or not table[0]:
        return ""

    rows = [[_cell_to_str(c) for c in row] for row in table]
    # 过滤掉全空行
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""

    # 列数对齐（补齐短行）
    max_cols = max(len(r) for r in rows)
    rows = [r + [""] * (max_cols - len(r)) for r in rows]

    # 转义管道符
    def esc(s: str) -> str:
        return s.replace("|", "\\|")

    header = "| " + " | ".join(esc(c) for c in rows[0]) + " |"
    separator = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body_lines = [
        "| " + " | ".join(esc(c) for c in row) + " |"
        for row in rows[1:]
    ]
    return "\n".join([header, separator] + body_lines)


def extract_tables_markdown(file_bytes: bytes, max_pages: int = 50) -> str:
    """提取 PDF 中所有表格，返回拼接后的 Markdown 字符串。

    参数：
        file_bytes: PDF 文件字节
        max_pages: 最多扫描的页数（防止超大 PDF 拖慢）

    返回：
        Markdown 表格文本，无表格或失败时返回空串。
        每个表格前会有一个 "### 表格 N (页码 M)" 的小标题。
    """
    # AnyDoc 增强路径：其 GFM Markdown 天然含高质量表格，直接作为 tables_md 注入。
    # 成功则返回；失败/超时/不可用返回空串并回退 pdfplumber 提取。
    if (
        getattr(settings, "ENABLE_ANYDOC", False)
        and anydoc_parser.is_available()
        and anydoc_parser.supports(".pdf")
    ):
        md = anydoc_parser.to_markdown_bytes(file_bytes, ".pdf")
        if md and anydoc_parser.contains_table(md):
            logger.info(f"[表格提取] 解析路径=AnyDoc，Markdown 含表格: {len(md)} 字符")
            return md
        logger.info("[表格提取] 回退=pdfplumber（AnyDoc 无表格或失败）")

    # pdf-inspector 增强路径：仅对 PDF 格式，优先尝试 pdf-inspector。
    # 由 pdf-inspector 提取 Markdown 后检测是否含 GFM 表格，有则直接返回。
    if (
        getattr(settings, "ENABLE_PDF_INSPECTOR", False)
        and pdf_inspector_parser.is_available()
    ):
        md = pdf_inspector_parser.to_markdown_bytes(file_bytes)
        if md and anydoc_parser.contains_table(md):
            logger.info(f"[表格提取] 解析路径=pdf-inspector，Markdown 含表格: {len(md)} 字符")
            return md
        logger.info("[表格提取] 回退=pdfplumber（pdf-inspector 无表格或失败）")

    if not HAS_PDFPLUMBER:
        logger.debug("[表格提取] pdfplumber 不可用，跳过")
        return ""

    try:
        tables_md_parts: list[str] = []
        table_count = 0
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            total_pages = len(pdf.pages)
            scan_pages = min(total_pages, max_pages)
            for page_idx in range(scan_pages):
                page = pdf.pages[page_idx]
                try:
                    tables = page.extract_tables() or []
                except Exception as e:
                    # 某些页表格提取失败不影响其他页
                    logger.debug(f"[表格提取] 第 {page_idx + 1} 页提取失败: {e}")
                    continue
                for tbl in tables:
                    md = _table_to_markdown(tbl)
                    if md:
                        table_count += 1
                        tables_md_parts.append(f"### 表格 {table_count} (页码 {page_idx + 1})\n\n{md}")

        if table_count == 0:
            logger.info("[表格提取] PDF 未检测到结构化表格")
            return ""

        result = "\n\n".join(tables_md_parts)
        logger.info(f"[表格提取] 共提取 {table_count} 个表格，Markdown 长度 {len(result)} 字符")
        return result
    except Exception as e:
        logger.warning(f"[表格提取] 表格提取失败（不影响纯文本提取）: {e}")
        return ""


def has_tables(file_bytes: bytes) -> bool:
    """快速判断 PDF 是否包含表格（只扫第一页）。"""
    if not HAS_PDFPLUMBER:
        return False
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                return False
            first = pdf.pages[0]
            tables = first.extract_tables() or []
            return any(tables)
    except Exception:
        return False

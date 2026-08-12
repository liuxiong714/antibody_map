import logging
import io
import re
from typing import Optional

try:
    import fitz  # PyMuPDF

    # 验证是否为真正的 PyMuPDF（而非冲突的 fitz 包）
    if not hasattr(fitz, "open"):
        raise ImportError("fitz module is not PyMuPDF")
    HAS_PYMUPDF = True
except ImportError:
    fitz = None
    HAS_PYMUPDF = False

# 尝试导入 MinerU（增强 PDF 解析，需安装 PyTorch）
HAS_MINERU = False
MINERU_AVAILABLE_MSG = ""
try:
    import torch
    from mineru.backend.hybrid.hybrid_analyze import doc_analyze as mineru_doc_analyze
    from mineru.data.data_reader_writer import FileBasedDataWriter
    from mineru.utils.pdfium_guard import (
        open_pdfium_document,
        get_pdfium_document_page_count,
        close_pdfium_document,
    )
    import pypdfium2 as pdfium
    HAS_MINERU = True
except ImportError as e:
    MINERU_AVAILABLE_MSG = f" ({e})"

from app.core.ocr_service import ocr_pdf_pages
from app.config import settings

logger = logging.getLogger("uvicorn")


def _extract_with_mineru(file_bytes: bytes) -> Optional[str]:
    """使用 MinerU 增强解析 PDF，返回结构化 Markdown 文本。"""
    if not HAS_MINERU or not settings.ENABLE_MINERU_PDF_PARSER:
        return None
    try:
        logger.info("[MinerU] 开始增强 PDF 解析...")
        # MinerU 首次运行会自动下载模型（pp_doclayout_v2, unimernet_small 等）
        middle_json, model_list = mineru_doc_analyze(
            pdf_bytes=file_bytes,
            image_writer=None,
            backend="transformers",
            parse_method="auto",
        )
        pdf_info = middle_json.get("pdf_info", [])
        if not pdf_info:
            logger.warning("[MinerU] 解析结果为空")
            return None

        # 从 MinerU 的 middle_json 中提取文本
        text_parts = []
        for page in pdf_info:
            page_text = page.get("text", "").strip()
            if page_text:
                text_parts.append(page_text)
            # 同时提取表格 Markdown 表示
            for block in page.get("blocks", []):
                if block.get("type") == "table":
                    table_md = _mineru_table_to_markdown(block)
                    if table_md:
                        text_parts.append(table_md)

        combined = "\n\n".join(text_parts)
        logger.info(f"[MinerU] 增强解析完成: {len(combined)} 字符")
        return combined
    except Exception as e:
        logger.warning(f"[MinerU] 解析失败，回退到 PyMuPDF: {e}")
        return None


def _mineru_table_to_markdown(table_block: dict) -> str:
    """将 MinerU 的表格 block 转为 Markdown 格式。"""
    try:
        rows = []
        for cell in table_block.get("cells", []):
            row_idx = cell.get("row_idx", 0)
            col_idx = cell.get("col_idx", 0)
            text = cell.get("text", "").strip()
            # 按行号组织
            while len(rows) <= row_idx:
                rows.append([])
            while len(rows[row_idx]) <= col_idx:
                rows[row_idx].append("")
            rows[row_idx][col_idx] = text

        if not rows:
            return ""

        md_lines = []
        # 表头分隔线
        header_sep = "|" + "|".join(["---"] * len(rows[0])) + "|"
        md_lines.append("|" + "|".join(rows[0]) + "|")
        md_lines.append(header_sep)
        for row in rows[1:]:
            md_lines.append("|" + "|".join(row) + "|")
        return "\n".join(md_lines)
    except Exception:
        return ""


def extract_text(file_bytes: bytes) -> str:
    """从 PDF 文件字节中提取文本。

    优先使用 MinerU 增强解析（若已安装且启用），
    否则回退到 PyMuPDF + OCR 兜底。
    """
    # 尝试 MinerU 增强解析
    if HAS_MINERU and settings.ENABLE_MINERU_PDF_PARSER:
        mineru_text = _extract_with_mineru(file_bytes)
        if mineru_text:
            return mineru_text
    elif not HAS_MINERU and settings.ENABLE_MINERU_PDF_PARSER:
        logger.warning(
            "[MinerU] 已启用但不可用，请安装 PyTorch 和 mineru："
            "pip install torch mineru"
        )

    if not HAS_PYMUPDF:
        logger.warning("PyMuPDF 不可用，PDF 解析被跳过")
        return ""

    # 单页有效文本少于该字符数 → 判定为扫描页/文字层损坏页，交给 OCR
    PAGE_TEXT_MIN = 100
    # 文本中数字字符少于该值 → 疑似字体编码损坏的乱码文本，也交给 OCR
    PAGE_DIGIT_MIN = 3

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text_parts = []
        page_images_for_ocr = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            # 先尝试直接提取文本
            page_text = page.get_text("text").strip()
            digit_count = len(re.findall(r"\d", page_text))
            if len(page_text) >= PAGE_TEXT_MIN and digit_count >= PAGE_DIGIT_MIN:
                full_text_parts.append(page_text)
            else:
                # 无文本或文本过短（扫描件/文字层损坏），整页交给 OCR
                # 同时保留少量文本作为 OCR 失败时的兜底
                if page_text:
                    full_text_parts.append(page_text)
                pix = page.get_pixmap(dpi=200)
                page_images_for_ocr.append(pix.tobytes("png"))

        doc.close()

        combined_text = "\n\n".join(full_text_parts)

        # 存在扫描页/文字层损坏页时，执行 OCR 兜底并合并结果
        if page_images_for_ocr:
            logger.info(
                f"检测到 {len(page_images_for_ocr)} 个页面文本过短，尝试 OCR 兜底..."
            )
            ocr_text = ocr_pdf_pages(
                page_images_for_ocr,
                fallback_to_baidu=settings.OCR_FALLBACK_TO_BAIDU,
                baidu_api_key=settings.BAIDU_OCR_API_KEY,
                baidu_secret_key=settings.BAIDU_OCR_SECRET_KEY,
            )
            if ocr_text:
                parts = full_text_parts + [ocr_text] if full_text_parts else [ocr_text]
                return "\n\n".join(parts)

        return combined_text if combined_text.strip() else ""

    except Exception as e:
        logger.error(f"PDF 解析失败: {e}")
        return ""

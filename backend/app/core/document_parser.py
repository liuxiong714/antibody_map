"""多格式文献文本提取分发器。

按文件扩展名分发到对应解析器，统一返回纯文本：
- .pdf  → PyMuPDF（复用 pdf_parser，含 OCR 兜底）
- .caj  → caj2pdf 转 PDF → PyMuPDF（尽力而为，失败抛 RuntimeError）
- .epub/.docx/.pptx/.xlsx/.txt/.html/.htm → 策略模式解析器（processors 包）
  各格式独立解析器类，通过 @register_parser 装饰器注册到 _PARSER_REGISTRY，
  新增格式只需在 processors 包下新建文件并注册。

MIME 映射表供上传校验、文件服务、MinIO 上传共用。
"""
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import settings
from app.core.parse_trace import record as trace_record
from app.core.pdf_parser import extract_text as pdf_extract_text
from app.core.processors import anydoc_parser, get_parser, pdf_inspector_parser

logger = logging.getLogger("uvicorn")

# 扩展名 → MIME 映射（上传白名单即该表的 keys）
# 注意：.html/.htm 已从白名单移除（XSS 防护），仅保留 MIME 映射供存量文件预览
MIME_MAP = {
    ".pdf": "application/pdf",
    ".caj": "application/octet-stream",
    ".epub": "application/epub+zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
}

ALLOWED_EXTS = set(MIME_MAP.keys())

# 标题清理时需识别的已知后缀（顺序无关，仅取首个匹配）
_KNOWN_EXTS = (".pdf", ".caj", ".epub", ".docx", ".pptx", ".xlsx", ".txt", ".html", ".htm")


def get_mime_type(file_ext: str) -> str:
    """按扩展名返回 MIME 类型，未知返回 application/octet-stream。"""
    ext = (file_ext or "").lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return MIME_MAP.get(ext, "application/octet-stream")


def normalize_ext(file_ext: str) -> str:
    """规范化扩展名为带点小写形式，默认 .pdf。"""
    ext = (file_ext or ".pdf").lower()
    if not ext.startswith("."):
        ext = "." + ext
    return ext


def _is_quality_acceptable(text: str) -> bool:
    """粗略质量检测：判定提取出的文本是否可用。

    条件（任一不满足即视为低质量，触发 MinerU GPU 增强回退）：
    - 文本长度 > 100 字符
    - 字母/数字占比 > 10%（排除大量乱码或特殊符号）
    - 至少包含 3 个数字（可能是表格数据）
    """
    if not text or len(text) <= 100:
        return False
    alnum = sum(c.isalnum() or c.isspace() for c in text)
    if alnum / len(text) <= 0.10:
        return False
    digit_count = sum(c.isdigit() for c in text[:2000])
    return not digit_count < 3


def extract_text(file_bytes: bytes, file_ext: str = ".pdf") -> str:
    """按扩展名分发到对应解析器，提取纯文本。

    CAJ 转换失败时抛 RuntimeError（由上层捕获并标记 failed），
    PDF 使用 pdf_parser（含 OCR 兜底），其他格式使用策略模式解析器。
    """
    ext = normalize_ext(file_ext)
    byte_len = len(file_bytes)
    logger.info(f"[文档解析] 开始解析: 格式={ext}, 文件大小={byte_len} 字节")

    # AnyDoc 增强路径（渐进式接入，默认关闭）：扩展名受支持且绑定可用时优先尝试。
    # 成功则直接用 AnyDoc 的 Markdown；任何异常/超时/不可用返回空字符串，走原逻辑。
    if (
        getattr(settings, "ENABLE_ANYDOC", False)
        and anydoc_parser.is_available()
        and anydoc_parser.supports(ext)
    ):
        md = anydoc_parser.to_markdown_bytes(file_bytes, ext)
        if md:
            logger.info(f"[文档解析] 解析路径=AnyDoc, 格式={ext}, 输出={len(md)} 字符")
            trace_record("anydoc")
            return md
        logger.info(f"[文档解析] 回退=策略解析器, 格式={ext}（AnyDoc 无有效输出）")

    # pdf-inspector 增强路径：仅对 PDF 格式，优先尝试 pdf-inspector 提取。
    # 若 pdf-inspector 可用且配置开启，尝试解析；失败时自动修复损坏 PDF 尾部结构
    # 重试；任何失败/超时回退到现有解析链。
    if (
        ext == ".pdf"
        and getattr(settings, "ENABLE_PDF_INSPECTOR", False)
        and pdf_inspector_parser.is_available()
    ):
        md = pdf_inspector_parser.to_markdown_bytes(file_bytes)
        if md and _is_quality_acceptable(md):
            logger.info(f"[文档解析] 解析路径=pdf-inspector, 格式={ext}, 输出={len(md)} 字符")
            trace_record("pdf-inspector")
            return md
        if md:
            logger.info(
                f"[文档解析] pdf-inspector 输出质量不足({len(md)} 字符)，触发 MinerU GPU 增强回退"
            )
        else:
            logger.info(f"[文档解析] 回退=现有解析链, 格式={ext}（pdf-inspector 无有效输出）")

    try:
        if ext == ".pdf":
            result = pdf_extract_text(file_bytes)
            text_len = len(result)
            # 具体走 MinerU 还是 PyMuPDF+OCR 的路径日志，由 pdf_parser 内部打印
            logger.info(f"[文档解析] PDF 解析完成: {text_len} 字符")
            trace_record("pdf")
            return result

        if ext == ".caj":
            logger.info("[文档解析] CAJ 格式，准备调用 caj2pdf 转换...")
            pdf_bytes = _caj_to_pdf_bytes(file_bytes)
            logger.info(f"[文档解析] CAJ 转换成功: {len(pdf_bytes)} 字节 PDF")
            result = pdf_extract_text(pdf_bytes)
            logger.info(f"[文档解析] CAJ 解析完成: {len(result)} 字符")
            trace_record("caj")
            return result

        # 策略模式：从 processors 注册表获取解析器
        parser = get_parser(ext)
        if parser is not None:
            parser_name = parser.__class__.__name__
            logger.info(f"[文档解析] 使用策略模式解析器: {parser_name} (格式={ext})")
            result = parser.extract_text(file_bytes)
            text_len = len(result)
            logger.info(f"[文档解析] {parser_name} 解析完成: {text_len} 字符")
            trace_record(parser_name)
            return result

        logger.warning(f"[文档解析] 未找到匹配的解析器: {ext}")
        raise ValueError(f"不支持的文件格式: {ext}")
    except RuntimeError:
        # CAJ 转换失败等显式错误，向上传播以便日志明确
        logger.warning(f"[文档解析] {ext} 解析抛出 RuntimeError，向上传播")
        raise
    except Exception as e:
        logger.error(f"[文档解析] 文件解析失败 ({ext}): {e}")
        return ""


def _caj_to_pdf_bytes(caj_bytes: bytes) -> bytes:
    """调用 caj2pdf 将 CAJ 转 PDF，返回 PDF 字节。

    依赖系统已安装 caj2pdf 命令与 mutool（mupdf-tools）。
    任一缺失或转换失败时抛 RuntimeError，由上层标记提取 failed。
    """
    if shutil.which("caj2pdf") is None:
        raise RuntimeError(
            "未安装 caj2pdf 命令，无法转换 CAJ（需 pip install caj2pdf 并安装 mutool）"
        )
    if shutil.which("mutool") is None:
        logger.warning("未检测到 mutool，CAJ 转换可能失败（caj2pdf 依赖 mutool）")

    with tempfile.TemporaryDirectory() as tmpdir:
        caj_path = Path(tmpdir) / "input.caj"
        pdf_path = Path(tmpdir) / "output.pdf"
        caj_path.write_bytes(caj_bytes)
        try:
            result = subprocess.run(
                ["caj2pdf", "convert", str(caj_path), "-o", str(pdf_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"caj2pdf 命令调用失败: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("CAJ 转换超时（120s）") from e

        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            stderr = (result.stderr or "").strip()
            tail = f": {stderr[:300]}" if stderr else ""
            raise RuntimeError(
                f"CAJ 转换失败，可能为不支持的 CAJ 变体或加密文件{tail}"
            )
        return pdf_path.read_bytes()

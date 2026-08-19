import asyncio
import concurrent.futures
import hashlib
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
    from mineru.backend.pipeline.pipeline_middle_json_mkcontent import (
        union_make as mineru_union_make,
    )
    from mineru.data.data_reader_writer import FileBasedDataWriter
    from mineru.utils.enum_class import MakeMode
    from mineru.utils.pdfium_guard import (
        open_pdfium_document,
        get_pdfium_document_page_count,
        close_pdfium_document,
    )
    import pypdfium2 as pdfium
    HAS_MINERU = True
except ImportError as e:
    MINERU_AVAILABLE_MSG = f" ({e})"

from app.core.ocr_service import ocr_tesseract_with_timeout
from app.config import settings
from app.core.parse_cache import get_cache, set_cache

logger = logging.getLogger("uvicorn")


def _run_cache_coro(coro):
    """在同步函数中执行异步缓存协程。

    无运行中的事件循环时直接用 asyncio.run；若已处于事件循环内（如 Celery 异步
    任务中调用 extract_text），则另起临时线程运行，避免 asyncio.run 报错。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=30)


async def _ocr_pages_async(
    page_images: list[bytes],
    *,
    lang: str = "chi_sim+eng",
    timeout: float = 60,
) -> list[str]:
    """并发对多页执行 OCR（asyncio.gather），保持页顺序；超时/失败页被跳过。

    并发上限复用 settings.LLM_CONCURRENCY（不新造配置）；gather 返回顺序与传入
    页顺序一致，因此无需额外排序。
    """
    concurrency = max(1, int(getattr(settings, "LLM_CONCURRENCY", 4)))
    sem = asyncio.Semaphore(concurrency)

    async def _ocr_one(page_bytes: bytes) -> Optional[str]:
        async with sem:
            return await ocr_tesseract_with_timeout(page_bytes, lang=lang, timeout=timeout)

    results = await asyncio.gather(*(_ocr_one(pb) for pb in page_images))
    return [r for r in results if r]


def _run_ocr_gather(page_images: list[bytes]) -> Optional[str]:
    """在同步的 extract_text 中执行并发 OCR，兼容有无运行中事件循环。

    复用 _run_cache_coro 的调度思路：无运行中循环用 asyncio.run；已处于循环内
    则另起临时线程跑独立循环。每页超时由 ocr_tesseract_with_timeout 隔离，因此
    单页卡死不会阻塞整篇。
    """
    async def _run() -> Optional[str]:
        texts = await _ocr_pages_async(page_images)
        if not texts:
            return None
        return "\n\n--- PAGE SEPARATOR ---\n\n".join(texts)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _run).result()


def _extract_with_mineru(file_bytes: bytes) -> Optional[str]:
    """使用 MinerU 增强解析 PDF，返回结构化 Markdown 文本。

    MinerU 在 Celery prefork（daemonic）进程中无法直接运行——内部会 spawn 子进程，
    触发 "daemonic processes are not allowed to have children" 异常。因此通过独立
    子进程隔离执行（app.core.mineru_worker）：子进程非 daemonic，可正常派生进程，
    且 MinerU 崩溃/超时不会拖垮 worker 主进程。
    """
    if not HAS_MINERU or not settings.ENABLE_MINERU_PDF_PARSER:
        return None

    timeout = getattr(settings, "MINERU_PARSE_TIMEOUT", 600)
    logger.info("[MinerU] 开始增强 PDF 解析（子进程隔离）...")
    tmp_path = None
    try:
        import subprocess
        import sys as _sys
        import tempfile
        import os as _os
        import signal as _signal
        from pathlib import Path as _Path

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(file_bytes)
            tmp_path = tf.name

        # 工作目录指向 backend 根目录（如 /app/backend），保证 `-m app.core...` 可导入
        cwd = _Path(__file__).resolve().parent.parent.parent
        env = dict(_os.environ)
        env["PYTHONPATH"] = str(cwd)

        proc = subprocess.Popen(
            [_sys.executable, "-m", "app.core.mineru_worker", tmp_path],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # 独立进程组，便于超时后整组清理
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning(f"[MinerU] 解析超时（>{timeout}s），终止子进程并回退 PyMuPDF")
            try:
                _os.killpg(_os.getpgid(proc.pid), _signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            proc.wait(timeout=10)
            return None

        if proc.returncode != 0:
            err_txt = err.decode("utf-8", errors="replace").strip()[-500:]
            logger.warning(f"[MinerU] 子进程退出码 {proc.returncode}，回退 PyMuPDF: {err_txt}")
            return None

        markdown_text = out.decode("utf-8", errors="replace")
        if not markdown_text.strip():
            logger.warning("[MinerU] 解析结果为空")
            return None
        logger.info(f"[MinerU] 增强解析完成: {len(markdown_text)} 字符")
        return markdown_text
    except Exception as e:
        logger.warning(f"[MinerU] 解析失败，回退到 PyMuPDF: {e}")
        return None
    finally:
        if tmp_path:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass


def extract_text(file_bytes: bytes) -> str:
    """从 PDF 文件字节中提取文本。

    优先使用 MinerU 增强解析（若已安装且启用），
    否则回退到 PyMuPDF + OCR 兜底。
    """
    # 缓存：以文件字节 sha256 为 key，命中则直接复用，避免重复跑最慢的 MinerU/OCR
    cache_key = hashlib.sha256(file_bytes).hexdigest()
    cached = _run_cache_coro(get_cache(cache_key))
    if cached is not None:
        logger.info(f"[解析缓存] 命中: key={cache_key[:12]}…, 文本 {len(cached)} 字符")
        return cached

    def _cache_result(result: str) -> str:
        """解析成功后写入缓存（空结果不缓存），并原样返回。"""
        if result:
            _run_cache_coro(set_cache(cache_key, result))
        return result

    # 尝试 MinerU 增强解析
    if HAS_MINERU and settings.ENABLE_MINERU_PDF_PARSER:
        mineru_text = _extract_with_mineru(file_bytes)
        if mineru_text:
            return _cache_result(mineru_text)
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

        # 存在扫描页/文字层损坏页时，并发执行 OCR 兜底并合并结果
        if page_images_for_ocr:
            logger.info(
                f"检测到 {len(page_images_for_ocr)} 个页面文本过短，尝试 OCR 兜底"
                f"（并发={max(1, int(getattr(settings, 'LLM_CONCURRENCY', 4)))}）..."
            )
            ocr_text = _run_ocr_gather(page_images_for_ocr)
            if ocr_text:
                parts = full_text_parts + [ocr_text] if full_text_parts else [ocr_text]
                return _cache_result("\n\n".join(parts))

        return _cache_result(combined_text if combined_text.strip() else "")

    except Exception as e:
        logger.error(f"PDF 解析失败: {e}")
        return ""

"""共享导入与辅助函数 —— 从原 literature.py 提取，供拆分子路由使用。"""

import io
import logging
import re
import uuid
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger("uvicorn")

from fastapi import HTTPException  # noqa: E402
from fastapi.responses import Response, StreamingResponse  # noqa: E402

from app.core.document_parser import ALLOWED_EXTS  # noqa: E402
from app.services.literature._common import (  # noqa: E402
    LOCAL_STORAGE_DIR,
)

# ===== 辅助函数 =====


def _resolve_literature_file(literature) -> Path | None:
    """解析文献文件在磁盘上的真实路径。

    数据库中存储的 file_path 可能是 Windows 绝对路径（E:\\...），
    当后端运行在 Docker 容器（Linux）中时无法直接访问该路径。
    仅解析与 LOCAL_STORAGE_DIR 相对的路径，并校验路径不越界。
    """
    raw = (literature.file_path or "").strip()
    if not raw:
        return None

    # 去除可能的 Windows 盘符前缀与目录前缀，仅保留相对部分
    rel = raw.replace("\\", "/")
    rel = re.sub(r"^[A-Za-z]:", "", rel)
    # 取 data/pdfs 之后的相对路径，兼容绝对/相对两种写法
    if "/data/pdfs/" in rel:
        rel = rel.split("/data/pdfs/", 1)[1]
    elif rel.startswith("/backend/data/pdfs/"):
        rel = rel.split("/backend/data/pdfs/", 1)[1]
    elif rel.startswith("/app/backend/data/pdfs/"):
        rel = rel.split("/app/backend/data/pdfs/", 1)[1]
    else:
        rel = rel.lstrip("/")
    if not rel:
        return None

    target = (LOCAL_STORAGE_DIR / rel).resolve()
    try:
        if target.is_relative_to(LOCAL_STORAGE_DIR.resolve()) and target.exists() and target.is_file():
            return target
    except OSError:
        pass
    return None


def _build_safe_filename(title: str | None, ext: str, literature_id: uuid.UUID) -> str:
    """构建下载文件名：去除标题已含的已知后缀，清理非法字符，附加真实扩展名。"""
    raw = title or str(literature_id)
    raw_lower = raw.lower()
    for known in ALLOWED_EXTS:
        if raw_lower.endswith(known):
            raw = raw[: -len(known)]
            break
    safe = "".join(c for c in raw if c not in r'\/:*?"<>|').strip() or str(literature_id)
    return quote(f"{safe}{ext}")


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)", re.IGNORECASE)
_CHUNK_SIZE = 1024 * 1024


def _read_file_chunked(path: Path, start: int, length: int):
    """按 1MB 分块读取文件的 [start, start+length) 区间，用于流式响应，避免一次性读入内存。"""
    remaining = length
    with open(path, "rb") as f:
        f.seek(start)
        while remaining > 0:
            data = f.read(min(_CHUNK_SIZE, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def _build_file_response(
    file_path: Path,
    mime_type: str,
    disposition: str,
    filename: str,
    range_header: str | None,
) -> Response:
    """构建支持 HTTP Range（206 Partial Content）的文件响应。

    pdf.js 等前端预览器加载 PDF 时会发起 Range 请求；若服务端不支持，
    会返回 200 全量流，导致 pdf.js abort 重试并报 "Rendering cancelled"。
    """
    file_size = file_path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }

    if range_header:
        m = _RANGE_RE.match(range_header.strip())
        if m:
            start_s, end_s = m.groups()
            start = int(start_s) if start_s else None
            end = int(end_s) if end_s else None

            if start is None and end is not None:
                # bytes=-N 后缀区间：取最后 N 字节
                suffix = min(end, file_size)
                start = max(file_size - suffix, 0)
                end = file_size - 1
            else:
                start = start if start is not None else 0
                if start >= file_size:
                    raise HTTPException(status_code=416, detail="请求的文件范围不可满足")
                if end is None or end >= file_size:
                    end = file_size - 1

            if start <= end:
                length = end - start + 1
                headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
                headers["Content-Length"] = str(length)
                logger.info(f"[预览] Range 请求: {range_header!r} -> bytes {start}-{end}/{file_size}")
                return StreamingResponse(
                    _read_file_chunked(file_path, start, length),
                    status_code=206,
                    media_type=mime_type,
                    headers=headers,
                )

    headers["Content-Length"] = str(file_size)
    return StreamingResponse(
        _read_file_chunked(file_path, 0, file_size),
        status_code=200,
        media_type=mime_type,
        headers=headers,
    )


# CAJ → PDF 转换结果缓存（key=mdf5(原文件字节)，value=PDF 字节），避免同一文件重复转换
_caj_pdf_cache: dict[str, bytes] = {}


def _caj_pdf_key(file_path: Path) -> str:
    """基于文件路径+大小+修改时间生成缓存 key，文件变化后自动失效。"""
    st = file_path.stat()
    return f"{file_path}:{st.st_size}:{st.st_mtime_ns}"


def _build_pdf_bytes_response(
    pdf_bytes: bytes,
    mime_type: str,
    disposition: str,
    filename: str,
    range_header: str | None,
) -> Response:
    """基于内存 PDF 字节构建支持 HTTP Range 的流式响应（用于 CAJ 实时转换预览）。"""
    file_size = len(pdf_bytes)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }

    if range_header:
        m = _RANGE_RE.match(range_header.strip())
        if m:
            start_s, end_s = m.groups()
            start = int(start_s) if start_s else None
            end = int(end_s) if end_s else None

            if start is None and end is not None:
                suffix = min(end, file_size)
                start = max(file_size - suffix, 0)
                end = file_size - 1
            else:
                start = start if start is not None else 0
                if start >= file_size:
                    raise HTTPException(status_code=416, detail="请求的文件范围不可满足")
                if end is None or end >= file_size:
                    end = file_size - 1

            if start <= end:
                length = end - start + 1
                headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
                headers["Content-Length"] = str(length)
                logger.info(f"[预览CAJ] Range 请求: {range_header!r} -> bytes {start}-{end}/{file_size}")
                return StreamingResponse(
                    io.BytesIO(pdf_bytes[start : start + length]),
                    status_code=206,
                    media_type=mime_type,
                    headers=headers,
                )

    headers["Content-Length"] = str(file_size)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        status_code=200,
        media_type=mime_type,
        headers=headers,
    )


# 简单魔数签名（文件头前 N 字节），无需 python-magic
_MAGIC_SIGNATURES = {
    ".pdf": (b"%PDF", 4),
    ".caj": (b"Caj ", 4),
    ".docx": (b"PK\x03\x04", 4),
    ".pptx": (b"PK\x03\x04", 4),
    ".xlsx": (b"PK\x03\x04", 4),
    ".epub": (b"PK\x03\x04", 4),
    # .txt 无固定魔数，跳过校验
}


def _validate_file_magic(ext: str, data: bytes) -> bool:
    """校验文件头与扩展名是否一致。返回 True 表示合法，False 表示魔数不匹配。"""
    sig = _MAGIC_SIGNATURES.get(ext)
    if sig is None:
        return True  # 无魔数定义（如 .txt），跳过
    magic, length = sig
    return len(data) >= length and data[:length] == magic


def _format_file_history(history) -> list[dict]:
    """把文件历史记录转成前端可读的 dict 列表（时间倒序）。"""
    out = []
    for h in history:
        out.append({
            "operation": "imported" if h.action == "imported" else "deleted",
            "operated_at": h.operated_at.isoformat(),
            "operator_name": h.operator_name or "未知",
            "file_name": h.file_name,
        })
    return out
"""Crossref 检索服务：封装 Crossref REST API 检索学术文献。

- search_crossref ：GET https://api.crossref.org/works 检索，返回统一结构
  统一结构：{ "items": [ { id, source, title, authors, year, journal, doi,
  abstract, oa_pdf_url } ], "total": int }
"""
import html
import logging
import re
from urllib.parse import quote

from app.core.external_http import get_json

logger = logging.getLogger("uvicorn")

_CROSSREF_API = "https://api.crossref.org/works"
_MAILTO = "research@example.com"

# 简单去 HTML 标签（Crossref 的 abstract 常含 <jats:p> 等标签）
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_abstract(raw: str) -> str:
    """去掉 HTML 标签并反转义实体，返回纯文本摘要。"""
    if not raw:
        return ""
    text = _TAG_RE.sub("", raw)
    return html.unescape(text).strip()


def _parse_item(item: dict) -> dict:
    """把单条 Crossref work 解析为统一结构。"""
    # 标题：item.title[0]（可能缺失）
    title_list = item.get("title") or []
    title = title_list[0] if title_list else ""

    # 作者：前 3 位，每个 "given family"，逗号分隔
    authors = ""
    author_list = item.get("author") or []
    name_parts = []
    for auth in author_list[:3]:
        given = (auth.get("given") or "").strip()
        family = (auth.get("family") or "").strip()
        name = f"{given} {family}".strip()
        if name:
            name_parts.append(name)
    if name_parts:
        authors = ", ".join(name_parts)

    # 年份：published-print → published-online → issued
    year = ""
    for key in ("published-print", "published-online", "issued"):
        date_parts = (item.get(key) or {}).get("date-parts") or []
        if date_parts and date_parts[0] and date_parts[0][0]:
            year = str(date_parts[0][0])
            break

    # 期刊：container-title[0]（可能缺失）
    container = item.get("container-title") or []
    journal = container[0] if container else ""

    return {
        "id": item.get("DOI") or "",
        "source": "crossref",
        "title": title,
        "authors": authors,
        "year": year,
        "journal": journal,
        "doi": item.get("DOI") or "",
        "abstract": _clean_abstract(item.get("abstract") or ""),
        "oa_pdf_url": "",  # Crossref 不直接提供 OA PDF 直链，留空
    }


async def search_crossref(query: str, page: int = 1, page_size: int = 20) -> dict:
    """检索 Crossref，返回统一结构 {items, total, page, page_size}。

    失败时返回空结果并记录 warning，避免单个上游异常拖垮接口。
    """
    query = (query or "").strip()
    page = max(1, page)
    page_size = max(1, page_size)
    if not query:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    rows = page_size
    offset = (page - 1) * page_size
    url = (
        f"{_CROSSREF_API}?query={quote(query)}"
        f"&rows={rows}&offset={offset}&mailto={_MAILTO}"
    )
    try:
        data = await get_json(url)
    except Exception as e:
        logger.warning(f"[Crossref] 检索失败 q={query!r}: {e}")
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    message = data.get("message") or {}
    items = [_parse_item(item) for item in (message.get("items") or [])]
    try:
        total = int(message.get("total-results") or len(items))
    except (TypeError, ValueError):
        total = len(items)

    logger.info(f"[Crossref] 检索完成: q={query!r}, total={total}, 返回 {len(items)} 条")
    return {"items": items, "total": total, "page": page, "page_size": page_size}

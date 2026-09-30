"""OpenAlex 检索服务：封装 OpenAlex Works API 检索学术文献。

- search_openalex ：GET https://api.openalex.org/works 检索，返回统一结构
  统一结构：{ "items": [ { id, source, title, authors, year, journal, doi,
  abstract, oa_pdf_url } ], "total": int }
"""
import logging
from urllib.parse import quote

from app.core.external_http import get_json

logger = logging.getLogger("uvicorn")

_OPENALEX_API = "https://api.openalex.org/works"


def _parse_item(item: dict) -> dict:
    """把单条 OpenAlex work 解析为统一结构。"""
    # id：doi 或 item.id
    wid = item.get("doi") or item.get("id") or ""

    # 作者：authorships 里每个 author.display_name，取前 3
    authors = ""
    author_names = []
    for auth in (item.get("authorships") or [])[:3]:
        display_name = ((auth.get("author") or {}).get("display_name") or "").strip()
        if display_name:
            author_names.append(display_name)
    if author_names:
        authors = ", ".join(author_names)

    # 期刊：primary_location.source.display_name，source 可能为 None，层层安全取值
    journal = ""
    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") or {}
    journal = (source.get("display_name") or "") if source else ""

    # OA PDF 直链：open_access.oa_url（可能 None）
    oa_url = ""
    open_access = item.get("open_access") or {}
    oa_url = open_access.get("oa_url") or ""

    return {
        "id": wid,
        "source": "openalex",
        "title": item.get("title") or "",
        "authors": authors,
        "year": str(item["publication_year"]) if item.get("publication_year") else "",
        "journal": journal,
        "doi": item.get("doi") or "",
        # abstract_inverted_index 解析复杂，统一留空
        "abstract": "",
        "oa_pdf_url": oa_url,
    }


async def search_openalex(query: str, page: int = 1, page_size: int = 20) -> dict:
    """检索 OpenAlex，返回统一结构 {items, total, page, page_size}。

    失败时返回空结果并记录 warning，避免单个上游异常拖垮接口。
    """
    query = (query or "").strip()
    page = max(1, page)
    page_size = max(1, page_size)
    if not query:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    url = (
        f"{_OPENALEX_API}?search={quote(query)}"
        f"&per-page={page_size}&page={page}"
    )
    try:
        data = await get_json(url)
    except Exception as e:
        logger.warning(f"[OpenAlex] 检索失败 q={query!r}: {e}")
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    items = [_parse_item(item) for item in (data.get("results") or [])]
    meta = data.get("meta") or {}
    try:
        total = int(meta.get("count") or len(items))
    except (TypeError, ValueError):
        total = len(items)

    logger.info(f"[OpenAlex] 检索完成: q={query!r}, total={total}, 返回 {len(items)} 条")
    return {"items": items, "total": total, "page": page, "page_size": page_size}

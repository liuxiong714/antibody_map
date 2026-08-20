"""Europe PMC 检索服务：封装 Europe PMC REST API 检索学术文献。

- search_europepmc ：GET https://www.ebi.ac.uk/europepmc/webservices/rest/search 检索，
  返回统一结构
  统一结构：{ "items": [ { id, source, title, authors, year, journal, doi,
  abstract, oa_pdf_url } ], "total": int }
"""
import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger("uvicorn")

_EUROPE_PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_REQUEST_TIMEOUT = 60


async def _http_get_json(url: str) -> dict:
    """GET 请求并解析 JSON；失败抛异常。"""
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


def _find_oa_pdf_url(item: dict) -> str:
    """从 fullTextUrlList 中找 documentStyle 含 'pdf' 的 url，找不到返回空串。"""
    full_text_urls = item.get("fullTextUrlList") or {}
    for u in full_text_urls.get("fullTextUrl") or []:
        doc_style = (u.get("documentStyle") or "").lower()
        if "pdf" in doc_style and u.get("url"):
            return u["url"]
    return ""


def _parse_item(item: dict) -> dict:
    """把单条 Europe PMC 记录解析为统一结构。"""
    pmid = item.get("id") or ""
    source = item.get("source") or ""
    # id：item.id（PMID），缺失时用 source+id 兜底
    wid = pmid if pmid else f"{source}{pmid}"

    # 期刊：journalInfo.journal.title（安全取值）
    journal = ""
    journal_info = item.get("journalInfo") or {}
    journal = ((journal_info.get("journal") or {}).get("title") or "")

    return {
        "id": wid,
        "source": "europepmc",
        "title": item.get("title") or "",
        "authors": item.get("authorString") or "",
        "year": str(item["pubYear"]) if item.get("pubYear") else "",
        "journal": journal,
        "doi": item.get("doi") or "",
        "abstract": item.get("abstractText") or "",
        "oa_pdf_url": _find_oa_pdf_url(item),
    }


async def search_europepmc(query: str, page: int = 1, page_size: int = 20) -> dict:
    """检索 Europe PMC，返回统一结构 {items, total, page, page_size}。

    失败时返回空结果并记录 warning，避免单个上游异常拖垮接口。
    """
    query = (query or "").strip()
    page = max(1, page)
    page_size = max(1, page_size)
    if not query:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    url = (
        f"{_EUROPE_PMC_API}?query={quote(query)}"
        f"&resultType=core&pageSize={page_size}&format=json&page={page}"
    )
    try:
        data = await _http_get_json(url)
    except Exception as e:
        logger.warning(f"[EuropePMC] 检索失败 q={query!r}: {e}")
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    result_list = data.get("resultList") or {}
    results = result_list.get("result") or []
    items = [_parse_item(item) for item in results]
    try:
        total = int(data.get("hitCount") or len(items))
    except (TypeError, ValueError):
        total = len(items)

    logger.info(f"[EuropePMC] 检索完成: q={query!r}, total={total}, 返回 {len(items)} 条")
    return {"items": items, "total": total, "page": page, "page_size": page_size}

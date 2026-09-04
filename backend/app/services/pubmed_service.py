"""PubMed 检索服务：封装 NCBI E-utilities 的 esearch + esummary + efetch。

- search_pubmed       ：esearch 拿 PMID 列表 → esummary 拿元数据 → 本地分页
- get_pubmed_abstract ：efetch 拿摘要纯文本

限速：NCBI 要求 ≤ 3 次/秒（无 API key），每次请求前固定 sleep 0.35s；
失败重试 3 次，指数退避 1/2/4 秒。
"""
import asyncio
import json
import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger("uvicorn")

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# 每次请求前的最小间隔（秒），符合 NCBI 无 API key 的 3 次/秒限速要求
_REQUEST_INTERVAL = 0.35
# 失败重试次数（1 次初始 + 3 次重试 = 4 次尝试），退避 2**attempt 秒 → 1/2/4
_MAX_RETRIES = 3
_REQUEST_TIMEOUT = 30


async def _http_get(url: str, *, as_text: bool = False) -> str:
    """带限速与指数退避重试的 GET 请求，返回响应文本（含 JSON 原文）。

    每次请求前 sleep _REQUEST_INTERVAL 秒；失败时指数退避重试 1/2/4 秒，
    全部失败后抛最后一次异常。
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        await asyncio.sleep(_REQUEST_INTERVAL)
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
        except Exception as e:
            last_exc = e
            logger.warning(f"[PubMed] 请求失败(第{attempt + 1}次): {url[:120]} → {e}")
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)  # 指数退避：1/2/4 秒
    assert last_exc is not None
    raise last_exc


def _parse_esummary(rec: dict) -> dict:
    """把单条 esummary 记录解析为前端需要的字段。"""
    pmid = rec.get("uid") or ""
    doi = ""
    for aid in rec.get("articleids") or []:
        if aid.get("idtype") == "doi":
            doi = aid.get("value") or ""
            break
    authors = rec.get("authors") or []
    first_author = authors[0].get("name") if authors else None
    pubdate = rec.get("pubdate") or ""
    year = pubdate[:4] if pubdate else None
    return {
        "pmid": pmid,
        "title": rec.get("title"),
        "authors": first_author,  # 仅取第一作者
        "year": year,             # pubdate 前 4 位
        "journal": rec.get("fulljournalname"),
        "doi": doi,
        "volume": rec.get("volume"),
        "issue": rec.get("issue"),
    }


async def search_pubmed(query: str, page: int = 1, page_size: int = 20) -> dict:
    """esearch 拿 PMID 列表，再 esummary 拿元数据，返回分页结果。"""
    query = (query or "").strip()
    if not query:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    esearch_url = (
        f"{EUTILS_BASE}/esearch.fcgi"
        f"?db=pubmed&term={quote(query)}&retmax=200&retmode=json"
    )
    esearch_text = await _http_get(esearch_url)
    esearch_data = json.loads(esearch_text)
    esearch_result = esearch_data.get("esearchresult") or {}
    id_list = esearch_result.get("idlist") or []
    try:
        total = int(esearch_result.get("count") or len(id_list))
    except (TypeError, ValueError):
        total = len(id_list)

    items: list[dict] = []
    if id_list:
        start = (page - 1) * page_size
        page_ids = id_list[start:start + page_size]
        if page_ids:
            esummary_url = (
                f"{EUTILS_BASE}/esummary.fcgi"
                f"?db=pubmed&id={','.join(page_ids)}&retmode=json"
            )
            esummary_text = await _http_get(esummary_url)
            esummary_data = json.loads(esummary_text)
            result_map = esummary_data.get("result") or {}
            for pmid in page_ids:
                rec = result_map.get(pmid)
                # esummary 对无数据的 PMID 会返回 {"uid": "empty"}
                if not rec or rec.get("uid") in (None, "empty"):
                    continue
                items.append(_parse_esummary(rec))

    logger.info(
        f"[PubMed] 检索完成: q={query!r}, total={total}, 返回 {len(items)} 条"
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def get_pubmed_abstract(pmid: str) -> str:
    """efetch 获取摘要纯文本；失败返回空串。"""
    pmid = (pmid or "").strip()
    if not pmid:
        return ""
    efetch_url = (
        f"{EUTILS_BASE}/efetch.fcgi"
        f"?db=pubmed&id={pmid}&rettype=abstract&retmode=text"
    )
    try:
        text = await _http_get(efetch_url)
        return text.strip()
    except Exception as e:
        logger.warning(f"[PubMed] 获取摘要失败 pmid={pmid}: {e}")
        return ""

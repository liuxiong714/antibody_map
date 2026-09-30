"""PubMed 开放获取全文查询与 PDF 下载。

- fetch_oa_pdf_url ：通过 Europe PMC REST 查询某 PMID 的开放获取全文直链
- download_pdf     ：用 httpx 下载 PDF 到指定目录，返回保存后的绝对路径
"""
import asyncio
import logging
from pathlib import Path

import httpx

logger = logging.getLogger("uvicorn")

_EUROPE_PMC_SEARCH = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    "?query=EXT_ID:{pmid}%20AND%20SRC:MED&resultType=core&format=json"
)
_REQUEST_TIMEOUT = 60
# 查询欧洲 PMC 前同样做基础限速，避免对上游造成压力
_REQUEST_INTERVAL = 0.35


async def fetch_oa_pdf_url(pmid: str) -> str:
    """查询 PMID 的开放获取全文 PDF 直链，找不到返回空串。

    从 fullTextUrlList 中查找 documentStyle 包含 "pdf" 的 url。
    """
    pmid = (pmid or "").strip()
    if not pmid:
        return ""
    url = _EUROPE_PMC_SEARCH.format(pmid=pmid)
    try:
        await asyncio.sleep(_REQUEST_INTERVAL)
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"[PubMed/OA] 查询 OA 全文失败 pmid={pmid}: {e}")
        return ""

    result_list = data.get("resultList") or {}
    results = result_list.get("result") or []
    if not results:
        return ""
    full_text_urls = results[0].get("fullTextUrlList") or {}
    for item in full_text_urls.get("fullTextUrl") or []:
        doc_style = (item.get("documentStyle") or "").lower()
        if "pdf" in doc_style and item.get("url"):
            return item["url"]
    return ""


async def download_pdf(url: str, dest_dir: Path, filename: str) -> str:
    """下载 PDF 到 dest_dir/filename，返回保存后的绝对路径；失败抛异常。"""
    if not url:
        raise ValueError("下载地址为空")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    await asyncio.sleep(_REQUEST_INTERVAL)
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest_path.write_bytes(resp.content)

    logger.info(f"[PubMed/OA] PDF 已下载: {dest_path}")
    return str(dest_path.resolve())

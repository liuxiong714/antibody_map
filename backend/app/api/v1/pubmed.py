"""PubMed 检索代理 API 端点。

- GET /pubmed/search?q=&page=&page_size=   ：检索 PubMed（esearch + esummary）
- GET /pubmed/abstract/{pmid}              ：获取某篇文献的摘要（efetch）
- POST /pubmed/import                      ：将 PMID 列表纳入文献库
- POST /pubmed/download-pdf                ：下载开放获取 PDF 到本地目录

注册在 router.py 的 _protected 下，需登录态访问。
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.schemas.common import ApiResponse
from app.schemas.literature import LiteratureCreate
from app.services.crossref_service import search_crossref
from app.services.europepmc_service import search_europepmc
from app.services.literature_service import LOCAL_STORAGE_DIR, create_literature
from app.services.openalex_service import search_openalex
from app.services.pubmed_pdf import download_pdf, fetch_oa_pdf_url
from app.services.pubmed_service import (
    EUTILS_BASE,
    _http_get,
    _parse_esummary,
    get_pubmed_abstract,
    search_pubmed,
)

logger = logging.getLogger("uvicorn")

router = APIRouter(prefix="/pubmed")


class PubmedImportBody(BaseModel):
    """纳入文献库的 PMID 列表。"""

    pmids: list[str]


class PubmedDownloadBody(BaseModel):
    """下载开放获取 PDF 的 PMID 列表。"""

    pmids: list[str]


async def _fetch_esummary_meta(pmid: str) -> dict:
    """单 PMID 的 esummary 元数据（复用 pubmed_service 的限速/解析逻辑）。"""
    url = f"{EUTILS_BASE}/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
    try:
        text = await _http_get(url)
    except Exception as e:
        logger.warning(f"[PubMed] esummary 失败 pmid={pmid}: {e}")
        return {}
    data = json.loads(text)
    rec = (data.get("result") or {}).get(pmid) or {}
    if not rec or rec.get("uid") in (None, "empty"):
        return {}
    return _parse_esummary(rec)


@router.get("/search", response_model=ApiResponse, summary="PubMed 检索", description="封装 NCBI E-utilities esearch+esummary 检索 PubMed，返回分页结果")
async def pubmed_search(
    q: str = Query(..., description="检索词（如：measles China）"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=50, description="每页条数"),
):
    """检索 PubMed，返回 {items, total, page, page_size}。"""
    data = await search_pubmed(q, page=page, page_size=page_size)
    return ApiResponse(data=data)


# 多源检索：source → service 分发映射
_MULTI_SEARCHERS = {
    "crossref": search_crossref,
    "openalex": search_openalex,
    "europepmc": search_europepmc,
}


@router.get("/search/multi", response_model=ApiResponse, summary="多源检索", description="按 source 调用 Crossref / OpenAlex / Europe PMC 检索，返回统一分页结果")
async def pubmed_search_multi(
    q: str = Query(..., description="检索词（如：measles antibody）"),
    source: str = Query("crossref", description="检索来源：crossref / openalex / europepmc"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=50, description="每页条数"),
):
    """按 source 调用对应服务，返回 {items, total, page, page_size, source}。"""
    source = (source or "").strip().lower()
    searcher = _MULTI_SEARCHERS.get(source)
    if searcher is None:
        raise HTTPException(status_code=400, detail=f"不支持的检索来源: {source}，可选 crossref / openalex / europepmc")
    data = await searcher(q, page=page, page_size=page_size)
    data["source"] = source
    return ApiResponse(data=data)


@router.get("/abstract/{pmid}", response_model=ApiResponse, summary="获取 PubMed 摘要", description="通过 efetch 获取指定 PMID 的摘要纯文本")
async def pubmed_abstract(pmid: str):
    """获取摘要纯文本，返回 {pmid, abstract}。"""
    abstract = await get_pubmed_abstract(pmid)
    return ApiResponse(data={"pmid": pmid, "abstract": abstract})


@router.post("/import", response_model=ApiResponse, summary="PubMed 文献纳入库", description="将 PMID 列表经 esummary 取元数据后调用 create_literature 纳入文献库")
async def pubmed_import(
    body: PubmedImportBody,
    db: AsyncSession = Depends(get_db),
):
    """纳入文献库，返回成功/失败计数与已入库的 literature_id 列表。"""
    imported_ids: list[str] = []
    failed_pmids: list[str] = []
    for pmid in body.pmids:
        pmid = (pmid or "").strip()
        if not pmid:
            continue
        try:
            meta = await _fetch_esummary_meta(pmid)
            if not meta or not meta.get("title"):
                failed_pmids.append(pmid)
                continue
            lit = await create_literature(
                db,
                LiteratureCreate(
                    title=meta["title"],
                    authors=meta.get("authors"),
                    journal=meta.get("journal"),
                    pub_year=int(meta["year"]) if meta.get("year") else None,
                    doi=meta.get("doi"),
                    pmid=pmid,
                    source_db="pubmed",
                ),
            )
            imported_ids.append(str(lit.id))
        except Exception as e:
            logger.warning(f"[PubMed] 纳入失败 pmid={pmid}: {e}")
            failed_pmids.append(pmid)
    return ApiResponse(data={
        "success_count": len(imported_ids),
        "fail_count": len(failed_pmids),
        "imported_ids": imported_ids,
        "failed_pmids": failed_pmids,
    })


@router.post("/download-pdf", response_model=ApiResponse, summary="下载 PubMed 开放获取 PDF", description="查询 Europe PMC OA 全文直链并下载到本地目录")
async def pubmed_download_pdf(body: PubmedDownloadBody):
    """下载 OA PDF 到指定目录，返回 {downloaded, no_oa, failed, dir}。"""
    dest_dir = Path(settings.PDF_DOWNLOAD_DIR) if settings.PDF_DOWNLOAD_DIR else LOCAL_STORAGE_DIR
    downloaded: list[str] = []
    no_oa: list[str] = []
    failed: list[str] = []
    for pmid in body.pmids:
        pmid = (pmid or "").strip()
        if not pmid:
            continue
        try:
            url = await fetch_oa_pdf_url(pmid)
            if not url:
                no_oa.append(pmid)
                continue
            await download_pdf(url, dest_dir, f"{pmid}.pdf")
            downloaded.append(pmid)
        except Exception as e:
            logger.warning(f"[PubMed] PDF 下载失败 pmid={pmid}: {e}")
            failed.append(pmid)
    return ApiResponse(data={
        "downloaded": downloaded,
        "no_oa": no_oa,
        "failed": failed,
        "dir": str(dest_dir),
    })

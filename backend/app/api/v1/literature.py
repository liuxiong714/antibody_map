import csv
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger("uvicorn")

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.schemas.common import ApiResponse, PagedResponse
from app.schemas.literature import (
    LiteratureCreate, LiteratureResponse, LiteratureUpdate,
    CheckDuplicateRequest, MergePreviewRequest, MergeRequest,
)
from app.core.document_parser import ALLOWED_EXTS, get_mime_type
from app.core.url_fetcher import fetch_url, guess_title_from_html
from app.services.literature_service import (
    list_literature,
    get_literature,
    create_literature,
    update_literature,
    delete_literature,
    upload_literature,
    upload_literature_file,
    check_duplicates,
    scan_duplicates,
    preview_merge,
    merge_literatures,
    _clean_filename_title,
)
from app.services.extraction_service import trigger_extraction

router = APIRouter()


def _build_safe_filename(title: Optional[str], ext: str, literature_id: uuid.UUID) -> str:
    """构建下载文件名：去除标题已含的已知后缀，清理非法字符，附加真实扩展名。"""
    raw = title or str(literature_id)
    raw_lower = raw.lower()
    for known in ALLOWED_EXTS:
        if raw_lower.endswith(known):
            raw = raw[: -len(known)]
            break
    safe = "".join(c for c in raw if c not in r'\/:*?"<>|').strip() or str(literature_id)
    return quote(f"{safe}{ext}")


@router.post("/literatures/upload", response_model=ApiResponse)
async def upload(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    doi: Optional[str] = Form(None),
    province: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    # 按扩展名白名单校验（支持 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML）
    ext = Path(file.filename or "").suffix.lower() if file.filename else ""
    logger.info(
        f"[上传] 收到文件: filename={file.filename}, ext={ext or '(未知)'}, "
        f"title={title or '(无)'}, doi={doi or '(无)'}, province={province or '(无)'}"
    )
    if ext not in ALLOWED_EXTS:
        logger.warning(f"[上传] 格式被拒绝: filename={file.filename}, ext={ext}")
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext or '未知'}，支持 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML",
        )

    file_bytes = await file.read()
    file_size = len(file_bytes)
    logger.info(f"[上传] 读取完成: filename={file.filename}, size={file_size} bytes")
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
        logger.warning(f"[上传] 文件超限: filename={file.filename}, size={file_size}, limit={settings.MAX_UPLOAD_SIZE}")
        raise HTTPException(status_code=400, detail="文件大小超过限制")

    try:
        literature, _action = await upload_literature(db, file_bytes, file.filename, title, doi, province)
    except Exception as e:
        logger.error(f"[上传] upload_literature 抛出异常: filename={file.filename}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)[:200]}")

    if literature is None:
        logger.error(f"[上传] upload_literature 返回 None: filename={file.filename}")
        raise HTTPException(status_code=500, detail="文件上传失败")

    logger.info(f"[上传] 成功: id={literature.id}, title={literature.title}, path={literature.file_path}")
    return ApiResponse(
        message="上传成功",
        data=LiteratureResponse.model_validate(literature).model_dump(),
    )


@router.post("/literatures/from-url", response_model=ApiResponse)
async def create_from_url(
    url: str = Form(..., description="要抓取的网页 URL"),
    title: Optional[str] = Form(None, description="文献标题（留空则从 HTML <title> 自动提取）"),
    province: Optional[str] = Form(None, description="关联省份"),
    db: AsyncSession = Depends(get_db),
):
    """从 URL 抓取 HTML 内容并创建文献记录。

    自动提取页面标题（如未提供），保存为 .html 文件，
    后续可通过 AI 提取功能从 HTML 文本中提取数据点。
    """
    logger.info(f"[URL 导入] 收到请求: url={url}, title={title or '(自动提取)'}, province={province or '(无)'}")

    if not url.startswith(("http://", "https://")):
        logger.warning(f"[URL 导入] URL 格式无效: {url}")
        raise HTTPException(status_code=400, detail="URL 必须以 http:// 或 https:// 开头")

    try:
        content = await fetch_url(url)
        logger.info(f"[URL 导入] 抓取成功: {len(content)} 字节")
    except Exception as e:
        logger.error(f"[URL 导入] 抓取失败: {url} - {e}")
        raise HTTPException(status_code=400, detail=f"URL 抓取失败: {str(e)[:200]}")

    # 自动提取标题
    lit_title = title
    if not lit_title:
        lit_title = guess_title_from_html(content) or url
        logger.info(f"[URL 导入] 自动提取标题: {lit_title[:80]}{'...' if len(lit_title) > 80 else ''}")

    # 从 URL 中提取域名作为文件名
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc or "webpage"
    filename = f"{domain}.html"
    logger.info(f"[URL 导入] 准备保存: filename={filename}, title={lit_title[:80]}{'...' if len(lit_title) > 80 else ''}")

    literature, _action = await upload_literature(db, content, filename, lit_title, province=province)
    if literature is None:
        logger.error(f"[URL 导入] 创建文献记录失败: {url}")
        raise HTTPException(status_code=500, detail="创建文献失败")

    logger.info(f"[URL 导入] 成功创建文献: id={literature.id}, title={literature.title}")
    return ApiResponse(
        message="URL 导入成功",
        data=LiteratureResponse.model_validate(literature).model_dump(),
    )


@router.get("/literatures", response_model=PagedResponse)
async def list_literatures(
    keyword: Optional[str] = Query(None, description="标题/作者/期刊关键词搜索"),
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    journal: Optional[str] = Query(None, description="期刊名称"),
    sort_by: Optional[str] = Query(None, description="排序字段: title, authors, journal, year, province, created, status"),
    sort_order: Optional[str] = Query(None, description="排序方向: asc, desc"),
    review_status: Optional[str] = Query(None, description="审核状态: none, pending, partial, approved"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_literature(
        db, keyword, disease, province, year_start, year_end, journal, sort_by, sort_order, review_status, page, page_size
    )

    def _derive_file_format(lit) -> Optional[str]:
        """根据 file_path / title / source_db 推导文献文件格式，大写后缀，None 表示无本地文件。"""
        path = getattr(lit, "file_path", None) or ""
        if path:
            low = path.lower()
            # query string 带 ?att=xxx 情况（from-URL 存的是网页 URL）
            if low.startswith("http://") or low.startswith("https://"):
                if ".pdf" in low:
                    return "PDF"
                if ".caj" in low:
                    return "CAJ"
                if ".epub" in low:
                    return "EPUB"
                if ".docx" in low:
                    return "DOCX"
                if ".pptx" in low:
                    return "PPTX"
                if ".xlsx" in low:
                    return "XLSX"
                # URL 不带后缀，默认是 HTML (网页) 来源
                if low.endswith(".html") or low.endswith(".htm"):
                    return "HTML"
                return "URL"
            # 本地文件路径：按扩展名
            ext = low.rsplit(".", 1)[-1] if "." in low else ""
            ext = ext.split("?", 1)[0]
            if ext in {"pdf", "caj", "epub", "docx", "pptx", "xlsx", "txt", "html", "htm"}:
                return ext.upper() if ext != "htm" else "HTML"
        # 没有本地文件：根据 source_db 判断是否是纯元数据（PubMed/CNKI等）
        if getattr(lit, "source_db", None):
            return None
        return None

    serialized = []
    for item in items:
        data = LiteratureResponse.model_validate(item).model_dump()
        data["file_format"] = _derive_file_format(item)
        serialized.append(data)

    return PagedResponse(
        items=serialized,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/literatures/export")
async def export_literatures(
    keyword: Optional[str] = Query(None, description="标题/作者/期刊关键词搜索"),
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    journal: Optional[str] = Query(None, description="期刊名称"),
    review_status: Optional[str] = Query(None, description="审核状态: none, pending, partial, approved"),
    format: str = Query("csv", description="导出格式: csv, xlsx, json"),
    include_data_points: bool = Query(False, description="是否包含数据点（JSON/Excel有效）"),
    literature_ids: Optional[str] = Query(None, description="逗号分隔的文献ID列表，指定时仅导出这些文献"),
    db: AsyncSession = Depends(get_db),
):
    """导出文献列表，支持 CSV / Excel / JSON 格式，可选包含数据点

    当 literature_ids 参数提供时，仅导出指定的文献及其数据点（忽略筛选条件）。
    """
    if literature_ids:
        # 按指定 ID 查询
        ids = [uuid.UUID(s.strip()) for s in literature_ids.split(",") if s.strip()]
        result = await db.execute(
            select(Literature).where(Literature.id.in_(ids))
        )
        items = list(result.scalars().all())
    else:
        items, _ = await list_literature(
            db, keyword, disease, province, year_start, year_end, journal,
            sort_by=None, sort_order=None, review_status=review_status,
            page=1, page_size=10000,
        )

    # ── CSV 格式（仅文献元信息）──
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "标题", "英文标题", "作者", "期刊", "出版年份", "DOI", "PMID",
            "省份", "提取状态", "审核通过数", "数据点总数", "创建时间",
        ])
        for lit in items:
            writer.writerow([
                lit.title, lit.title_en, lit.authors, lit.journal, lit.pub_year,
                lit.doi, lit.pmid, lit.province, lit.extraction_status,
                lit.approved_count, lit.extracted_count, lit.created_at,
            ])

        return Response(
            content=output.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename*=UTF-8''literatures.csv"},
        )

    # ── JSON 格式（可含数据点，用于 round-trip 导入）──
    if format == "json":
        # 如果需要数据点，批量查询
        dp_map: dict[str, list] = {}
        if include_data_points:
            lit_ids = [lit.id for lit in items]
            if lit_ids:
                dp_result = await db.execute(
                    select(DataPoint).where(DataPoint.literature_id.in_(lit_ids))
                    .order_by(DataPoint.created_at)
                )
                for dp in dp_result.scalars().all():
                    dp_map.setdefault(str(dp.literature_id), []).append({
                        "disease": dp.disease,
                        "region": dp.region,
                        "province": dp.province,
                        "city": dp.city,
                        "latitude": float(dp.latitude) if dp.latitude else None,
                        "longitude": float(dp.longitude) if dp.longitude else None,
                        "age_group": dp.age_group,
                        "age_min": dp.age_min,
                        "age_max": dp.age_max,
                        "sample_size": dp.sample_size,
                        "data_type": dp.data_type,
                        "value": float(dp.value) if dp.value is not None else None,
                        "unit": dp.unit,
                        "ci_lower": float(dp.ci_lower) if dp.ci_lower else None,
                        "ci_upper": float(dp.ci_upper) if dp.ci_upper else None,
                        "method": dp.method,
                        "assay": dp.assay,
                        "population": dp.population,
                        "collection_year": dp.collection_year,
                        "source_page": dp.source_page,
                        "source_context": dp.source_context,
                        "source_char_start": dp.source_char_start,
                        "source_char_end": dp.source_char_end,
                        "is_grounded": bool(dp.is_grounded) if dp.is_grounded else False,
                        "estimate_type": dp.estimate_type or "primary",
                        "confidence": dp.confidence or "medium",
                        "review_status": dp.review_status or "pending",
                    })

        literatures_json = []
        for lit in items:
            entry = {
                "title": lit.title,
                "title_en": lit.title_en,
                "authors": lit.authors,
                "journal": lit.journal,
                "pub_year": lit.pub_year,
                "doi": lit.doi,
                "pmid": lit.pmid,
                "abstract": lit.abstract,
                "keywords": lit.keywords if lit.keywords else [],
                "region": lit.region,
                "province": lit.province,
                "publication_types": lit.publication_types if lit.publication_types else [],
                "source_db": lit.source_db,
                "extraction_status": lit.extraction_status or "pending",
                "extracted_count": lit.extracted_count or 0,
                "approved_count": lit.approved_count or 0,
            }
            if include_data_points:
                entry["data_points"] = dp_map.get(str(lit.id), [])
            literatures_json.append(entry)

        export_data = {
            "export_version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "include_data_points": include_data_points,
            "literature_count": len(literatures_json),
            "data_point_count": sum(len(dps) for dps in dp_map.values()) if include_data_points else 0,
            "literatures": literatures_json,
        }

        content = json.dumps(export_data, ensure_ascii=False, indent=2, default=str)
        return Response(
            content=content.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename*=UTF-8''literatures_export.json"},
        )

    # ── Excel 格式（两个 sheet：文献 + 数据点）──
    if format == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()

        # Sheet 1: 文献列表
        ws1 = wb.active
        ws1.title = "文献列表"
        ws1.append([
            "标题", "英文标题", "作者", "期刊", "出版年份", "DOI", "PMID",
            "省份", "提取状态", "审核通过数", "数据点总数", "创建时间",
        ])
        for lit in items:
            ws1.append([
                lit.title, lit.title_en, lit.authors, lit.journal, lit.pub_year,
                lit.doi, lit.pmid, lit.province, lit.extraction_status,
                lit.approved_count, lit.extracted_count,
                lit.created_at.strftime("%Y-%m-%d %H:%M") if lit.created_at else "",
            ])

        # Sheet 2: 数据点（如果请求包含）
        if include_data_points:
            ws2 = wb.create_sheet("数据点")
            ws2.append([
                "文献标题", "疾病", "省份", "城市", "数据类型", "数值", "单位",
                "CI下限", "CI上限", "样本量", "年龄下限", "年龄上限", "采集年份",
                "人群", "检测方法", "assay", "置信度", "审核状态", "估计类型",
            ])
            lit_ids = [lit.id for lit in items]
            if lit_ids:
                dp_result = await db.execute(
                    select(DataPoint).where(DataPoint.literature_id.in_(lit_ids))
                    .order_by(DataPoint.created_at)
                )
                # 构建标题查找表
                title_map = {str(lit.id): lit.title for lit in items}
                for dp in dp_result.scalars().all():
                    ws2.append([
                        title_map.get(str(dp.literature_id), ""),
                        dp.disease, dp.province, dp.city, dp.data_type,
                        float(dp.value) if dp.value is not None else None,
                        dp.unit,
                        float(dp.ci_lower) if dp.ci_lower else None,
                        float(dp.ci_upper) if dp.ci_upper else None,
                        dp.sample_size, dp.age_min, dp.age_max,
                        dp.collection_year, dp.population, dp.method, dp.assay,
                        dp.confidence, dp.review_status, dp.estimate_type,
                    ])

        output = io.BytesIO()
        wb.save(output)
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename*=UTF-8''literatures_export.xlsx"},
        )

    raise HTTPException(status_code=400, detail=f"不支持的导出格式: {format}")


@router.post("/literatures/import", response_model=ApiResponse)
async def import_literatures(
    file: UploadFile = File(..., description="导入文件（JSON 格式）"),
    skip_duplicates: bool = Form(True, description="跳过重复文献"),
    db: AsyncSession = Depends(get_db),
):
    """导入文献及数据点（从 JSON 导出文件）

    支持从 export?format=json&include_data_points=true 导出的 JSON 文件导入。
    会自动检测重复文献（按 DOI/标题匹配），可选择跳过或创建。
    导入的文献和数据点会保留原有的审核状态，确保在地图、分析等模块正常展示。
    """
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="请上传 JSON 格式的导入文件")

    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件读取失败: {e}")

    literatures = data.get("literatures", [])
    if not literatures:
        raise HTTPException(status_code=400, detail="文件中未找到文献数据")

    imported_count = 0
    skipped_count = 0
    dp_imported_count = 0
    errors: list[dict] = []
    imported_titles: list[str] = []

    for idx, lit_data in enumerate(literatures):
        try:
            title = lit_data.get("title", "").strip()
            if not title:
                errors.append({"index": idx, "reason": "标题为空"})
                continue

            doi = lit_data.get("doi") or None
            if doi:
                doi = doi.strip() or None

            # 重复检测
            existing = None
            if doi:
                result = await db.execute(
                    select(Literature).where(Literature.doi == doi)
                )
                existing = result.scalar_one_or_none()

            if not existing:
                result = await db.execute(
                    select(Literature).where(Literature.title == title)
                )
                existing = result.scalar_one_or_none()

            if existing:
                if skip_duplicates:
                    skipped_count += 1
                    logger.info(f"[Import] 跳过重复文献: title={title}")
                    continue
                # 不跳过则更新已有记录的元数据
                existing.pub_year = lit_data.get("pub_year") or existing.pub_year
                existing.province = lit_data.get("province") or existing.province
                existing.journal = lit_data.get("journal") or existing.journal
                existing.authors = lit_data.get("authors") or existing.authors
                existing.abstract = lit_data.get("abstract") or existing.abstract
                existing.extraction_status = lit_data.get("extraction_status") or existing.extraction_status
                existing.extracted_count = lit_data.get("extracted_count") or existing.extracted_count
                existing.approved_count = lit_data.get("approved_count") or existing.approved_count
                existing.updated_at = datetime.now(timezone.utc)
                await db.flush()
                lit_id = existing.id
                imported_count += 1
                imported_titles.append(title)
            else:
                # 创建新文献记录
                literature = Literature(
                    title=title,
                    title_en=lit_data.get("title_en"),
                    authors=lit_data.get("authors"),
                    journal=lit_data.get("journal"),
                    pub_year=lit_data.get("pub_year"),
                    doi=doi,
                    pmid=lit_data.get("pmid"),
                    abstract=lit_data.get("abstract"),
                    keywords=lit_data.get("keywords") if lit_data.get("keywords") else None,
                    region=lit_data.get("region"),
                    province=lit_data.get("province"),
                    publication_types=lit_data.get("publication_types") if lit_data.get("publication_types") else None,
                    source_db=lit_data.get("source_db") or "import",
                    file_path=None,
                    extraction_status=lit_data.get("extraction_status") or "done",
                    extracted_count=lit_data.get("extracted_count") or 0,
                    approved_count=lit_data.get("approved_count") or 0,
                )
                db.add(literature)
                await db.flush()
                lit_id = literature.id
                imported_count += 1
                imported_titles.append(title)

            # 导入数据点
            data_points = lit_data.get("data_points", [])
            for dp_data in data_points:
                dp = DataPoint(
                    literature_id=lit_id,
                    disease=dp_data.get("disease"),
                    region=dp_data.get("region"),
                    province=dp_data.get("province"),
                    city=dp_data.get("city"),
                    latitude=dp_data.get("latitude"),
                    longitude=dp_data.get("longitude"),
                    age_group=dp_data.get("age_group"),
                    age_min=dp_data.get("age_min"),
                    age_max=dp_data.get("age_max"),
                    sample_size=dp_data.get("sample_size"),
                    data_type=dp_data.get("data_type"),
                    value=dp_data.get("value"),
                    unit=dp_data.get("unit"),
                    ci_lower=dp_data.get("ci_lower"),
                    ci_upper=dp_data.get("ci_upper"),
                    method=dp_data.get("method"),
                    assay=dp_data.get("assay"),
                    population=dp_data.get("population"),
                    collection_year=dp_data.get("collection_year"),
                    source_page=dp_data.get("source_page"),
                    source_context=dp_data.get("source_context"),
                    source_char_start=dp_data.get("source_char_start"),
                    source_char_end=dp_data.get("source_char_end"),
                    is_grounded=dp_data.get("is_grounded", False),
                    estimate_type=dp_data.get("estimate_type") or "primary",
                    confidence=dp_data.get("confidence") or "medium",
                    review_status=dp_data.get("review_status") or "pending",
                )
                db.add(dp)
                dp_imported_count += 1

            await db.flush()

        except Exception as e:
            logger.error(f"[Import] 导入第 {idx} 条文献失败: {e}", exc_info=True)
            errors.append({"index": idx, "title": lit_data.get("title", ""), "reason": str(e)[:200]})
            await db.rollback()

    await db.commit()

    logger.info(
        f"[Import] 导入完成: 文献 {imported_count} 篇, 跳过 {skipped_count} 篇, "
        f"数据点 {dp_imported_count} 个, 失败 {len(errors)} 条"
    )

    return ApiResponse(
        message=f"导入完成：成功 {imported_count} 篇文献，{dp_imported_count} 个数据点，跳过 {skipped_count} 篇重复",
        data={
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "data_point_count": dp_imported_count,
            "error_count": len(errors),
            "errors": errors[:20],
            "imported_titles": imported_titles[:20],
        },
    )


@router.post("/literatures/batch-import-from-folder", response_model=ApiResponse)
async def batch_import_from_folder(
    folder_path: str = Form(..., description="服务器上的文件夹路径，包含要导入的 PDF 等文件"),
    trigger_extraction_after: bool = Form(True, description="新导入的文献是否自动触发 AI 提取"),
    db: AsyncSession = Depends(get_db),
):
    """从服务器本地文件夹批量导入文件，自动匹配已有文献或新建文献记录。

    - 匹配策略：按文件名清洗后精确/模糊匹配已有文献标题
    - 已存在且无文件的文献 → 关联文件（不新建）
    - 已存在且有文件的文献 → 跳过
    - 不存在的文献 → 新建记录 + 可选 AI 提取
    """
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"文件夹不存在: {folder_path}")

    # 收集所有支持的文件
    supported_exts = {".pdf", ".caj", ".doc", ".docx", ".txt", ".epub", ".pptx", ".xlsx", ".ps", ".wps", ".md"}
    all_files = [f for f in sorted(folder.iterdir()) if f.is_file() and f.suffix.lower() in supported_exts]
    if not all_files:
        raise HTTPException(status_code=400, detail=f"文件夹中未找到支持的文件类型（{', '.join(sorted(supported_exts))}）")

    logger.info(f"[batch-import] 开始批量导入: folder={folder_path}, total={len(all_files)} files")

    matched = 0       # 匹配到已有文献且关联文件
    imported = 0      # 新建文献记录
    skipped = 0       # 已有文献且已有文件
    failed = 0        # 导入失败
    extraction_triggered = 0
    details: list[dict] = []

    for file_path in all_files:
        filename = file_path.name
        try:
            file_bytes = file_path.read_bytes()
        except Exception as e:
            logger.error(f"[batch-import] 读取文件失败: {filename}, error={e}")
            failed += 1
            details.append({"filename": filename, "status": "read_error", "error": str(e)})
            continue

        # 判断是否已匹配——先查标题
        clean_title = _clean_filename_title(filename)

        # 查询已有文献（返回 tuple: (Literature, action)）
        try:
            lit, action = await upload_literature(db, file_bytes, filename)
        except Exception as e:
            logger.error(f"[batch-import] 导入出错: {filename}, error={e}", exc_info=True)
            failed += 1
            details.append({"filename": filename, "status": "import_error", "error": str(e)[:200]})
            continue

        if lit is None:
            failed += 1
            details.append({"filename": filename, "status": "import_failed", "reason": "upload_literature 返回 None"})
            continue

        # 根据 action 判断处理结果
        if action == "new":
            imported += 1
            details.append({
                "filename": filename, "status": "imported", "literature_id": str(lit.id),
                "title": lit.title,
            })
            if trigger_extraction_after:
                try:
                    await trigger_extraction(db, lit.id)
                    extraction_triggered += 1
                except Exception as e:
                    logger.warning(f"[batch-import] 触发提取失败: id={lit.id}, error={e}")
        elif action == "matched":
            matched += 1
            details.append({
                "filename": filename, "status": "matched", "literature_id": str(lit.id),
                "title": lit.title,
            })
        elif action == "skipped":
            skipped += 1
            details.append({
                "filename": filename, "status": "skipped_has_file", "literature_id": str(lit.id),
                "title": lit.title,
            })
        else:
            failed += 1
            details.append({
                "filename": filename, "status": "unknown", "literature_id": str(lit.id),
                "error": f"未知 action: {action}",
            })

    await db.commit()

    parts = []
    if matched:
        parts.append(f"关联 {matched} 篇")
    if imported:
        parts.append(f"新建 {imported} 篇")
    if skipped:
        parts.append(f"跳过 {skipped} 篇（已有文件）")
    if failed:
        parts.append(f"失败 {failed} 个")
    message = "批量导入完成：" + "，".join(parts)
    if extraction_triggered:
        message += f"，已触发 {extraction_triggered} 篇 AI 提取"

    logger.info(f"[batch-import] {message}")

    return ApiResponse(
        message=message,
        data={
            "matched": matched,
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "extraction_triggered": extraction_triggered,
            "total": len(all_files),
            "details": details[:100],
        },
    )


@router.post("/literatures/batch-upload-files", response_model=ApiResponse)
async def batch_upload_files(
    files: list[UploadFile] = File(..., description="从浏览器上传的文件列表"),
    trigger_extraction_after: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """从浏览器上传文件批量导入，自动匹配已有文献或新建文献记录。

    与 batch_import_from_folder 逻辑相同，但文件从浏览器上传而非服务器本地路径。
    """
    all_files = [f for f in files if f.filename]
    supported_exts = {".pdf", ".caj", ".doc", ".docx", ".txt", ".epub", ".pptx", ".xlsx", ".ps", ".wps", ".md"}
    valid_files = [f for f in all_files if Path(f.filename or "").suffix.lower() in supported_exts]
    if not valid_files:
        raise HTTPException(status_code=400, detail="未找到支持的文件类型")

    logger.info(f"[batch-upload-files] 开始批量上传: total_received={len(all_files)}, valid={len(valid_files)}")

    matched = 0
    imported = 0
    skipped = 0
    failed = 0
    extraction_triggered = 0
    details: list[dict] = []

    for file in valid_files:
        filename = file.filename or "unknown"
        try:
            file_bytes = await file.read()
        except Exception as e:
            logger.error(f"[batch-upload-files] 读取文件失败: {filename}, error={e}")
            failed += 1
            details.append({"filename": filename, "status": "read_error", "error": str(e)})
            continue

        if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
            logger.warning(f"[batch-upload-files] 文件超限: {filename}, size={len(file_bytes)}")
            failed += 1
            details.append({"filename": filename, "status": "file_too_large", "error": f"文件超过大小限制"})
            continue

        try:
            lit, action = await upload_literature(db, file_bytes, filename)
        except Exception as e:
            logger.error(f"[batch-upload-files] 导入出错: {filename}, error={e}", exc_info=True)
            failed += 1
            details.append({"filename": filename, "status": "import_error", "error": str(e)[:200]})
            continue

        if lit is None:
            failed += 1
            details.append({"filename": filename, "status": "import_failed", "reason": "upload_literature 返回 None"})
            continue

        if action == "new":
            imported += 1
            details.append({
                "filename": filename, "status": "imported", "literature_id": str(lit.id),
                "title": lit.title,
            })
            if trigger_extraction_after:
                try:
                    await trigger_extraction(db, lit.id)
                    extraction_triggered += 1
                except Exception as e:
                    logger.warning(f"[batch-upload-files] 触发提取失败: id={lit.id}, error={e}")
        elif action == "matched":
            matched += 1
            details.append({
                "filename": filename, "status": "matched", "literature_id": str(lit.id),
                "title": lit.title,
            })
        elif action == "skipped":
            skipped += 1
            details.append({
                "filename": filename, "status": "skipped_has_file", "literature_id": str(lit.id),
                "title": lit.title,
            })
        else:
            failed += 1
            details.append({
                "filename": filename, "status": "unknown", "literature_id": str(lit.id),
                "error": f"未知 action: {action}",
            })

    await db.commit()

    parts = []
    if matched:
        parts.append(f"关联 {matched} 篇")
    if imported:
        parts.append(f"新建 {imported} 篇")
    if skipped:
        parts.append(f"跳过 {skipped} 篇（已有文件）")
    if failed:
        parts.append(f"失败 {failed} 个")
    message = "批量导入完成：" + "，".join(parts)
    if extraction_triggered:
        message += f"，已触发 {extraction_triggered} 篇 AI 提取"

    logger.info(f"[batch-upload-files] {message}")

    return ApiResponse(
        message=message,
        data={
            "matched": matched,
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "extraction_triggered": extraction_triggered,
            "total": len(valid_files),
            "details": details[:100],
        },
    )


@router.get("/literatures/{literature_id}", response_model=ApiResponse)
async def get_one(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    return ApiResponse(data=LiteratureResponse.model_validate(literature).model_dump())


@router.put("/literatures/{literature_id}", response_model=ApiResponse)
async def update(
    literature_id: uuid.UUID,
    data: LiteratureUpdate,
    db: AsyncSession = Depends(get_db),
):
    literature = await update_literature(db, literature_id, data.model_dump(exclude_unset=True))
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")
    return ApiResponse(message="更新成功", data=LiteratureResponse.model_validate(literature).model_dump())


@router.post("/literatures/{literature_id}/file", response_model=ApiResponse)
async def upload_file(
    literature_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """为已有文献关联上传文件（替换原有文件）。"""
    ext = Path(file.filename or "").suffix.lower() if file.filename else ""
    logger.info(f"[关联文件] 收到文件: literature_id={literature_id}, filename={file.filename}, ext={ext or '(未知)'}")
    if ext not in ALLOWED_EXTS:
        logger.warning(f"[关联文件] 格式被拒绝: filename={file.filename}, ext={ext}")
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext or '未知'}，支持 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML",
        )

    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
        logger.warning(f"[关联文件] 文件超限: filename={file.filename}, size={len(file_bytes)}, limit={settings.MAX_UPLOAD_SIZE}")
        raise HTTPException(status_code=400, detail="文件大小超过限制")

    try:
        literature = await upload_literature_file(db, literature_id, file_bytes, file.filename)
    except Exception as e:
        logger.error(f"[关联文件] upload_literature_file 抛出异常: id={literature_id}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件关联失败: {str(e)[:200]}")

    if literature is None:
        raise HTTPException(status_code=404, detail="文献不存在")

    logger.info(f"[关联文件] 成功: id={literature.id}, path={literature.file_path}")
    return ApiResponse(
        message="文件关联成功",
        data=LiteratureResponse.model_validate(literature).model_dump(),
    )


@router.delete("/literatures/{literature_id}", response_model=ApiResponse)
async def delete(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    success = await delete_literature(db, literature_id)
    if not success:
        raise HTTPException(status_code=404, detail="文献不存在")
    return ApiResponse(message="删除成功")


@router.get("/literatures/{literature_id}/file")
async def get_pdf_file(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """返回文件流供前端预览（仅 PDF 支持浏览器内预览，其余格式前端会禁用预览按钮）"""
    logger.info(f"[预览] 请求文件: literature_id={literature_id}")
    literature = await get_literature(db, literature_id)
    if not literature:
        logger.warning(f"[预览] 文献不存在: id={literature_id}")
        raise HTTPException(status_code=404, detail="文献不存在")

    file_path = Path(literature.file_path) if literature.file_path else None
    if not file_path or not file_path.exists():
        logger.error(f"[预览] 文件在磁盘上不存在: id={literature_id}, path={file_path}")
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = file_path.suffix.lower()
    safe_filename = _build_safe_filename(literature.title, ext, literature_id)
    mime_type = get_mime_type(ext)
    logger.info(f"[预览] 返回文件流: id={literature_id}, ext={ext}, mime={mime_type}, size={file_path.stat().st_size} bytes")
    return FileResponse(
        path=str(file_path),
        media_type=mime_type,
        filename=safe_filename,
        content_disposition_type="inline",
    )


@router.get("/literatures/{literature_id}/download")
async def download_pdf_file(
    literature_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """下载文件（attachment 模式，触发浏览器下载，用本地阅读器打开）"""
    logger.info(f"[下载] 请求下载: literature_id={literature_id}")
    literature = await get_literature(db, literature_id)
    if not literature:
        logger.warning(f"[下载] 文献不存在: id={literature_id}")
        raise HTTPException(status_code=404, detail="文献不存在")

    file_path = Path(literature.file_path) if literature.file_path else None
    if not file_path or not file_path.exists():
        logger.error(f"[下载] 文件在磁盘上不存在: id={literature_id}, path={file_path}")
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = file_path.suffix.lower()
    safe_filename = _build_safe_filename(literature.title, ext, literature_id)
    mime_type = get_mime_type(ext)
    logger.info(f"[下载] 返回文件流: id={literature_id}, ext={ext}, mime={mime_type}, size={file_path.stat().st_size} bytes")
    return FileResponse(
        path=str(file_path),
        media_type=mime_type,
        filename=safe_filename,
        content_disposition_type="attachment",
    )


@router.get("/literatures/{literature_id}/source-text", response_model=ApiResponse)
async def get_source_text(
    literature_id: uuid.UUID,
    start: Optional[int] = Query(None, description="字符起始位置（0-based，含）"),
    end: Optional[int] = Query(None, description="字符结束位置（0-based，不含）"),
    context: int = Query(200, description="前后扩展的上下文字符数", ge=0, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """P2：返回文献的提取文本，支持按字符区间截取（供溯源查看高亮使用）"""
    literature = await get_literature(db, literature_id)
    if not literature:
        raise HTTPException(status_code=404, detail="文献不存在")

    # 优先读取缓存的 clean_text 文件
    text_path = Path("data/pdfs") / f"{literature_id}.txt"
    if not text_path.exists():
        raise HTTPException(status_code=404, detail="溯源文本未缓存，请重新提取该文献")

    try:
        full_text = text_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取溯源文本失败: {e}")

    total_len = len(full_text)

    # 如果指定了区间，截取并扩展上下文
    if start is not None and end is not None:
        s = max(0, start - context)
        e = min(total_len, end + context)
        snippet = full_text[s:e]
        return ApiResponse(data={
            "full_text": None,
            "snippet": snippet,
            "snippet_start": s,
            "snippet_end": e,
            "highlight_start": start,
            "highlight_end": min(end, total_len),
            "total_length": total_len,
        })

    # 未指定区间，返回全文（大文本时前端自行处理）
    # 限制最大返回 50000 字符，避免响应过大
    if total_len > 50000:
        return ApiResponse(data={
            "full_text": full_text[:50000],
            "snippet": None,
            "total_length": total_len,
            "truncated": True,
        })

    return ApiResponse(data={
        "full_text": full_text,
        "snippet": None,
        "total_length": total_len,
        "truncated": False,
    })


# ===== 查重与合并 API =====

@router.post("/literatures/check-duplicate", response_model=ApiResponse)
async def check_duplicate(
    req: CheckDuplicateRequest,
    db: AsyncSession = Depends(get_db),
):
    """检查重复文献（按文献ID或字段）"""
    try:
        result = await check_duplicates(
            db, req.literature_id,
            title=req.title, doi=req.doi, authors=req.authors, pdf_hash=req.pdf_hash,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ApiResponse(data={
        "literature_id": result["literature_id"],
        "total": result["total"],
        "duplicates": [
            {
                "literature": LiteratureResponse.model_validate(d["literature"]).model_dump(),
                "match_reasons": d["match_reasons"],
                "match_values": d["match_values"],
            }
            for d in result["duplicates"]
        ],
    })


@router.post("/literatures/scan-duplicates", response_model=ApiResponse)
async def scan_duplicates_endpoint(
    db: AsyncSession = Depends(get_db),
):
    """全库扫描重复文献"""
    result = await scan_duplicates(db)
    # 将 UUID 转为字符串以便 JSON 序列化
    serializable_groups = []
    for g in result["groups"]:
        serializable_groups.append({
            "literature_ids": [str(uid) for uid in g["literature_ids"]],
            "match_reasons": g["match_reasons"],
            "representative_id": str(g["representative_id"]),
        })
    return ApiResponse(data={
        "groups": serializable_groups,
        "total_groups": result["total_groups"],
        "total_duplicates": result["total_duplicates"],
    })


@router.post("/literatures/merge/preview", response_model=ApiResponse)
async def merge_preview(
    req: MergePreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """预览合并：字段对比 + 数据点冲突检测"""
    try:
        result = await preview_merge(db, req.source_id, req.target_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ApiResponse(data=result)


@router.post("/literatures/merge", response_model=ApiResponse)
async def merge(
    req: MergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """执行合并：将 source 合并进 target，删除 source"""
    try:
        result = await merge_literatures(
            db, req.source_id, req.target_id,
            req.field_choices,
            req.dp_conflict_strategy,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(
        message="合并成功",
        data={
            "merged_literature": LiteratureResponse.model_validate(result["merged_literature"]).model_dump(),
            "moved_data_points": result["moved_data_points"],
            "deleted_conflict_data_points": result["deleted_conflict_data_points"],
            "deleted_source_id": result["deleted_source_id"],
        },
    )

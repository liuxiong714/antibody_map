import contextlib
import csv
import io
import json
import os
import re
import subprocess  # 打开宿主机文件夹使用
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.document_parser import get_mime_type
from app.core.minio_client import upload_file
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.schemas.literature import LiteratureCreate
from app.services.literature._common import (
    LOCAL_STORAGE_DIR,
    _clean_filename_title,
    _find_existing_by_title,
    compute_pdf_hash,
    logger,
)
from app.services.literature.crud import (
    create_literature,
    get_literature,
    list_literature,
)
from app.services.reference_parser import parse_references


async def upload_literature(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
    title: str | None = None,
    doi: str | None = None,
    province: str | None = None,
    owner_id: uuid.UUID | None = None,
) -> tuple[Literature | None, str]:
    """上传/导入文献文件。

    返回值: (Literature 对象 or None, 状态标记)
        - "new": 新建文献记录
        - "matched": 匹配到已有文献并关联文件
        - "skipped": 匹配到已有文献且已有文件，跳过
        - "error": 处理失败
    """
    logger.info(f"[upload_literature] 开始: filename={filename}, size={len(file_bytes)} bytes, title={title or '(无)'}")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"
    logger.info(f"[upload_literature] 解析扩展名: ext={ext}")

    # 1. 提取干净标题，查找是否已存在该标题的文献
    clean_title = title or _clean_filename_title(filename)
    existing = await _find_existing_by_title(db, clean_title)
    if existing:
        if existing.has_fulltext:
            logger.info(f"[upload_literature] 文献已存在且已有文件: id={existing.id}, title={existing.title}，跳过导入")
            return existing, "skipped"
        else:
            logger.info(f"[upload_literature] 找到已存在文献（无文件）: id={existing.id}, title={existing.title}，关联文件")
            # 保存文件，直接关联到已有文献
            lit = await _save_and_associate(db, existing, file_bytes, filename, ext, doi, province, clean_title)
            return lit, "matched"

    # 2. 始终保存到本地文件系统（确保提取时能找到文件）
    LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    local_filename = f"{uuid.uuid4()}.{ext}"
    local_path = LOCAL_STORAGE_DIR / local_filename
    try:
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"[upload_literature] 本地保存成功: path={local_path}")
    except Exception as e:
        logger.error(f"[upload_literature] 本地保存失败: path={local_path}, error={e}", exc_info=True)
        return None

    # 3. 尝试上传到 MinIO（仅用于分布式/备份场景，失败不阻塞）
    object_name = f"literature/{uuid.uuid4()}.{ext}"
    minio_path = upload_file(file_bytes, object_name, content_type=get_mime_type(ext))
    if minio_path is None:
        logger.warning(f"[upload_literature] MinIO 不可用，仅保存本地副本: filename={filename}")
    else:
        logger.info(f"[upload_literature] MinIO 上传成功: object_name={object_name}")

    # 4. 数据库记录使用本地路径（_download_pdf 会优先匹配本地文件）
    stored_path = str(local_path)

    # 5. 计算文件哈希用于查重
    pdf_hash = compute_pdf_hash(file_bytes)
    logger.info(f"[upload_literature] 哈希计算完成: hash={pdf_hash[:16]}..., filename={filename}")

    # 创建文献记录
    literature = Literature(
        title=clean_title,
        doi=doi,
        province=province,
        file_path=stored_path,
        pdf_hash=pdf_hash,
        has_fulltext=True,
        source_db="upload",
        owner_id=owner_id,
    )
    db.add(literature)
    try:
        await db.commit()
        await db.refresh(literature)
        logger.info(f"[upload_literature] 数据库记录创建成功: id={literature.id}, title={literature.title}")
    except Exception as e:
        logger.error(f"[upload_literature] 数据库提交失败: filename={filename}, error={e}", exc_info=True)
        # 回滚本地文件以避免脏文件残留
        try:
            os.remove(local_path)
            logger.info(f"[upload_literature] 已清理本地文件: {local_path}")
        except Exception as cleanup_err:
            logger.warning(f"[upload_literature] 清理本地文件失败: {local_path}, {cleanup_err}")
        return None, "error"
    return literature, "new"


async def _save_and_associate(
    db: AsyncSession,
    literature: Literature,
    file_bytes: bytes,
    filename: str,
    ext: str,
    doi: str | None = None,
    province: str | None = None,
    clean_title: str | None = None,
) -> Literature:
    """保存文件并关联到已有文献（仅替换文件，不新建记录）。"""
    # 保存文件
    LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    local_filename = f"{uuid.uuid4()}.{ext}"
    local_path = LOCAL_STORAGE_DIR / local_filename
    try:
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"[upload_literature] 关联文件保存成功: path={local_path}")
    except Exception as e:
        logger.error(f"[upload_literature] 关联文件保存失败: path={local_path}, error={e}", exc_info=True)
        return literature

    # 尝试上传 MinIO
    object_name = f"literature/{uuid.uuid4()}.{ext}"
    minio_path = upload_file(file_bytes, object_name, content_type=get_mime_type(ext))
    if minio_path is None:
        logger.warning(f"[upload_literature] 关联文件 MinIO 不可用，仅保存本地副本: filename={filename}")
    else:
        logger.info(f"[upload_literature] 关联文件 MinIO 上传成功: object_name={object_name}")

    stored_path = str(local_path)
    pdf_hash = compute_pdf_hash(file_bytes)

    # 更新已有文献的文件关联
    if clean_title and literature.title != clean_title:
        literature.title = clean_title
    literature.file_path = stored_path
    literature.pdf_hash = pdf_hash
    literature.has_fulltext = True
    if doi:
        literature.doi = doi
    if province:
        literature.province = province
    literature.updated_at = datetime.now(timezone.utc)

    try:
        await db.commit()
        await db.refresh(literature)
        logger.info(f"[upload_literature] 文献文件关联更新成功: id={literature.id}, title={literature.title}, path={stored_path}")
    except Exception as e:
        logger.error(f"[upload_literature] 关联文件数据库提交失败: id={literature.id}, error={e}", exc_info=True)
        with contextlib.suppress(Exception):
            os.remove(local_path)
    return literature


async def upload_literature_file(
    db: AsyncSession,
    literature_id: uuid.UUID,
    file_bytes: bytes,
    filename: str,
) -> Literature | None:
    """为已有文献关联上传文件（替换原有文件）。"""
    logger.info(f"[upload_literature_file] 开始: literature_id={literature_id}, filename={filename}, size={len(file_bytes)} bytes")

    literature = await get_literature(db, literature_id)
    if not literature:
        logger.warning(f"[upload_literature_file] 文献不存在: id={literature_id}")
        return None

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"

    # 1. 保存到本地文件系统
    LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    local_filename = f"{uuid.uuid4()}.{ext}"
    local_path = LOCAL_STORAGE_DIR / local_filename
    try:
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"[upload_literature_file] 本地保存成功: path={local_path}")
    except Exception as e:
        logger.error(f"[upload_literature_file] 本地保存失败: path={local_path}, error={e}", exc_info=True)
        return None

    # 2. 尝试上传到 MinIO
    object_name = f"literature/{uuid.uuid4()}.{ext}"
    minio_path = upload_file(file_bytes, object_name, content_type=get_mime_type(ext))
    if minio_path is None:
        logger.warning(f"[upload_literature_file] MinIO 不可用，仅保存本地副本: filename={filename}")
    else:
        logger.info(f"[upload_literature_file] MinIO 上传成功: object_name={object_name}")

    stored_path = str(local_path)
    pdf_hash = compute_pdf_hash(file_bytes)

    # 3. 删除旧文件（如果存在）
    if literature.file_path:
        old_path = Path(literature.file_path)
        if old_path.exists():
            try:
                os.remove(old_path)
                logger.info(f"[upload_literature_file] 已删除旧文件: {old_path}")
            except Exception as e:
                logger.warning(f"[upload_literature_file] 删除旧文件失败: {old_path}, {e}")

    # 4. 更新文献记录
    literature.file_path = stored_path
    literature.pdf_hash = pdf_hash
    literature.has_fulltext = True
    try:
        await db.commit()
        await db.refresh(literature)
        logger.info(f"[upload_literature_file] 文献文件关联成功: id={literature.id}, path={stored_path}")
    except Exception as e:
        logger.error(f"[upload_literature_file] 数据库提交失败: id={literature_id}, error={e}", exc_info=True)
        with contextlib.suppress(Exception):
            os.remove(local_path)
        return None
    return literature


async def preview_import_references(
    db: AsyncSession,
    ref_text: str,
    fmt: str = "auto",
) -> dict:
    """预览题录导入：解析文本并统计总条数、重复条数、可导入条数，不写入数据库。

    返回 {"total", "skipped", "imported"}。
    """
    text = (ref_text or "").strip()
    if not text:
        raise ValueError("题录文本为空")

    refs = parse_references(text, fmt)
    if not refs:
        raise ValueError("未解析到有效题录（支持 RIS / EndNote / PubMed / WoS / 读秀超星 格式）")

    total = len(refs)
    skipped = 0
    importable_indices: list[int] = []
    for idx, ref in enumerate(refs):
        title = (ref.get("title") or "").strip()
        if not title:
            skipped += 1
            continue
        pmid = (ref.get("pmid") or "").strip() or None
        doi = (ref.get("doi") or "").strip() or None
        source_id = pmid or doi
        existing = None
        if source_id:
            if pmid:
                r = await db.execute(select(Literature).where(Literature.pmid == pmid))
                existing = r.scalar_one_or_none()
            if not existing and doi:
                r = await db.execute(select(Literature).where(Literature.doi == doi))
                existing = r.scalar_one_or_none()
        if not existing:
            existing = await _find_existing_by_title(db, title)
        if existing:
            skipped += 1
            continue
        importable_indices.append(idx)

    imported = total - skipped
    results = {"total": total, "skipped": skipped, "imported": imported}
    # 返回可导入记录的真实行号，供前端按实际位置分批，避免重复记录散落时漏导
    results["importable_indices"] = importable_indices
    return results


async def import_references_from_text(
    db: AsyncSession,
    ref_text: str,
    fmt: str = "auto",
    start: int = 0,
    limit: int = 0,
    indices: list[int] | None = None,
) -> dict:
    """解析题录文本并入库（RIS / EndNote(.enw) / PubMed / WoS / 读秀超星）。

    - 格式自动探测（reference_parser.parse_references，fmt 显式指定可跳过探测）
    - source_db 取解析 source，source_id 取 pmid（为空则用 doi）
    - 跳过条件：标题为空；source_id（pmid，兜底 doi）或归一化标题已存在
    - 复用 create_literature 入库
    - start/limit：分批导入时指定从第几条开始处理、处理多少条（0=全部）
    - indices：精确指定要处理的解析结果行号（优先级高于 start/limit）。
       前端先在 /preview 拿到 importable_indices（真实可导入的行号），再按此分批，
       避免重复记录散落时按 count 连续切片导致漏导。
    返回 {"imported", "skipped", "total", "errors"}。
    """
    text = (ref_text or "").strip()
    if not text:
        raise ValueError("题录文本为空")

    refs = parse_references(text, fmt)
    if not refs:
        raise ValueError("未解析到有效题录（支持 RIS / EndNote / PubMed / WoS / 读秀超星 格式）")

    # 分批选择要处理的记录：indices 优先；其次 start/limit 连续切片
    if indices is not None:
        picked = [(i, refs[i]) for i in sorted(set(indices)) if 0 <= i < len(refs)]
    else:
        if limit > 0:
            picked = list(enumerate(refs[start:start + limit], start=start))
        elif start > 0:
            picked = list(enumerate(refs[start:], start=start))
        else:
            picked = list(enumerate(refs))

    imported = 0
    skipped = 0
    errors: list[dict] = []
    for idx, ref in picked:
        title = (ref.get("title") or "").strip()
        if not title:
            skipped += 1
            errors.append({"index": idx, "reason": "标题为空"})
            continue
        try:
            # 来源标识：source_id = pmid（为空则用 doi），用于查重
            pmid = (ref.get("pmid") or "").strip() or None
            doi = (ref.get("doi") or "").strip() or None
            source_id = pmid or doi
            existing = None
            if source_id:
                if pmid:
                    r = await db.execute(select(Literature).where(Literature.pmid == pmid))
                    existing = r.scalar_one_or_none()
                if not existing and doi:
                    r = await db.execute(select(Literature).where(Literature.doi == doi))
                    existing = r.scalar_one_or_none()
            if not existing:
                existing = await _find_existing_by_title(db, title)
            if existing:
                skipped += 1
                logger.info(f"[ImportReferences] 跳过重复文献: title={title}, source_id={source_id}")
                continue

            year_str = (ref.get("year") or "").strip()
            pub_year = int(year_str) if year_str.isdigit() else None
            # 关键词：分号分隔的字符串 → 列表
            kw_str = (ref.get("keywords") or "").strip()
            keywords_list = [k.strip() for k in re.split(r"[;；]", kw_str) if k.strip()] if kw_str else None
            await create_literature(
                db,
                LiteratureCreate(
                    title=title,
                    authors=(ref.get("authors") or "").strip() or None,
                    journal=(ref.get("journal") or "").strip() or None,
                    pub_year=pub_year,
                    doi=doi,
                    pmid=pmid,
                    abstract=(ref.get("abstract") or "").strip() or None,
                    keywords=keywords_list,
                    source_db=(ref.get("source") or "cnki"),
                ),
            )
            imported += 1
        except Exception as e:
            logger.error(f"[ImportReferences] 第 {idx} 条入库失败: {e}", exc_info=True)
            errors.append({"index": idx, "title": title, "reason": str(e)[:200]})

    logger.info(
        f"[ImportReferences] 导入完成: 解析 {len(refs)} 条, "
        f"导入 {imported} 条, 跳过 {skipped} 条, 失败 {len(errors)} 条"
    )
    return {
        "imported": imported,
        "skipped": skipped,
        "total": len(refs),
        "errors": errors[:20],
    }


# 批量导入支持的文件扩展名集合
_BATCH_SUPPORTED_EXTS = {".pdf", ".caj", ".doc", ".docx", ".txt", ".epub", ".pptx", ".xlsx", ".ps", ".wps", ".md"}


async def _batch_import_files_core(
    db: AsyncSession,
    entries: list[dict],
    trigger_extraction_after: bool = True,
    max_size_bytes: int | None = None,
    owner_id: uuid.UUID | None = None,
) -> dict:
    """通用批量导入核心：遍历 entries 调用 upload_literature 自动匹配/新建。

    entries: 每个元素为 {"filename": str, "bytes": bytes|None, "read_error": str|None}
      - bytes=None 且 read_error 非空 → 记为读取失败
      - max_size_bytes 给定时，超限文件记为 file_too_large
    新建文献时可选触发 AI 提取。
    返回 {"matched", "imported", "skipped", "failed", "extraction_triggered", "total", "details"}。
    """
    matched = imported = skipped = failed = extraction_triggered = 0
    details: list[dict] = []

    for entry in entries:
        filename = entry["filename"]
        file_bytes = entry.get("bytes")
        read_error = entry.get("read_error")

        if file_bytes is None:
            failed += 1
            details.append({
                "filename": filename, "status": "read_error",
                "error": read_error or "读取文件失败",
            })
            continue

        if max_size_bytes is not None and len(file_bytes) > max_size_bytes:
            failed += 1
            details.append({
                "filename": filename, "status": "file_too_large", "error": "文件超过大小限制",
            })
            continue

        # 判断是否已匹配——upload_literature 内部处理标题匹配与文件关联
        try:
            lit, action = await upload_literature(db, file_bytes, filename, owner_id=owner_id)
        except Exception as e:
            logger.error(f"[batch-import] 导入出错: {filename}, error={e}", exc_info=True)
            failed += 1
            details.append({"filename": filename, "status": "import_error", "error": str(e)[:200]})
            continue

        if lit is None:
            failed += 1
            details.append({
                "filename": filename, "status": "import_failed",
                "reason": "upload_literature 返回 None",
            })
            continue

        if action == "new":
            imported += 1
            details.append({
                "filename": filename, "status": "imported",
                "literature_id": str(lit.id), "title": lit.title,
            })
            if trigger_extraction_after:
                try:
                    from app.services.extraction_service import trigger_extraction
                    await trigger_extraction(db, lit.id)
                    extraction_triggered += 1
                except Exception as e:
                    logger.warning(f"[batch-import] 触发提取失败: id={lit.id}, error={e}")
        elif action == "matched":
            matched += 1
            details.append({
                "filename": filename, "status": "matched",
                "literature_id": str(lit.id), "title": lit.title,
            })
        elif action == "skipped":
            skipped += 1
            details.append({
                "filename": filename, "status": "skipped_has_file",
                "literature_id": str(lit.id), "title": lit.title,
            })
        else:
            failed += 1
            details.append({
                "filename": filename, "status": "unknown",
                "literature_id": str(lit.id), "error": f"未知 action: {action}",
            })

    await db.commit()
    return {
        "matched": matched,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "extraction_triggered": extraction_triggered,
        "total": len(entries),
        "details": details[:100],
    }


async def batch_import_files_from_folder(
    db: AsyncSession,
    folder_path: str,
    trigger_extraction_after: bool = True,
    owner_id: uuid.UUID | None = None,
) -> dict:
    """从服务器本地文件夹批量导入文件。

    自动匹配已有文献或新建文献记录；支持导入后自动触发 AI 提取。
    文件夹不存在 / 无支持文件时抛出异常，由调用方映射为 400。
    """
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"文件夹不存在: {folder_path}")

    all_files = [
        f for f in sorted(folder.iterdir())
        if f.is_file() and f.suffix.lower() in _BATCH_SUPPORTED_EXTS
    ]
    if not all_files:
        raise ValueError(f"文件夹中未找到支持的文件类型（{', '.join(sorted(_BATCH_SUPPORTED_EXTS))}）")

    entries: list[dict] = []
    for f in all_files:
        try:
            entries.append({"filename": f.name, "bytes": f.read_bytes()})
        except Exception as e:
            logger.error(f"[batch-import] 读取文件失败: {f.name}, error={e}")
            entries.append({"filename": f.name, "bytes": None, "read_error": str(e)})

    return await _batch_import_files_core(db, entries, trigger_extraction_after, owner_id=owner_id)


async def batch_import_uploaded_files(
    db: AsyncSession,
    files: list,
    trigger_extraction_after: bool = True,
    owner_id: uuid.UUID | None = None,
) -> dict:
    """从浏览器上传的文件批量导入（与文件夹导入共用核心逻辑，但文件来自上传）。

    files: 浏览器上传的 UploadFile 列表；仅保留扩展名受支持且带有文件名的文件。
    单文件超过 settings.MAX_UPLOAD_SIZE 记为 file_too_large。
    """
    all_files = [f for f in files if f.filename]
    valid_files = [
        f for f in all_files
        if Path(f.filename or "").suffix.lower() in _BATCH_SUPPORTED_EXTS
    ]
    if not valid_files:
        raise ValueError("未找到支持的文件类型")

    entries: list[dict] = []
    for f in valid_files:
        filename = f.filename or "unknown"
        # 读前检查 file.size 或 Content-Length，避免大文件进内存
        if f.size is not None and f.size > settings.MAX_UPLOAD_SIZE:
            logger.warning(f"[batch-upload-files] 文件超限（跳过）: {filename}, size={f.size}")
            entries.append({"filename": filename, "bytes": None, "read_error": "文件超过大小限制"})
            continue
        try:
            entries.append({"filename": filename, "bytes": await f.read()})
        except Exception as e:
            logger.error(f"[batch-upload-files] 读取文件失败: {filename}, error={e}")
            entries.append({"filename": filename, "bytes": None, "read_error": str(e)})

    return await _batch_import_files_core(
        db, entries, trigger_extraction_after, max_size_bytes=settings.MAX_UPLOAD_SIZE,
        owner_id=owner_id,
    )


# ===== JSON 导出文件导入、导出服务（从 API 路由下沉）=====

async def import_literatures_from_json(
    db: AsyncSession,
    content: bytes,
    skip_duplicates: bool = True,
) -> dict:
    """从 JSON 导出文件导入文献及数据点，自动检测重复文献。

    - 支持从 export?format=json&include_data_points=true 导出的 JSON 文件导入
    - 按 DOI/标题自动检测重复，可选择跳过或更新已有记录的元数据
    - 保留原有审核状态
    返回 {"imported_count", "skipped_count", "data_point_count", "error_count",
          "errors", "imported_titles"}。
    JSON 解析失败 / 未找到文献数据时抛 ValueError（由调用方映射为 400）。
    """
    try:
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {e}") from e
    except Exception as e:
        raise ValueError(f"文件读取失败: {e}") from e

    literatures = data.get("literatures", [])
    if not literatures:
        raise ValueError("文件中未找到文献数据")

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

    return {
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "data_point_count": dp_imported_count,
        "error_count": len(errors),
        "errors": errors[:20],
        "imported_titles": imported_titles[:20],
    }


async def build_literatures_export(
    db: AsyncSession,
    format: str,
    include_data_points: bool,
    keyword: str | None = None,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    journal: str | None = None,
    review_status: str | None = None,
    file_format: str | None = None,
    literature_ids: str | None = None,
) -> dict:
    """导出文献列表（CSV / Excel / JSON），返回字节内容与响应元信息。

    当 literature_ids 提供时，仅导出指定文献及其数据点（忽略筛选条件）。
    返回 {"content": bytes, "media_type": str, "filename": str}。
    不支持的格式抛 ValueError（由调用方映射为 400）。
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
            file_format=file_format,
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

        return {
            "content": output.getvalue().encode("utf-8-sig"),
            "media_type": "text/csv; charset=utf-8",
            "filename": "literatures.csv",
        }

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
        return {
            "content": content.encode("utf-8"),
            "media_type": "application/json; charset=utf-8",
            "filename": "literatures_export.json",
        }

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
        return {
            "content": output.getvalue(),
            "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "filename": "literatures_export.xlsx",
        }

    raise ValueError(f"不支持的导出格式: {format}")


# ===== 宿主机文件管理器辅助函数（打开所在文件夹，从 API 路由下沉）=====

def reveal_in_host_file_manager(resolved: str, folder: str) -> None:
    """在宿主机上定位并选中文件（Windows 资源管理器 / macOS Finder / WSL 间调）。

    关键点：
    - Windows 资源管理器的 `/select,<路径>` 必须作为单个参数传入（中间不能有空格），
      否则 explorer 无法正确识别并选中目标文件；此处分三段尝试，任一成功即返回。
    - 后端可能运行在 WSL(Linux) 中：此时可通过 WSL 互操作将 Linux 路径转成 Windows
      路径并调用 explorer.exe，从而在 Windows 宿主机上打开资源管理器并选中该文件。
    - 若当前环境无法打开图形文件管理器（如无头服务器），不抛出未处理异常：
      直接返回，由调用方给出文件路径提示。
    """
    if sys.platform == "win32":
        # 原生 Windows：先 explorer /select 定位选中，失败则用关联程序打开所在目录
        try:
            subprocess.Popen(
                ["explorer", f"/select,{resolved}"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        except Exception as e:  # pragma: no cover
            logger.warning(f"[打开文件夹] explorer 选中失败({e})，回退为打开目录")
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
            return
        except Exception as e:  # pragma: no cover
            logger.warning(f"[打开文件夹] os.startfile 失败({e})，按环境处理")
    elif sys.platform == "darwin":
        # macOS：在 Finder 中显示
        subprocess.Popen(["open", "-R", resolved])
        return
    else:
        # 非 Windows / macOS：可能是 WSL(Linux) 或 Linux 桌面
        win_path = _to_windows_path(resolved)
        logger.info(f"[打开文件夹] WSL分支: sys.platform={sys.platform}, uid={os.getuid()}, resolved={resolved}, win_path={win_path}")
        if win_path:
            # WSL 环境下调用 explorer.exe 打开 Windows 资源管理器并选中文件
            #
            # 关键问题1：后端可能以 root 运行（sudo uvicorn），而 WSL interop 在 root 下
            #   调用 Windows GUI 程序时无法在交互式桌面会话中显示窗口。
            #   解决：若为 root，通过 runuser 切换到 WSL 默认非 root 用户再调用。
            #
            # 关键问题2：uvicorn 进程继承的 WSL_INTEROP socket 可能来自已失效的终端会话，
            #   虽然 socket 文件仍在、explorer.exe 能启动，但窗口不会在当前桌面显示。
            #   解决：优先使用 WSL 主会话的 interop socket（/run/WSL/1_interop 或 2_interop），
            #   该 socket 始终关联当前的 Windows 交互式桌面会话。
            interop_socket = _find_active_wsl_interop()
            logger.info(f"[打开文件夹] interop_socket={interop_socket or '(继承当前)'}")

            runuser = _get_wsl_runuser_prefix()
            username = runuser[2] if runuser else None
            if username:
                cmd = ["runuser", "-u", username, "--", "explorer.exe", f"/select,{win_path}"]
                logger.info(f"[打开文件夹] root用户，使用runuser({username})调用")
            else:
                cmd = ["explorer.exe", f"/select,{win_path}"]
                logger.info("[打开文件夹] 非root用户，直接调用explorer.exe")
            try:
                env = os.environ.copy()
                if interop_socket:
                    env["WSL_INTEROP"] = interop_socket
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
                logger.info(f"[打开文件夹] explorer.exe 已启动: pid={proc.pid}")
                return
            except Exception as e:
                logger.warning(f"[打开文件夹] explorer.exe 启动失败({e})")
        try:
            subprocess.Popen(["xdg-open", folder])
            return
        except Exception as e:  # pragma: no cover
            logger.warning(f"[打开文件夹] xdg-open 失败({e})，当前环境无可用文件管理器")


def _to_windows_path(path: str) -> str | None:
    """将 Linux/WSL 路径转换为 Windows 盘符路径（如 /mnt/e/... -> E:\\...）。

    仅在 WSL/Linux 且存在 wslpath 工具时返回 Windows 路径，否则返回 None。
    """
    try:
        out = subprocess.run(
            ["wslpath", "-w", path],
            capture_output=True, text=True, timeout=10,
        )
        win = (out.stdout or "").strip()
        return win if win else None
    except Exception:  # pragma: no cover
        return None


def _get_wsl_runuser_prefix() -> list[str] | None:
    """若当前进程以 root 运行且处于 WSL 环境，返回 runuser 命令前缀以切换到非 root 用户。

    WSL interop 在 root 用户下调用 Windows GUI 程序（如 explorer.exe）时，
    程序虽能启动但无法在交互式桌面会话中显示窗口。
    通过 runuser 切换到 WSL 默认用户即可解决此问题。

    返回示例: ["runuser", "-u", "liux", "--"]
    非 root 或找不到合适用户时返回 None。
    """
    if os.getuid() != 0:
        return None
    # 查找 WSL 默认非 root 用户：优先从 who 命令获取当前登录用户
    try:
        out = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
        for line in (out.stdout or "").strip().splitlines():
            username = line.split()[0] if line.split() else ""
            if username and username != "root":
                return ["runuser", "-u", username, "--"]
    except Exception:  # pragma: no cover
        pass
    # 回退：从 /run/user 目录查找 uid>=1000 的用户
    try:
        import glob
        for uid_dir in sorted(glob.glob("/run/user/*")):
            uid_str = uid_dir.split("/")[-1]
            if uid_str.isdigit() and int(uid_str) >= 1000:
                import pwd
                pw = pwd.getpwuid(int(uid_str))
                if pw and pw.pw_name != "root":
                    return ["runuser", "-u", pw.pw_name, "--"]
    except Exception:  # pragma: no cover
        pass
    return None


def _find_active_wsl_interop() -> str | None:
    """查找当前 WSL 主会话的 interop socket 路径。

    背景：每个 WSL 终端会话都会在 /run/WSL/ 下创建一个 <pid>_interop Unix socket，
    用于 Linux <-> Windows 互操作（调用 explorer.exe 等）。uvicorn 进程继承的
    WSL_INTEROP 可能来自一个已失效或非交互式的终端会话——socket 文件仍在、
    explorer.exe 能启动，但窗口不会在当前 Windows 桌面显示。

    WSL 主会话（PID 2 的 /init 进程）的 interop socket 始终关联当前的
    Windows 交互式桌面会话，因此优先使用它。

    查找顺序：
      1. /run/WSL/1_interop（WSL 主会话的标准符号链接）
      2. /run/WSL/2_interop（PID 2 的 /init 进程对应的 socket）
      3. /run/WSL/ 下数字最小且对应 /init 进程仍存活的 socket
      4. 返回 None（由调用方继承当前进程环境）
    """
    import glob as _glob

    candidates: list[str] = []

    # 优先1：标准符号链接 1_interop -> 2_interop
    link = "/run/WSL/1_interop"
    if os.path.islink(link):
        target = os.path.realpath(link)
        if os.path.exists(target):
            candidates.append(target)

    # 优先2：PID 2 的 /init 对应的 socket
    candidates.append("/run/WSL/2_interop")

    # 优先3：所有 <pid>_interop socket，按 pid 数字升序
    try:
        sockets = []
        for path in _glob.glob("/run/WSL/*_interop"):
            name = os.path.basename(path)
            pid_str = name.replace("_interop", "")
            if pid_str.isdigit():
                sockets.append((int(pid_str), path))
        sockets.sort(key=lambda x: x[0])
        for _, path in sockets:
            if path not in candidates:
                candidates.append(path)
    except Exception:  # pragma: no cover
        pass

    # 返回第一个存在且为 socket 的候选
    for path in candidates:
        try:
            if stat_is_socket(path):
                return path
        except Exception:
            continue
    return None


def stat_is_socket(path: str) -> bool:
    """判断路径是否为一个有效的 Unix socket 文件。"""
    import stat as _stat
    st = os.stat(path)
    return _stat.S_ISSOCK(st.st_mode)
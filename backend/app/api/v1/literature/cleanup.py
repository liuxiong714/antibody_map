"""孤儿文件清理端点 —— 本地文件和 MinIO 孤儿对象的预览与清理。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.file_cleanup_service import (
    cleanup_orphan_files,
    delete_minio_orphan_objects,
    scan_minio_orphans,
    scan_orphan_files,
)

logger = logging.getLogger("uvicorn")

router = APIRouter()


@router.get("/literatures/cleanup-orphan-files/preview", response_model=ApiResponse, summary="预览孤儿文件清理", description="（管理员）扫描 backend/data/pdfs，列出已不在数据库中的孤儿文件，不执行任何移动/删除")
async def preview_orphan_files_cleanup(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    scan = await scan_orphan_files(db)
    return ApiResponse(
        message=(
            f"扫描完成：共 {scan['total']} 个文件，其中孤儿文件 {len(scan['orphan'])} 个，"
            f"冷静期跳过 {len(scan['cooldown'])} 个，MinIO 引用保护 {len(scan['minio_protected'])} 个"
        ),
        data={
            "scanned": scan["total"],
            "orphan_count": len(scan["orphan"]),
            "orphan_files": scan["orphan"],
            "cooldown_count": len(scan["cooldown"]),
            "cooldown_files": scan["cooldown"],
            "minio_protected_count": len(scan["minio_protected"]),
            "minio_protected_files": scan["minio_protected"],
        },
    )


@router.post("/literatures/cleanup-orphan-files", response_model=ApiResponse, summary="清理孤儿文件", description="（管理员）清理 backend/data/pdfs 中已不在数据库的孤儿文件。默认 dry_run=true 仅预览不移动；显式传 dry_run=false 才将孤儿文件移入回收目录（默认保留 30 天后自动删除）。")
async def cleanup_orphan_files_endpoint(
    dry_run: bool = Query(True, description="为 true 时仅预览（默认，不移动）；为 false 时执行真实移动+清理过期回收"),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await cleanup_orphan_files(db, dry_run=dry_run, operator=user.username)
    except Exception as e:
        logger.error(f"[清理孤儿文件] 执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清理失败: {e}") from e
    if dry_run:
        message = (
            f"预览完成（未移动）：共 {result['scanned']} 个文件，"
            f"孤儿 {result['orphan_count']} 个，冷静期跳过 {len(result.get('cooldown_files', []))} 个，"
            f"MinIO 引用保护 {len(result.get('minio_protected_files', []))} 个"
        )
    else:
        message = (
            f"清理完成：扫描 {result['scanned']} 个文件，孤儿 {result['orphan_count']} 个，"
            f"移入回收 {result['moved']} 个，失败 {result['failed']} 个"
        )
    return ApiResponse(message=message, data=result)


@router.get("/literatures/cleanup-minio-orphan-files/preview", response_model=ApiResponse, summary="预览 MinIO 孤儿对象清理", description="（管理员）扫描 MINIO_BUCKET_LITERATURE，列出已不在数据库中的孤儿对象，不执行任何删除")
async def preview_minio_orphan_cleanup(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    scan = await scan_minio_orphans(db)
    return ApiResponse(
        message=(
            f"扫描完成：共 {scan['total']} 个对象，其中孤儿对象 {len(scan['orphan'])} 个，"
            f"冷静期跳过 {len(scan['cooldown'])} 个，引用保护 {len(scan['protected'])} 个"
            + ("" if scan.get("available", True) else "（MinIO 不可用，本次仅为降级结果）")
        ),
        data={
            "scanned": scan["total"],
            "orphan_count": len(scan["orphan"]),
            "orphan_files": scan["orphan"],
            "cooldown_count": len(scan["cooldown"]),
            "cooldown_files": scan["cooldown"],
            "protected_count": len(scan["protected"]),
            "protected_files": scan["protected"],
            "available": scan.get("available", True),
        },
    )


@router.post("/literatures/cleanup-minio-orphan-files", response_model=ApiResponse, summary="清理 MinIO 孤儿对象", description="（管理员）清理 MINIO_BUCKET_LITERATURE 中已不在数据库的孤儿对象。默认 dry_run=true 仅预览不删除；显式传 dry_run=false 才物理删除（无回收站，删除不可恢复）。")
async def cleanup_minio_orphan_objects_endpoint(
    dry_run: bool = Query(True, description="为 true 时仅预览（默认，不删除）；为 false 时执行物理删除"),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await delete_minio_orphan_objects(db, dry_run=dry_run, operator=user.username)
    except Exception as e:
        logger.error(f"[清理 MinIO 孤儿对象] 执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清理失败: {e}") from e
    if dry_run:
        message = (
            f"预览完成（未删除）：共 {result['scanned']} 个对象，"
            f"孤儿 {result['orphan_count']} 个，冷静期跳过 {len(result.get('cooldown_files', []))} 个，"
            f"引用保护 {len(result.get('protected_files', []))} 个"
        )
    else:
        message = (
            f"清理完成：扫描 {result['scanned']} 个对象，孤儿 {result['orphan_count']} 个，"
            f"物理删除 {result['deleted']} 个，失败 {result['failed']} 个"
        )
    return ApiResponse(message=message, data=result)
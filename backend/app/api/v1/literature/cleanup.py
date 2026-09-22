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
# ─────────────────────────────────────────────────────────────────────────────
# 数据一致性审计：extraction_history vs data_point 表
# ─────────────────────────────────────────────────────────────────────────────

from app.services.extraction_audit_service import (
    fix_extraction_consistency,
    scan_extraction_consistency,
)


@router.get(
    "/literatures/audit-extraction-consistency/preview",
    response_model=ApiResponse,
    summary="预览提取历史 vs 数据点的一致性",
    description=(
        "(管理员) 全局扫描 extraction_history.data_point_count 与 data_point 表 "
        "实际行数是否一致，返回 mismatch 清单。不执行任何修改。"
    ),
)
async def preview_extraction_consistency(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    literature_ids: str | None = Query(
        None,
        description="可选，逗号分隔的文献 UUID 列表；不传则扫描全部",
    ),
    model: str | None = Query(None, description="可选，限定模型名，如 ollama:gpt-oss:20b"),
    only_unmarked: bool = Query(
        True,
        description="True=只返回尚未 [DP_DROPPED] 标记的记录（默认）",
    ),
    include_non_success: bool = Query(
        False,
        description="False=只检查 status=success（默认）；True=含 no_data/failed",
    ),
):
    _lit_ids = None
    if literature_ids:
        _lit_ids = [x.strip() for x in literature_ids.split(",") if x.strip()]

    mismatches = await scan_extraction_consistency(
        db,
        literature_ids=_lit_ids,
        model=model,
        only_unmarked=only_unmarked,
        include_non_success=include_non_success,
    )
    total_eh = len(mismatches)
    eh_dp_claimed = sum(m["eh_dp"] for m in mismatches)
    real_dp_sum = sum(m["real_dp"] for m in mismatches)
    lost_dp = eh_dp_claimed - real_dp_sum

    # 按 model 汇总
    by_model: dict[str, dict] = {}
    for m in mismatches:
        mm = by_model.setdefault(
            m["model"] or "(no model)",
            {"count": 0, "eh_dp": 0, "real_dp": 0},
        )
        mm["count"] += 1
        mm["eh_dp"] += m["eh_dp"]
        mm["real_dp"] += m["real_dp"]

    return ApiResponse(
        message=(
            f"扫描完成：发现 {total_eh} 条不一致的提取历史，"
            f"eh 声称 {eh_dp_claimed} dp 但 real 表仅 {real_dp_sum} dp，"
            f"**丢失 {lost_dp} dp**"
        ),
        data={
            "total_mismatch": total_eh,
            "eh_dp_claimed": eh_dp_claimed,
            "real_dp_sum": real_dp_sum,
            "lost_dp": lost_dp,
            "by_model": by_model,
            "items": mismatches,
        },
    )


@router.post(
    "/literatures/audit-extraction-consistency",
    response_model=ApiResponse,
    summary="执行一致性修复：标记 mismatch 并修正 eh.data_point_count",
    description=(
        "(管理员) 对预览中的 mismatch 批量执行：在 error_message 追加 "
        "[DP_DROPPED] 标记，并把 eh.data_point_count 改写成 real 表实际值。"
        "默认 dry_run=true 仅预览不修改；显式 dry_run=false 才真正写入。"
    ),
)
async def execute_extraction_consistency(
    dry_run: bool = Query(
        True,
        description="True=仅预览（默认，不修改 DB）；False=真正写入修正",
    ),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    literature_ids: str | None = Query(None, description="可选，逗号分隔的文献 UUID"),
    model: str | None = Query(None, description="可选，限定模型名"),
    only_unmarked: bool = Query(True, description="True=仅处理未标记的（默认）"),
):
    _lit_ids = None
    if literature_ids:
        _lit_ids = [x.strip() for x in literature_ids.split(",") if x.strip()]

    mismatches = await scan_extraction_consistency(
        db,
        literature_ids=_lit_ids,
        model=model,
        only_unmarked=only_unmarked,
    )

    if dry_run:
        return ApiResponse(
            message=(
                f"[dry_run] 发现 {len(mismatches)} 条需要修正的 mismatch "
                f"（{sum(m['eh_dp'] - m['real_dp'] for m in mismatches)} dp 丢失）。"
                f"加 ?dry_run=false 执行真正修正。"
            ),
            data={
                "to_fix": len(mismatches),
                "lost_dp": sum(m["eh_dp"] - m["real_dp"] for m in mismatches),
                "items": mismatches[:50],  # 限制预览条目数
                "truncated": len(mismatches) > 50,
            },
        )

    try:
        result = await fix_extraction_consistency(db, mismatches, operator=user.username)
    except Exception as e:
        logger.error(f"[audit_consistency] 执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"修正失败: {e}") from e

    return ApiResponse(
        message=(
            f"修正完成：成功标记 {result['fixed']} 条，"
            f"跳过已标记 {result['already_marked_skipped']} 条，"
            f"errors={len(result['errors'])}"
        ),
        data=result,
    )

"""数据一致性审计服务 —— 核对 extraction_history.data_point_count 与 data_point 表实际行数。

用途：
1. 事后体检：对历史脏数据批量扫描，找出 eh 声明 N dp 但 data_point 表实际为 0/M 的记录
2. 批量修正：将 eh.data_point_count 改写成真实值，并在 error_message 中标记 [DP_DROPPED]

对应事前校验见 tasks/extract_task.py（commit 前自动核对）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint
from app.models.extraction_history import ExtractionHistory
from app.models.literature import Literature

logger = logging.getLogger("uvicorn")

_DP_DROPPED_TAG = "[DP_DROPPED]"


async def scan_extraction_consistency(
    db: AsyncSession,
    literature_ids: list[str] | None = None,
    model: str | None = None,
    only_unmarked: bool = True,
    include_non_success: bool = False,
) -> list[dict[str, Any]]:
    """扫描 extraction_history vs data_point 表的不一致。

    Args:
        db: 异步数据库会话
        literature_ids: 可选，限定文献 ID 子集（UUID 字符串列表）
        model: 可选，限定模型名（如 "ollama:gpt-oss:20b"）
        only_unmarked: True = 只返回尚未被 [DP_DROPPED] 标记过的记录（默认）
        include_non_success: False = 只检查 status='success'（默认）；True = 含 no_data/failed

    Returns:
        mismatch 列表，每项 dict: {
            "eh_id", "literature_id", "title", "model", "status",
            "eh_dp", "real_dp", "diff", "already_marked", "extracted_at"
        }
    """
    # 子查询：(eh_id → real_dp 数)
    dp_sub = (
        select(
            DataPoint.extraction_history_id.label("eh_id"),
            func.count(DataPoint.id).label("real_dp"),
        )
        .where(DataPoint.extraction_history_id.isnot(None))
        .group_by(DataPoint.extraction_history_id)
        .subquery()
    )

    stmt = (
        select(
            ExtractionHistory.id.label("eh_id"),
            ExtractionHistory.literature_id,
            ExtractionHistory.model,
            ExtractionHistory.status,
            ExtractionHistory.data_point_count.label("eh_dp"),
            ExtractionHistory.extracted_at,
            ExtractionHistory.error_message,
            Literature.title,
            dp_sub.c.real_dp,
        )
        .join(Literature, Literature.id == ExtractionHistory.literature_id)
        .outerjoin(dp_sub, dp_sub.c.eh_id == ExtractionHistory.id)
    )

    # 可选过滤器
    if not include_non_success:
        stmt = stmt.where(ExtractionHistory.status == "success")
    if literature_ids:
        # 限定在给定 ID 子集
        try:
            uuids = [lit_id for lit_id in literature_ids]
            stmt = stmt.where(ExtractionHistory.literature_id.in_(uuids))
        except Exception:
            pass
    if model:
        stmt = stmt.where(ExtractionHistory.model == model)

    result = await db.execute(stmt)
    rows = result.all()

    mismatches: list[dict[str, Any]] = []
    for row in rows:
        eh_dp = row.eh_dp or 0
        real_dp = row.real_dp or 0
        already_marked = bool(row.error_message and _DP_DROPPED_TAG in row.error_message)

        # 过滤条件：eh_dp != real_dp
        if eh_dp == real_dp:
            continue
        if only_unmarked and already_marked:
            continue

        mismatches.append(
            {
                "eh_id": str(row.eh_id),
                "literature_id": str(row.literature_id),
                "title": row.title or "",
                "model": row.model or "",
                "status": row.status or "",
                "eh_dp": eh_dp,
                "real_dp": real_dp,
                "diff": eh_dp - real_dp,
                "already_marked": already_marked,
                "extracted_at": row.extracted_at.isoformat() if row.extracted_at else None,
            }
        )

    return mismatches


async def fix_extraction_consistency(
    db: AsyncSession,
    mismatches: list[dict[str, Any]],
    operator: str = "admin",
) -> dict[str, Any]:
    """批量修正：对每个 mismatch，写 error_message 标记 + 修正 eh.data_point_count。

    不删除任何数据，仅把 eh 改成诚实值。
    """
    fixed = 0
    already_marked_skipped = 0
    errors: list[str] = []

    for m in mismatches:
        if m.get("already_marked"):
            already_marked_skipped += 1
            continue
        try:
            eh_id = m["eh_id"]
            eh_dp = m["eh_dp"]
            real_dp = m["real_dp"]

            eh = await db.get(ExtractionHistory, eh_id)
            if not eh:
                errors.append(f"eh {eh_id} not found")
                continue

            old_err = eh.error_message or ""
            tag = _DP_DROPPED_TAG
            if tag in old_err:
                already_marked_skipped += 1
                continue

            new_suffix = (
                f"{tag} eh claimed {eh_dp} dp, real table has {real_dp}. "
                f"Marked 2026-09-22 by {operator}."
            )
            if old_err:
                eh.error_message = old_err + "\n" + new_suffix
            else:
                eh.error_message = new_suffix

            # 核心：把 data_point_count 改成真实值
            eh.data_point_count = real_dp
            fixed += 1
        except Exception as e:
            errors.append(f"{m.get('eh_id', '?')}: {e}")
            logger.warning(f"[fix_extraction_consistency] 修正失败: {e}")

    if fixed > 0:
        await db.commit()
    else:
        await db.rollback()

    return {
        "fixed": fixed,
        "already_marked_skipped": already_marked_skipped,
        "total_input": len(mismatches),
        "errors": errors,
    }

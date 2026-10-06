"""修复文献状态滞留 processing（V2-01 阻塞修复配套脚本）。

扫描所有 extraction_status='processing' 的文献，判断是否已卡死：
- worker_heartbeat < now() - 间隔（默认 10 分钟）→ 卡死
- 有 ExtractionHistory status='success' → 置 done + 保留 extracted_count
- 无 ExtractionHistory → 置 pending（允许用户重新触发）

使用方式：

    # 预览（默认，不修改数据库）
    python -m scripts.fix_stuck_processing

    # 实际执行修复
    python -m scripts.fix_stuck_processing --apply

    # 自定义卡死阈值（默认 10 分钟）
    python -m scripts.fix_stuck_processing --interval 5

注意事项：
    - 绝不 DELETE 任何数据
    - 绝不影响 DataPoint
    - 脚本可重复运行（幂等）
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.models.extraction_history import ExtractionHistory
from app.models.literature import Literature

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fix_stuck_processing")


async def _scan_stuck(session: AsyncSession, interval_min: int) -> list[dict]:
    """扫描滞留 processing 超过间隔阈值的文献。"""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=interval_min)
    result = await session.execute(
        select(
            Literature.id,
            Literature.title,
            Literature.extraction_status,
            Literature.worker_heartbeat,
            Literature.extraction_started_at,
            Literature.extracted_count,
        ).where(
            Literature.extraction_status == "processing",
            Literature.worker_heartbeat.is_(None) | (Literature.worker_heartbeat < cutoff),
        )
    )
    rows = result.fetchall()
    stuck = []
    for row in rows:
        # 检查是否有 success 的 history
        hist_result = await session.execute(
            select(ExtractionHistory.status, ExtractionHistory.data_point_count)
            .where(ExtractionHistory.literature_id == row.id)
            .order_by(ExtractionHistory.extracted_at.desc())
            .limit(1)
        )
        hist = hist_result.first()
        stuck.append({
            "literature_id": str(row.id),
            "title": (row.title or "")[:60],
            "heartbeat": str(row.worker_heartbeat) if row.worker_heartbeat else "None",
            "started_at": str(row.extraction_started_at) if row.extraction_started_at else "None",
            "extracted_count": row.extracted_count or 0,
            "has_success_history": hist is not None and hist[0] in ("success", "no_data"),
            "history_dp_count": hist[1] if hist else None,
        })
    return stuck


async def _fix_one(session: AsyncSession, item: dict) -> str:
    """修复单篇文献状态，返回修复动作描述。"""
    lit_id = item["literature_id"]
    if item["has_success_history"]:
        # 有成功 history → 说明 V2-01 之前的旧 bug 导致状态没最终落定
        # 有数据点 → done；无数据点 → done_no_data
        target_status = "done" if item["history_dp_count"] else "done_no_data"
        _cas = await session.execute(
            update(Literature)
            .where(Literature.id == lit_id)
            .where(Literature.extraction_status == "processing")
            .values(
                extraction_status=target_status,
                extracted_count=item["history_dp_count"] or 0,
                extraction_started_at=None,
                worker_heartbeat=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        if _cas.rowcount == 0:
            return f"SKIP {lit_id}: CAS 未命中（状态已被其他进程更新）"
        return f"FIX {lit_id}: processing → {target_status}（有 success history, dp_count={item['history_dp_count']}）"
    else:
        # 无 success history → 置 pending 让用户重触发
        _cas = await session.execute(
            update(Literature)
            .where(Literature.id == lit_id)
            .where(Literature.extraction_status == "processing")
            .values(
                extraction_status="pending",
                extraction_started_at=None,
                worker_heartbeat=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        if _cas.rowcount == 0:
            return f"SKIP {lit_id}: CAS 未命中"
        return f"FIX {lit_id}: processing → pending（无 success history，等待用户重触发）"


async def main(dry_run: bool, interval_min: int, limit: int | None):
    async with get_async_session() as session:
        stuck = await _scan_stuck(session, interval_min)

    if limit:
        stuck = stuck[:limit]

    if not stuck:
        logger.info("✅ 没有滞留 processing 的文献（interval=%d min）", interval_min)
        return

    logger.info("发现 %d 篇滞留 processing 的文献（heartbeat 超过 %d 分钟未更新）:",
                len(stuck), interval_min)
    for i, item in enumerate(stuck, 1):
        hist_str = f"✅ success history (dp={item['history_dp_count']})" if item["has_success_history"] else "❌ 无 success history"
        logger.info("  [%d] %s | heartbeat=%s | %s",
                    i, item["title"], item["heartbeat"], hist_str)

    if dry_run:
        logger.info("\n⚠️ DRY-RUN 模式: %d 篇将被修复（加 --apply 执行）", len(stuck))
        return

    # 执行修复
    logger.info("\n=== 开始修复 ===")
    fixed = 0
    for item in stuck:
        async with get_async_session() as session:
            action = await _fix_one(session, item)
            await session.commit()
            logger.info(action)
            fixed += 1

    logger.info("\n✅ 修复完成: %d 篇文献已处理", fixed)
    # 最终校验
    async with get_async_session() as session:
        remaining = await _scan_stuck(session, interval_min)
        if remaining:
            logger.warning("仍有 %d 篇滞留（可能是真正的长任务），heartbeat 间隔调整后再运行", len(remaining))
        else:
            logger.info("✅ 无剩余滞留 processing 文献")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复文献状态滞留 processing（V2-01 脚本）")
    parser.add_argument("--apply", action="store_true", help="实际执行修复（默认 dry-run 预览）")
    parser.add_argument("--interval", type=int, default=10, help="判定卡死的 heartbeat 间隔（分钟，默认 10）")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少篇（默认全部）")
    args = parser.parse_args()

    logger.info("=== V2-01 fix_stuck_processing ===")
    logger.info("模式: %s | interval: %d min | limit: %s",
                "APPLY" if args.apply else "DRY-RUN",
                args.interval, args.limit or "all")

    asyncio.run(main(dry_run=not args.apply, interval_min=args.interval, limit=args.limit))

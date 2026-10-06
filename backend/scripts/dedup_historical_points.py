"""V3-06: 历史重复数据点脚本化清理 + 审计留痕.

问题: changelog 称"标记 4 组历史真重复为 rejected",但脚本与迁移中均无
对应代码 -> 手工操作、不可复现、无审计.

方案:
  1) 按 content_fingerprint 分组,识别多组真重复
  2) --dry-run (默认): 输出每组保留 ID (id 最小/最早写入者) + 待处理 ID 清单
  3) --apply: 对待处理行置 review_status='rejected' + review_reason='dedup_historical'
     **并写 AuditLog (action=dedup_historical, entity_type=data_point)**
  4) 输出 JSON 报告到 backups/dedup_report_<ts>.json
  5) --rollback <report.json>: 把报告里的行恢复为 review_status='pending',
     且 review_reason 仍为 'dedup_historical' (便于追溯)

使用方式:
  python -m scripts.dedup_historical_points                          # dry-run 审计
  python -m scripts.dedup_historical_points --apply                  # 实际标记 rejected
  python -m scripts.dedup_historical_points --rollback backups/xxx.json  # 回滚

设计原则:
  - 不删除任何数据行,只改 review_status
  - 幂等: --apply 已处理过的行会跳过 (review_reason='dedup_historical')
  - 可回滚: 每次 apply 都输出 JSON 报告,是 rollback 的唯一依据
  - 审计留痕: 每个被 reject 的 data_point 都有 AuditLog 记录
"""
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.base import get_async_session
from app.models.data_point import DataPoint

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dedup_historical")

BACKUPS_DIR = _backend_dir / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _find_duplicate_groups() -> list[dict[str, Any]]:
    """按 content_fingerprint 分组,返回所有 2+ 行重复组.

    只处理 fingerprint IS NOT NULL 的行 (空 fingerprint 说明 backfill 未跑过).
    每组保留策略: id 最小者 (最早写入),其余标记.
    """
    async for session in get_async_session():
        result = await session.execute(
            select(DataPoint).where(
                DataPoint.content_fingerprint.isnot(None),
                DataPoint.content_fingerprint != "",
            ).order_by(
                DataPoint.content_fingerprint, DataPoint.id
            )
        )
        rows = result.scalars().all()

    # 分组
    groups: dict[str, list[DataPoint]] = {}
    for dp in rows:
        groups.setdefault(dp.content_fingerprint, []).append(dp)

    dup_groups = []
    for fp, members in groups.items():
        if len(members) < 2:
            continue
        # 已被 dedup_historical 处理过的不再加入 (幂等)
        already_marked = [m for m in members if m.review_reason == "dedup_historical"]
        if len(members) - len(already_marked) < 2:
            continue
        keep = members[0]  # id 最小者
        reject = [m for m in members[1:] if m.review_reason != "dedup_historical"]
        dup_groups.append({
            "fingerprint": fp,
            "keep_id": str(keep.id),
            "keep_review_status": keep.review_status,
            "reject_ids": [str(m.id) for m in reject],
            "reject_count": len(reject),
            "total_in_group": len(members),
        })

    return dup_groups


async def _apply_dedup(dup_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对重复组执行 reject + 写 AuditLog + 输出 JSON 报告."""
    ts = _now_iso()
    report_entries: list[dict[str, Any]] = []
    total_rejected = 0

    async for session in get_async_session():
        for group in dup_groups:
            for rid_str in group["reject_ids"]:
                row = await session.get(DataPoint, rid_str)
                if row is None or row.review_reason == "dedup_historical":
                    continue

                old_status = row.review_status
                row.review_status = "rejected"
                row.review_reason = "dedup_historical"
                row.reviewed_at = datetime.now(timezone.utc)

                audit = AuditLog(
                    action="dedup_historical",
                    username="system:dedup_historical_points.py",
                    entity_type="data_point",
                    entity_id=str(row.id),
                    old_value=json.dumps({"review_status": old_status}, ensure_ascii=False),
                    new_value=json.dumps(
                        {"review_status": "rejected", "review_reason": "dedup_historical"},
                        ensure_ascii=False,
                    ),
                    detail=json.dumps(
                        {"fingerprint": group["fingerprint"], "keep_id": group["keep_id"]},
                        ensure_ascii=False,
                    ),
                )
                session.add(audit)

                report_entries.append({
                    "data_point_id": str(row.id),
                    "old_review_status": old_status,
                    "fingerprint": group["fingerprint"],
                    "kept_by": group["keep_id"],
                    "processed_at": ts,
                })
                total_rejected += 1

        await session.commit()

    logger.info("V3-06 dedup_historical: 标记 %d 行 rejected + %d 条 AuditLog",
                total_rejected, total_rejected)

    # 写 JSON 报告
    report_path = BACKUPS_DIR / f"dedup_report_{ts.replace(':', '-')}.json"
    report = {
        "script": "dedup_historical_points.py",
        "timestamp": ts,
        "summary": {
            "groups_found": len(dup_groups),
            "total_rejected": total_rejected,
        },
        "entries": report_entries,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("JSON report: %s", report_path)
    logger.info("rollback: python -m scripts.dedup_historical_points --rollback %s",
                report_path.name)

    return report_entries


async def _rollback_from_report(report_path: Path) -> int:
    """根据 JSON 报告回滚: review_status -> 'pending',review_reason 保持留痕."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    entries = report.get("entries", [])
    restored = 0

    async for session in get_async_session():
        for entry in entries:
            rid = entry["data_point_id"]
            row = await session.get(DataPoint, rid)
            if row is None:
                logger.warning("rollback: data_point %s not found, skip", rid)
                continue
            if row.review_reason != "dedup_historical":
                logger.warning("rollback: data_point %s reason=%s (not dedup), skip",
                               rid, row.review_reason)
                continue

            old_status = row.review_status
            row.review_status = "pending"

            audit = AuditLog(
                action="dedup_historical_rollback",
                username="system:dedup_historical_points.py",
                entity_type="data_point",
                entity_id=str(row.id),
                old_value=json.dumps({"review_status": old_status}, ensure_ascii=False),
                new_value=json.dumps({"review_status": "pending"}, ensure_ascii=False),
                detail=json.dumps({"rollback_from": str(report_path.name)}, ensure_ascii=False),
            )
            session.add(audit)
            restored += 1

        await session.commit()

    logger.info("V3-06 rollback: restored %d rows -> pending, %d AuditLog",
                restored, restored)
    return restored


async def main(args: argparse.Namespace):
    if args.rollback:
        report_path = Path(args.rollback)
        if not report_path.is_absolute():
            report_path = BACKUPS_DIR / report_path
        if not report_path.exists():
            logger.error("report not found: %s", report_path)
            sys.exit(1)
        logger.info("rollback from: %s", report_path)
        await _rollback_from_report(report_path)
        return

    dup_groups = await _find_duplicate_groups()

    if not dup_groups:
        logger.info("no duplicate groups (content_fingerprint no 2+ groups)")
        return

    total_pending_reject = sum(g["reject_count"] for g in dup_groups)
    logger.info("V3-06 dedup_historical audit")
    logger.info("  groups: %d", len(dup_groups))
    logger.info("  rows to process: %d", total_pending_reject)
    logger.info("")
    for i, g in enumerate(dup_groups, 1):
        logger.info("  #%d fp=%s... keep=%s reject=%d group_total=%d",
                     i, g["fingerprint"][:12], g["keep_id"][:8],
                     g["reject_count"], g["total_in_group"])
        for rid in g["reject_ids"]:
            logger.info("      reject %s", rid[:8])

    if not args.apply:
        logger.info("")
        logger.info("--- DRY-RUN (default) — no changes ---")
        logger.info("add --apply to mark rejected")
        return

    await _apply_dedup(dup_groups)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="V3-06: historical duplicate data_point dedup (dry-run default)"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="actually mark duplicates rejected (default dry-run)"
    )
    parser.add_argument(
        "--rollback", metavar="REPORT.JSON",
        help="rollback from JSON report: restore dedup_historical rows to pending"
    )
    args = parser.parse_args()

    asyncio.run(main(args))

"""V2-05 审计 + 回填 DataPoint.content_fingerprint。

步骤:
  1) 审计: 扫描 data_point，按 7 字段 key 聚合计数，报告重复点
     --dry-run 默认，输出"将影响 N 行"，绝不 DELETE
  2) 回填: 为 fingerprint IS NULL 的行计算并写入 SHA256
  3) apply 模式下额外输出"哪些 fingerprint 有重复，涉及哪些 ID"

指纹算法 (与 extract_task.py:1282 去重逻辑一致):
  sha256(f"{disease}|{province}|{city}|{data_type}|{age_min}|{age_max}|
          {collection_year}|{round(value,6)}")
  所有 None 值统一用 "NULL" 字符串。

使用方式:
    # 审计（默认）
    python -m scripts.backfill_dp_fingerprint

    # 回填 fingerprint 列（写 DB）
    python -m scripts.backfill_dp_fingerprint --apply

    # 额外输出具体重复 ID 列表（便于人工审计）
    python -m scripts.backfill_dp_fingerprint --apply --show-dup-ids
"""
import argparse
import asyncio
import hashlib
import logging
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_async_session
from app.models.data_point import DataPoint

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_fingerprint")


def compute_fingerprint(dp: DataPoint) -> str:
    """与 extract_task.py:1282 完全一致的指纹算法。"""
    val = round(dp.value, 6) if dp.value is not None else None
    parts = [
        str(dp.disease or "NULL"),
        str(dp.province or "NULL"),
        str(dp.city or "NULL"),
        str(dp.data_type or "NULL"),
        str(dp.age_min if dp.age_min is not None else "NULL"),
        str(dp.age_max if dp.age_max is not None else "NULL"),
        str(dp.collection_year if dp.collection_year is not None else "NULL"),
        str(val if val is not None else "NULL"),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def audit_duplicates(session: AsyncSession) -> dict:
    """按 7 字段 key 聚合审计重复。不读 fingerprint 列（可能还是 NULL）。"""
    # 用纯 SQL 聚合，快且不走 ORM
    result = await session.execute(
        select(
            DataPoint.disease, DataPoint.province, DataPoint.city,
            DataPoint.data_type, DataPoint.age_min, DataPoint.age_max,
            DataPoint.collection_year,
            func.count().label("cnt"),
        ).group_by(
            DataPoint.disease, DataPoint.province, DataPoint.city,
            DataPoint.data_type, DataPoint.age_min, DataPoint.age_max,
            DataPoint.collection_year,
        ).having(func.count() > 1)
        .order_by(func.count().desc())
        .limit(50)
    )
    dup_groups = result.fetchall()
    return {
        "dup_group_count": len(dup_groups),
        "dup_groups": dup_groups,
    }


async def count_total_and_null(session: AsyncSession) -> dict:
    """总量 + fingerprint 已存在/缺失数。"""
    total = await session.execute(select(func.count()).select_from(DataPoint))
    null_fp = await session.execute(
        select(func.count()).select_from(DataPoint).where(
            (DataPoint.content_fingerprint.is_(None)) |
            (DataPoint.content_fingerprint == "")
        )
    )
    return {"total": total.scalar() or 0, "null_fp": null_fp.scalar() or 0}


async def backfill(session: AsyncSession, batch_size: int = 500, apply: bool = False) -> int:
    """分批回填 fingerprint。返回回填行数（dry-run 为预期行数）。"""
    total = await session.execute(select(func.count()).select_from(DataPoint).where(
        DataPoint.content_fingerprint.is_(None)
    ))
    null_count = total.scalar() or 0
    if null_count == 0:
        logger.info("✅ 无 fingerprint IS NULL 的行 — 已是最新")
        return 0

    if not apply:
        logger.info("DRY-RUN: 预期回填 %d 行 data_point", null_count)
        return null_count

    logger.info("开始回填 %d 行，batch_size=%d", null_count, batch_size)
    backfilled = 0
    offset = 0
    while True:
        rows = (await session.execute(
            select(DataPoint).where(DataPoint.content_fingerprint.is_(None)).limit(batch_size).offset(offset)
        )).scalars().all()
        if not rows:
            break
        for dp in rows:
            dp.content_fingerprint = compute_fingerprint(dp)
        await session.flush()
        await session.commit()
        backfilled += len(rows)
        logger.info("  batch: offset=%d, filled=%d, total=%d", offset, len(rows), backfilled)
        offset += batch_size
    return backfilled


async def main(apply: bool, show_dup_ids: bool):
    logger.info("=== V2-05 backfill_dp_fingerprint ===")
    logger.info("模式: %s", "APPLY" if apply else "DRY-RUN")

    # Step 1: 审计
    async for session in get_async_session():
        counts = await count_total_and_null(session)
        dup_info = await audit_duplicates(session)

    logger.info("总量: %d | fingerprint 已存在: %d | 缺失: %d",
                counts["total"], counts["total"] - counts["null_fp"], counts["null_fp"])

    if dup_info["dup_group_count"] > 0:
        logger.warning("⚠️ 发现 %d 组潜在重复（按 7 字段 key 聚合），TOP 10:",
                       dup_info["dup_group_count"])
        for g in dup_info["dup_groups"][:10]:
            logger.warning("  cnt=%d disease=%s province=%s city=%s type=%s ages=%s-%s year=%s",
                           g.cnt, g.disease, g.province, g.city, g.data_type,
                           g.age_min, g.age_max, g.collection_year)
        if not apply:
            logger.info("加 --apply 执行回填后，可用 pg_stat_statements 或单独脚本审重复详情")
    else:
        logger.info("✅ 存量审计通过 — 未发现 7 字段 key 重复组")

    # Step 2: 回填
    if counts["null_fp"] > 0:
        async for session in get_async_session():
            filled = await backfill(session, apply=apply)
        logger.info("fingerprint 回填: %d 行 (%s)", filled, "已写入" if apply else "预计")

    if apply and show_dup_ids and dup_info["dup_group_count"] > 0:
        logger.info("提示: 回填完 fingerprint 后，可单独建唯一索引脚本审计重复 ID")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V2-05 审计 + 回填 content_fingerprint")
    parser.add_argument("--apply", action="store_true", help="实际回填 fingerprint（默认 dry-run）")
    parser.add_argument("--show-dup-ids", action="store_true", help="输出具体重复点 ID 列表")
    args = parser.parse_args()

    asyncio.run(main(apply=args.apply, show_dup_ids=args.show_dup_ids))

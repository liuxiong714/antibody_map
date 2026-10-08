"""V6-04: 数据红线巡检 Python 包装

执行 docs/change-checklist.md §4 的 6 条巡检 SQL，
全 0 即 exit 0；非 0 红线项 exit 1。pending 超 7 天标 warning 不算失败。

用法:
    # 默认读 DATABASE_URL 环境变量 (asyncpg 驱动)
    python backend/scripts/check_health.py

    # 显式指定 (psycopg 驱动也可)
    python backend/scripts/check_health.py --db-url postgresql://antibody:xxx@localhost:15432/antibody_map

豁免说明:
    #2 pending_older_than_7d — 业务状态豁免 (数据量积累的 pending 是正常现象,
       不属于红线错误; 若归零反而说明数据清理或批量 approved 过)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# --- 6 条巡检定义 -----------------------------------------------------

SQL_FILE = Path(__file__).parent / "daily_health_check.sql"

# (check_id, sql, kind, hint)
#   kind="error"  → bad_count>0 算失败, exit code 变 1
#   kind="warning" → 打印 warning 但不影响 exit code (业务豁免)
CHECKS = [
    (
        "dup_groups",
        "SELECT COUNT(*) FROM ("
        "  SELECT 1 FROM data_point"
        "  WHERE review_status != 'rejected'"
        "    AND content_fingerprint IS NOT NULL AND content_fingerprint != ''"
        "  GROUP BY literature_id, content_fingerprint"
        "  HAVING COUNT(*) > 1) t",
        "error",
        "uq_dp_lit_fingerprint 唯一索引应全部命中",
    ),
    (
        "pending_older_than_7d",
        "SELECT COUNT(*) FROM data_point"
        " WHERE review_status = 'pending'"
        "   AND created_at < NOW() - INTERVAL '7 days'",
        "warning",
        "业务状态豁免: pending 数据积累是正常现象, 不属于红线",
    ),
    (
        "approved_value_out_of_range",
        "SELECT COUNT(*) FROM data_point WHERE review_status = 'approved'"
        " AND ((data_type = 'seroprevalence' AND (value IS NULL OR value < 0 OR value > 100))"
        "    OR (data_type = 'gmc' AND (value IS NULL OR value < 0)))",
        "error",
        "seroprevalence 应在 [0,100], gmc 应 >=0",
    ),
    (
        "approved_no_source",
        "SELECT COUNT(*) FROM data_point WHERE review_status = 'approved'"
        " AND source_page IS NULL"
        " AND (source_context IS NULL OR btrim(source_context) = '')",
        "error",
        "已 approved 的数据点必须有溯源 (source_page + source_context 至少其一)",
    ),
    (
        "approved_ungrounded",
        "SELECT COUNT(*) FROM data_point"
        " WHERE review_status = 'approved' AND is_grounded = FALSE",
        "error",
        "语义矛盾: is_grounded=false 但 approved",
    ),
    (
        "fk_orphans",
        # 用 UNION ALL 返回多行, 分别计数; 包装在外层求和
        "SELECT COALESCE(SUM(cnt),0) FROM ("
        "  SELECT 'dp->lit orphan' AS check_name, COUNT(*) AS cnt FROM data_point dp"
        "   WHERE dp.literature_id NOT IN (SELECT id FROM literature)"
        "  UNION ALL"
        "  SELECT 'dp->eh orphan', COUNT(*) FROM data_point dp"
        "   WHERE dp.extraction_history_id IS NOT NULL"
        "     AND dp.extraction_history_id::uuid NOT IN (SELECT id FROM extraction_history)"
        "  UNION ALL"
        "  SELECT 'eh->lit orphan', COUNT(*) FROM extraction_history eh"
        "   WHERE eh.literature_id IS NOT NULL"
        "     AND eh.literature_id NOT IN (SELECT id FROM literature)"
        ") fk_all",
        "error",
        "FK 完整性: 数据点不能脱离 literature / extraction_history 存在",
    ),
    # V8-05: 幻觉率红线（已审核但未溯源的点，正常应为 0）
    (
        "hallucination_unapproved",
        "SELECT COUNT(*) FROM data_point"
        " WHERE review_status = 'approved'"
        "   AND is_grounded = FALSE"
        "   AND (source_context IS NULL OR btrim(source_context) = '')",
        "error",
        "V8-05 幻觉率红线: approved 但未溯源 (is_grounded=False 且 source_context 空)",
    ),
]


def _strip_driver(url: str) -> str:
    """把 DATABASE_URL 的 asyncpg/psycopg 驱动前缀剥掉 (psycopg 不接受 +asyncpg)。"""
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
           .replace("postgresql+psycopg://", "postgresql://")
    )


async def _run_one(pool, check_id: str, sql: str) -> int:
    async with pool.acquire() as conn:
        val = await conn.fetchval(sql)
        return int(val or 0)


async def main_async(db_url: str) -> int:
    try:
        import asyncpg  # type: ignore
    except ImportError:
        print("[health] ERROR: 需要 asyncpg (pip install asyncpg)", file=sys.stderr)
        return 2

    pg_url = _strip_driver(db_url)
    print(f"[health] connect → {pg_url}")

    pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=2)
    errors = 0
    warnings = 0
    print()
    print(f"{'check_id':<32} {'kind':<8} {'bad':>6}  hint")
    print("-" * 90)

    try:
        for check_id, sql, kind, hint in CHECKS:
            try:
                bad = await _run_one(pool, check_id, sql)
            except Exception as e:
                print(f"{check_id:<32} {'error':<8} {'ERR!':>6}  执行失败: {e}")
                errors += 1
                continue

            marker = ("❌" if kind == "error" and bad > 0 else "⚠️" if kind == "warning" and bad > 0 else "✅")
            print(f"{check_id:<32} {kind:<8} {bad:>6}  {marker} {hint}")

            if kind == "error" and bad > 0:
                errors += 1
            elif kind == "warning" and bad > 0:
                warnings += 1
    finally:
        await pool.close()

    print()
    if errors == 0:
        if warnings == 0:
            print("[health] ✅ 全部通过 — 数据红线为 0")
        else:
            print(f"[health] ⚠️  {warnings} 条业务豁免项有值 (不计入失败) — 数据红线为 0")
        return 0
    else:
        print(f"[health] ❌ {errors} 条红线失败 — 需要修复!")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="V6-04: 数据红线巡检")
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL"),
        help="数据库连接串 (默认读 DATABASE_URL 环境变量)",
    )
    args = parser.parse_args()

    if not args.db_url:
        print("[health] ERROR: 未指定 --db-url 且 DATABASE_URL 为空", file=sys.stderr)
        return 2

    return asyncio.run(main_async(args.db_url))


if __name__ == "__main__":
    sys.exit(main())

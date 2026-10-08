"""V8-05: 从已 approved 的 DataPoint 中随机抽样导出 Golden Set 标注文件。

用途: 为后续人工标注（"标准答案"）提供候选集。标注回填后，
import_golden_set.py 会把人工答案与原始数据做比对，产出评测指标。

输出 CSV 列:
  id | literature_id | disease | province | data_type | value | ci_lower | ci_upper |
  sample_size | age_group | collection_year | source_page | source_context |
  is_grounded | confidence | model_used | content_fingerprint | _golden_status | _golden_note

其中 _golden_status / _golden_note 为标注预留字段:
  - _golden_status 可选值: correct / missing / hallucinated / disputed
  - _golden_note: 标注者备注

用法:
  python backend/scripts/export_golden_candidates.py
  python backend/scripts/export_golden_candidates.py --limit 300 --seed 42
  python backend/scripts/export_golden_candidates.py --output ./golden_v8-05.csv
  python backend/scripts/export_golden_candidates.py --db-url postgresql://...
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import random
import sys
from datetime import datetime
from pathlib import Path


def _strip_driver(url: str) -> str:
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
           .replace("postgresql+psycopg://", "postgresql://")
    )


async def export(db_url: str, limit: int, seed: int, output: str) -> str:
    try:
        import asyncpg
    except ImportError:
        print("[golden] ERROR: 需要 asyncpg (pip install asyncpg)", file=sys.stderr)
        sys.exit(2)

    pg_url = _strip_driver(db_url)
    print(f"[golden] connect → {pg_url}")

    pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=2)

    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM data_point WHERE review_status = 'approved'"
            )
            print(f"[golden] approved 总数: {total}")

            if not total:
                print("[golden] ERROR: 无 approved 数据点可抽样", file=sys.stderr)
                return ""

            effective_limit = min(limit, total)
            offset = random.Random(seed).randint(0, max(0, total - effective_limit))
            rows = await conn.fetch(
                f"SELECT id, literature_id, disease, province, data_type, "
                f"value, ci_lower, ci_upper, sample_size, age_group, collection_year, "
                f"source_page, source_context, is_grounded, confidence, model_used, "
                f"content_fingerprint "
                f"FROM data_point WHERE review_status = 'approved' "
                f"ORDER BY id "
                f"LIMIT {effective_limit} OFFSET {offset}"
            )

            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            fieldnames = [
                "id", "literature_id", "disease", "province", "data_type",
                "value", "ci_lower", "ci_upper", "sample_size", "age_group",
                "collection_year", "source_page", "source_context",
                "is_grounded", "confidence", "model_used", "content_fingerprint",
                "_golden_status", "_golden_note",
            ]

            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for r in rows:
                    writer.writerow({
                        "id": str(r["id"]),
                        "literature_id": str(r["literature_id"]) if r["literature_id"] else "",
                        "disease": r["disease"] or "",
                        "province": r["province"] or "",
                        "data_type": r["data_type"] or "",
                        "value": r["value"] if r["value"] is not None else "",
                        "ci_lower": r["ci_lower"] if r["ci_lower"] is not None else "",
                        "ci_upper": r["ci_upper"] if r["ci_upper"] is not None else "",
                        "sample_size": r["sample_size"] or "",
                        "age_group": r["age_group"] or "",
                        "collection_year": r["collection_year"] or "",
                        "source_page": r["source_page"] or "",
                        "source_context": (r["source_context"] or "")[:500],
                        "is_grounded": r["is_grounded"],
                        "confidence": r["confidence"] or "",
                        "model_used": r["model_used"] or "",
                        "content_fingerprint": r["content_fingerprint"] or "",
                        "_golden_status": "",
                        "_golden_note": "",
                    })

            print(f"[golden] 导出 {len(rows)} 行 → {out_path}")
            print(f"[golden]   抽样: offset={offset}, limit={effective_limit}, seed={seed}")
            print(f"[golden]   标注完成后运行 import_golden_set.py 回填并评测")
            return str(out_path)
    finally:
        await pool.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="V8-05: 导出 Golden Set 候选")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL"),
                        help="数据库连接串 (默认读 DATABASE_URL)")
    parser.add_argument("--limit", type=int, default=200,
                        help="抽样数量 (默认 200)")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子 (默认 42, 保证可复现)")
    parser.add_argument("--output", default=None,
                        help="输出 CSV 路径 (默认 golden_candidates_YYYYMMDD.csv)")
    args = parser.parse_args()

    if not args.db_url:
        print("[golden] ERROR: 未指定 --db-url 且 DATABASE_URL 为空", file=sys.stderr)
        return 2

    out = args.output or f"golden_candidates_{datetime.now().strftime('%Y%m%d')}.csv"
    path = asyncio.run(export(args.db_url, args.limit, args.seed, out))
    return 0 if path else 1


if __name__ == "__main__":
    sys.exit(main())

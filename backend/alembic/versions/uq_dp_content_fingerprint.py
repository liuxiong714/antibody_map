"""V2-05 Step 3: 建 content_fingerprint 唯一索引 (partial, 排除 rejected)。

V3-05 二次修订:
  - 新增规模判断 (>50 万行 → 跳过事务内建索引，提示运维走 CONCURRENTLY 脚本)
  - CONCURRENTLY 脚本位于 scripts/create_index_concurrently.sql

幂等性: 用 DO $$ ... IF NOT EXISTS ... $$ 块，重入安全。
注意: ALTER TABLE 里不能用 CREATE INDEX CONCURRENTLY，因此 CONCURRENTLY
索引必须在事务外执行（独立 psql 或 pgAdmin 会话）。

Revision ID: uq_dp_content_fingerprint
Revises: add_datapoint_content_fingerprint
Create Date: 2026-10-06 15:30:00  (V3-05 rev: 2026-10-06 17:00:00)
"""
from alembic import op
import sqlalchemy as sa


revision = "uq_dp_content_fingerprint"
down_revision = "add_datapoint_content_fingerprint"
branch_labels = None
depends_on = None


_INDEX_NAME = "uq_dp_lit_fingerprint"
_SQL_CONCURRENTLY_SCRIPT = "scripts/create_index_concurrently.sql"
_SIZE_THRESHOLD = 500_000  # 超过此行数跳过事务内建索引


def upgrade() -> None:
    # V3-05: 规模判断 — 大表必须用 CONCURRENTLY (事务外)
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM data_point")).scalar() or 0

    if n > _SIZE_THRESHOLD:
        print(
            f"[V3-05] data_point={n} 行 (>{_SIZE_THRESHOLD}), 跳过事务内建索引 "
            f"({_INDEX_NAME})。"
            f" 请在库上独立执行 '{_SQL_CONCURRENTLY_SCRIPT}' 零停机建索引。"
            f" 此迁移会继续成功完成 — 索引创建由运维手动在 CONCURRENTLY 模式下完成。"
        )
        # 先确保旧的非 CONCURRENTLY 索引不存在（幂等 DROP）
        op.execute(
            "DROP INDEX IF EXISTS uq_dp_lit_fingerprint"
        )
        return

    # --- 小表 / 开发库路径 ---
    # 先幂等 DROP（开发库可能已手工建过非 CONCURRENTLY 版本）
    op.execute(
        "DROP INDEX IF EXISTS uq_dp_lit_fingerprint"
    )
    # 事务内普通 CREATE UNIQUE INDEX（小表无锁表风险）
    op.execute(f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
        ON data_point (literature_id, content_fingerprint)
        WHERE content_fingerprint IS NOT NULL
          AND content_fingerprint != ''
          AND review_status != 'rejected'
    """)
    print(f"[V3-05] data_point={n} 行 (≤{_SIZE_THRESHOLD}), "
          f"事务内建唯一索引 {_INDEX_NAME} ✅")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")

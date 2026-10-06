"""V2-05 Step 3: 建 content_fingerprint 唯一索引 (partial, 排除 rejected)。

幂等性: 用 DO $$ ... IF NOT EXISTS ... $$ 块，重入安全。
不阻塞长事务: 用 CREATE UNIQUE INDEX CONCURRENTLY（alembic 执行前已退出事务）。

Revision ID: uq_dp_content_fingerprint
Revises: add_datapoint_content_fingerprint
Create Date: 2026-10-06 15:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = "uq_dp_content_fingerprint"
down_revision = "add_datapoint_content_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # V2-05 Step 3: partial 唯一索引只约束非 rejected 的 active 行。
    # rejected 行已在 dedup 脚本里标记（review_status='rejected'），
    # 指纹相同的 rejected+active 对允许共存（rejected 不计入唯一约束）。
    #
    # 注意: 开发库已手工执行过一次 CREATE UNIQUE INDEX（非 CONCURRENTLY），
    # 先 DROP IF EXISTS 幂等处理。
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_indexes
                       WHERE tablename = 'data_point'
                       AND indexname = 'uq_dp_lit_fingerprint') THEN
                DROP INDEX uq_dp_lit_fingerprint;
            END IF;
        END $$;
    """)
    # 开发库 / alembic upgrade 均在非 CONCURRENTLY 模式下（事务内）。
    # 生产部署若需零停机，手动在数据库 shell 执行:
    #   CREATE UNIQUE INDEX CONCURRENTLY uq_dp_lit_fingerprint
    #     ON data_point (literature_id, content_fingerprint)
    #     WHERE content_fingerprint IS NOT NULL AND content_fingerprint != ''
    #       AND review_status != 'rejected';
    op.execute("""
        CREATE UNIQUE INDEX uq_dp_lit_fingerprint
        ON data_point (literature_id, content_fingerprint)
        WHERE content_fingerprint IS NOT NULL
          AND content_fingerprint != ''
          AND review_status != 'rejected'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_dp_lit_fingerprint")

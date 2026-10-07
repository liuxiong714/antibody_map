"""add_dp_extraction_history_fk — data_point.extraction_history_id FK（ON DELETE SET NULL）

Revision ID: add_dp_extraction_history_fk
Revises: uq_dp_content_fingerprint
Create Date: 2026-10-07

背景：
  - V6-02 曾把此 FK 加在历史迁移 add_datapoint_extraction_provenance 里
    （revision id 未变 → 已执行过该迁移的库不会重跑 → FK 不生效）。
  - V7-03 修正：结构性变更一律追加新迁移（不得修改已发布迁移）。
  - 前置条件：data_point.extraction_history_id 有值但 eh 不存在的孤儿 = 0
    （跑 upgrade 前先执行 V7-03 前置审计 SQL 确认）。

幂等：
  - ADD CONSTRAINT IF NOT EXISTS
  - DROP CONSTRAINT IF EXISTS
  - NOT VALID + 立即 VALIDATE（测试库数据量小；大表部署场景由运维低峰手动重跑 VALIDATE）
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'add_dp_extraction_history_fk'
down_revision: Union[str, Sequence[str], None] = 'uq_dp_content_fingerprint'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加 FK + 立即 VALIDATE。前置：孤儿审计 = 0。"""
    # PG 语法：ADD CONSTRAINT IF NOT EXISTS 与 NOT VALID 不能直接拼
    # → 用 DO block 手动判断是否已存在（真幂等）
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_dp_extraction_history'
                  AND conrelid = 'data_point'::regclass
            ) THEN
                ALTER TABLE data_point
                ADD CONSTRAINT fk_dp_extraction_history
                FOREIGN KEY (extraction_history_id) REFERENCES extraction_history(id)
                ON DELETE SET NULL NOT VALID;
            END IF;
        END $$;
    """)
    # 小库直接 VALIDATE；大表由运维低峰手动：
    #   ALTER TABLE data_point VALIDATE CONSTRAINT fk_dp_extraction_history;
    op.execute("ALTER TABLE data_point VALIDATE CONSTRAINT fk_dp_extraction_history")


def downgrade() -> None:
    op.execute("ALTER TABLE data_point DROP CONSTRAINT IF EXISTS fk_dp_extraction_history")

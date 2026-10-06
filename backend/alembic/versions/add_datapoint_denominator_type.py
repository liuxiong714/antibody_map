"""add_datapoint_denominator_type_and_value_note

V2-04: DataPoint 加 denominator_type / value_note — 分母语义标签。

5.2 Prompt/Schema v2 新增的关键字段，原代码只在校验瞬间使用（extraction_grounding.py），
未落库导致无法前端展示、二次校验、审计。

- denominator_type: 分母口径标签（serum_samples/population/cases/specimens/animals/unknown）
- value_note: 数值说明（如 "range" 表示区间取中值、"<10" 表示检出限）

幂等: ADD COLUMN IF NOT EXISTS，NOT NULL 默认值。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "add_datapoint_denominator_type"
down_revision = "add_extraction_history_cache_hit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE data_point ADD COLUMN IF NOT EXISTS denominator_type "
        "VARCHAR(20) DEFAULT NULL"
    )
    op.execute(
        "ALTER TABLE data_point ADD COLUMN IF NOT EXISTS value_note "
        "VARCHAR(100) DEFAULT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS value_note")
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS denominator_type")

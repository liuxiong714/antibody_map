"""add_extraction_history_grounding_rate

5.4: extraction_history 加 grounding_rate + ungrounded_count。

- grounding_rate: Numeric(5,4) NULL  — is_grounded=True 的点 / 总点数
- ungrounded_count: Integer NULL     — 未溯源点数（冗余存，便于快速筛选告警）

规则: ADD COLUMN ... NULL（项目硬性约束，禁止 ALTER COLUMN TYPE / DROP COLUMN）。
幂等: IF NOT EXISTS。

Revision ID: add_extraction_history_grounding_rate
Revises: add_kg_triple_source
Create Date: 2026-09-30 20:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "add_extraction_history_grounding_rate"
down_revision = "add_kg_triple_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE extraction_history ADD COLUMN IF NOT EXISTS grounding_rate NUMERIC(5,4)")
    op.execute("ALTER TABLE extraction_history ADD COLUMN IF NOT EXISTS ungrounded_count INTEGER")
    # NOTE: CREATE INDEX CONCURRENTLY cannot run inside a transaction block
    # (env.py wraps all migrations in one asyncpg connection).
    # Use plain CREATE INDEX IF NOT EXISTS — safe here because no concurrent writers.
    op.create_index(
        "ix_extraction_history_grounding_rate",
        "extraction_history",
        ["grounding_rate"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extraction_history_grounding_rate",
        table_name="extraction_history",
        if_exists=True,
    )
    op.execute("ALTER TABLE extraction_history DROP COLUMN IF EXISTS ungrounded_count")
    op.execute("ALTER TABLE extraction_history DROP COLUMN IF EXISTS grounding_rate")

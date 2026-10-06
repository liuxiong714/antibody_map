"""add_extraction_history_cache_hit

V2-01: ExtractionHistory 加 cache_hit 列。

缓存命中早退（extract_task.py:1127-1144）补闭环：
- cache_hit=True 表示跳过 LLM 调用，token/cost/duration 全为 0
- 与 V2-01 的终态 CAS 配套，确保缓存命中也写 history 记录

幂等: IF NOT EXISTS。

Revision ID: add_extraction_history_cache_hit
Revises: add_extraction_history_grounding_rate
Create Date: 2026-10-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "add_extraction_history_cache_hit"
down_revision = "add_extraction_history_grounding_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE extraction_history ADD COLUMN IF NOT EXISTS cache_hit "
        "BOOLEAN DEFAULT FALSE NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE extraction_history DROP COLUMN IF EXISTS cache_hit")

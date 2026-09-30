"""add extraction_history.duration_seconds

Revision ID: add_extraction_history_duration
Revises: add_literature_owner_id
Create Date: 2026-08-27

在 extraction_history 表中新增 duration_seconds 列，用于记录每篇文献每次 AI 提取的耗时：
- 成功路径：LLM 提取耗时（秒）
- 失败路径：从任务抢占到失败的整段耗时（秒）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_extraction_history_duration"
down_revision: Union[str, Sequence[str], None] = "add_literature_owner_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add duration_seconds column to extraction_history table."""
    op.add_column(
        "extraction_history",
        sa.Column(
            "duration_seconds",
            sa.Numeric(precision=12, scale=3),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Remove duration_seconds column from extraction_history table."""
    op.drop_column("extraction_history", "duration_seconds")
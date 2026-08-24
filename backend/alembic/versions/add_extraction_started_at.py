"""add extraction_started_at column

Revision ID: add_extraction_started_at
Revises: create_literature_file_history
Create Date: 2026-08-23 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_extraction_started_at"
down_revision: Union[str, None] = "create_literature_file_history"


def upgrade() -> None:
    op.add_column(
        "literature",
        sa.Column("extraction_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("literature", "extraction_started_at")
"""add extraction queued status

Revision ID: add_extraction_queued_status
Revises: (previous migration)
Create Date: 2026-08-22 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_extraction_queued_status"
down_revision: Union[str, None] = "add_soft_delete"


def upgrade() -> None:
    op.drop_constraint("lit_extraction_status_check", "literature", type_="check")
    op.create_check_constraint(
        "lit_extraction_status_check",
        "literature",
        "extraction_status IN ('pending','queued','processing','done','done_no_data','failed')",
    )


def downgrade() -> None:
    op.drop_constraint("lit_extraction_status_check", "literature", type_="check")
    op.create_check_constraint(
        "lit_extraction_status_check",
        "literature",
        "extraction_status IN ('pending','processing','done','done_no_data','failed')",
    )
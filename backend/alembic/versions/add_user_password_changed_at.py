"""add password_changed_at column to user table

Revision ID: add_user_password_changed_at
Revises: add_audit_log_entity_columns
Create Date: 2026-08-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_user_password_changed_at"
down_revision: Union[str, None] = "add_audit_log_entity_columns"


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "password_changed_at")
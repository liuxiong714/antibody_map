"""add audit_log entity columns

Revision ID: add_audit_log_entity_columns
Revises: add_audit_log
Create Date: 2026-08-24 08:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_audit_log_entity_columns"
down_revision: Union[str, None] = "add_audit_log"


def upgrade() -> None:
    # 为数据点等自定义实体的变更审计补充结构列（便于按实体过滤/回滚）
    op.add_column("audit_log", sa.Column("entity_type", sa.String(length=50), nullable=True))
    op.add_column("audit_log", sa.Column("entity_id", sa.String(length=100), nullable=True))
    op.add_column("audit_log", sa.Column("old_value", sa.Text(), nullable=True))
    op.add_column("audit_log", sa.Column("new_value", sa.Text(), nullable=True))
    op.create_index("ix_audit_log_entity_type", "audit_log", ["entity_type"])
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_entity_id", table_name="audit_log")
    op.drop_index("ix_audit_log_entity_type", table_name="audit_log")
    op.drop_column("audit_log", "new_value")
    op.drop_column("audit_log", "old_value")
    op.drop_column("audit_log", "entity_id")
    op.drop_column("audit_log", "entity_type")
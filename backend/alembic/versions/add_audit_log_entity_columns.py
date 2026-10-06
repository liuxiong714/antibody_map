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
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS entity_type VARCHAR(50)")
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS entity_id VARCHAR(100)")
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS old_value TEXT")
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS new_value TEXT")
    op.create_index("ix_audit_log_entity_type", "audit_log", ["entity_type"], if_not_exists=True)
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_audit_log_entity_id", table_name="audit_log")
    op.drop_index("ix_audit_log_entity_type", table_name="audit_log")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS new_value")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS old_value")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS entity_id")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS entity_type")
"""add soft-delete fields (deleted_at, deleted_by) to literature

Revision ID: add_soft_delete
Revises: add_report_template
Create Date: 2026-08-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_soft_delete'
down_revision: Union[str, None] = 'add_report_template'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE")
    op.create_index('ix_lit_deleted_at', 'literature', ['deleted_at'], if_not_exists=True)
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS deleted_by sa.Uuid()")


def downgrade() -> None:
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS deleted_by")
    op.drop_index('ix_lit_deleted_at', if_exists=True)
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS deleted_at")
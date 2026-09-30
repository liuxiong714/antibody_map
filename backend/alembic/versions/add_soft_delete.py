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
    op.add_column('literature', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_lit_deleted_at', 'literature', ['deleted_at'])
    op.add_column('literature', sa.Column('deleted_by', sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column('literature', 'deleted_by')
    op.drop_index('ix_lit_deleted_at')
    op.drop_column('literature', 'deleted_at')
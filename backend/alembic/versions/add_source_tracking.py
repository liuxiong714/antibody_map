"""add_source_tracking

Revision ID: add_source_tracking
Revises: 94cbbc6f286f
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_source_tracking'
down_revision: Union[str, Sequence[str], None] = '94cbbc6f286f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add source_page and source_context fields for data provenance tracking."""
    # Add source_page column (页码)
    op.add_column('data_point', sa.Column('source_page', sa.Integer(), nullable=True))
    
    # Add source_context column (原文片段)
    op.add_column('data_point', sa.Column('source_context', sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove source tracking fields."""
    op.drop_column('data_point', 'source_context')
    op.drop_column('data_point', 'source_page')
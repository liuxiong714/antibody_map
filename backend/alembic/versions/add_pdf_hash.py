"""add_pdf_hash

Revision ID: add_pdf_hash
Revises: add_source_tracking
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_pdf_hash'
down_revision: Union[str, Sequence[str], None] = 'add_source_tracking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add pdf_hash column to literature table for duplicate detection."""
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS pdf_hash VARCHAR(64)")
    op.create_index('idx_lit_pdf_hash', 'literature', ['pdf_hash'], unique=False, if_not_exists=True)


def downgrade() -> None:
    """Remove pdf_hash column."""
    op.drop_index('idx_lit_pdf_hash', table_name='literature')
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS pdf_hash")

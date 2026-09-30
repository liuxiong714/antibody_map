"""add_precise_grounding

Revision ID: add_precise_grounding
Revises: add_monitored_folder
Create Date: 2026-08-04

Adds precise character-level source grounding fields and schema constraint columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'add_precise_grounding'
down_revision: Union[str, Sequence[str], None] = 'add_monitored_folder'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add precise character-level grounding and schema enforcement fields."""
    # Character-level source interval in full document text
    op.add_column('data_point', sa.Column('source_char_start', sa.Integer(), nullable=True))
    op.add_column('data_point', sa.Column('source_char_end', sa.Integer(), nullable=True))
    # Whether the extraction was successfully grounded back to the original text
    op.add_column('data_point', sa.Column('is_grounded', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Timestamp for last update
    op.add_column('data_point', sa.Column(
        'updated_at',
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text('(CURRENT_TIMESTAMP)')
    ))


def downgrade() -> None:
    """Remove grounding enhancement columns."""
    op.drop_column('data_point', 'updated_at')
    op.drop_column('data_point', 'is_grounded')
    op.drop_column('data_point', 'source_char_end')
    op.drop_column('data_point', 'source_char_start')

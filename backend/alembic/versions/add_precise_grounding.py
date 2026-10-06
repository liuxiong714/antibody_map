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
    op.execute("ALTER TABLE data_point ADD COLUMN IF NOT EXISTS source_char_start INTEGER")
    op.execute("ALTER TABLE data_point ADD COLUMN IF NOT EXISTS source_char_end INTEGER")
    # Whether the extraction was successfully grounded back to the original text
    op.execute("ALTER TABLE data_point ADD COLUMN IF NOT EXISTS is_grounded BOOLEAN DEFAULT FALSE NOT NULL")
    # Timestamp for last update
    op.execute("ALTER TABLE data_point ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL")


def downgrade() -> None:
    """Remove grounding enhancement columns."""
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS is_grounded")
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS source_char_end")
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS source_char_start")

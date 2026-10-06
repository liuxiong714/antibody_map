"""add_report_llm_model

Revision ID: add_report_llm_model
Revises: add_monitored_folder
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_report_llm_model'
down_revision: Union[str, Sequence[str], None] = 'add_llm_token_usage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add llm_model column to report table."""
    op.execute("ALTER TABLE report ADD COLUMN IF NOT EXISTS llm_model VARCHAR(100)")


def downgrade() -> None:
    """Remove llm_model column."""
    op.execute("ALTER TABLE report DROP COLUMN IF EXISTS llm_model")
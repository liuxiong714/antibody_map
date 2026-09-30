"""add_report_data_snapshot_hash

Revision ID: add_report_data_snapshot_hash
Revises: add_extraction_robustness_fields
Create Date: 2026-08-24 21:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_report_data_snapshot_hash'
down_revision: Union[str, Sequence[str], None] = 'add_extraction_robustness_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add data_snapshot_hash column to report table (F38 可复现性)."""
    op.add_column(
        'report',
        sa.Column('data_snapshot_hash', sa.String(length=64), nullable=True),
    )
    op.create_index('ix_report_data_snapshot_hash', 'report', ['data_snapshot_hash'])


def downgrade() -> None:
    """Remove data_snapshot_hash column."""
    op.drop_index('ix_report_data_snapshot_hash', table_name='report')
    op.drop_column('report', 'data_snapshot_hash')
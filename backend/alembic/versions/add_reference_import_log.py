"""add reference_import_log table

Revision ID: add_reference_import_log
Revises: add_extraction_queued_status
Create Date: 2026-08-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_reference_import_log'
down_revision: Union[str, None] = 'add_extraction_queued_status'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reference_import_log',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_name', sa.String(500), nullable=False),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('imported_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('operator_name', sa.String(100), nullable=False),
        sa.Column('fmt', sa.String(20), nullable=False, server_default='auto'),
        sa.Column('operator_id', sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ref_import_log_imported_at', 'reference_import_log', ['imported_at'])
    op.create_index('ix_ref_import_log_file_name', 'reference_import_log', ['file_name'])


def downgrade() -> None:
    op.drop_index('ix_ref_import_log_file_name')
    op.drop_index('ix_ref_import_log_imported_at')
    op.drop_table('reference_import_log')
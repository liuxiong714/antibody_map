"""add_monitored_folder

Revision ID: add_monitored_folder
Revises: add_pdf_hash
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_monitored_folder'
down_revision: Union[str, Sequence[str], None] = 'add_pdf_hash'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create monitored_folder and monitored_file tables."""
    op.create_table(
        'monitored_folder',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('folder_path', sa.String(500), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('scan_interval_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.Column('file_extensions', sa.Text(), nullable=True),
        sa.Column('auto_extract', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('extraction_model', sa.String(100), nullable=True),
        sa.Column('extraction_api_key', sa.String(200), nullable=True),
        sa.Column('extraction_base_url', sa.String(300), nullable=True),
        sa.Column('last_scan_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_scan_new_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_imported_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='idle'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.CheckConstraint("status IN ('idle','scanning','error')", name='mf_status_check'),
    )

    op.create_table(
        'monitored_file',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('folder_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('monitored_folder.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('file_name', sa.String(300), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('file_mtime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('literature_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.CheckConstraint(
            "status IN ('pending','imported','skipped_duplicate','failed')",
            name='mf_file_status_check',
        ),
    )
    op.create_index('ix_monitored_file_folder_id', 'monitored_file', ['folder_id'])
    op.create_index('ix_monitored_file_file_hash', 'monitored_file', ['file_hash'])
    op.create_index('ix_monitored_file_literature_id', 'monitored_file', ['literature_id'])


def downgrade() -> None:
    """Drop monitored_file and monitored_folder tables."""
    op.drop_index('ix_monitored_file_literature_id', table_name='monitored_file')
    op.drop_index('ix_monitored_file_file_hash', table_name='monitored_file')
    op.drop_index('ix_monitored_file_folder_id', table_name='monitored_file')
    op.drop_table('monitored_file')
    op.drop_table('monitored_folder')

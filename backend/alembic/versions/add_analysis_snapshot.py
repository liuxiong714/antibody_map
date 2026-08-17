"""add analysis_snapshot table

Revision ID: add_analysis_snapshot
Revises: add_dp_quality_fields
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'add_analysis_snapshot'
down_revision: Union[str, None] = 'add_dp_quality_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analysis_snapshot',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('module', sa.String(length=50), nullable=False),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('data_hash', sa.String(length=32), nullable=False),
        sa.Column('response_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Index('ix_snapshot_module_hash', 'module', 'data_hash'),
        sa.Index('ix_analysis_snapshot_module', 'module'),
        sa.Index('ix_analysis_snapshot_data_hash', 'data_hash'),
    )


def downgrade() -> None:
    op.drop_table('analysis_snapshot')

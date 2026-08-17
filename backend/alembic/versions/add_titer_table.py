"""add titer_table model

Revision ID: add_titer_table
Revises: add_analysis_snapshot
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'add_titer_table'
down_revision: Union[str, None] = 'add_analysis_snapshot'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'titer_table',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('literature_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('literature.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('assay_type', sa.String(length=20), nullable=False, index=True),
        sa.Column('ref_antisera', postgresql.JSON(astext_type=sa.Text()), nullable=True,
                  comment='抗血清名称列表'),
        sa.Column('antigens', postgresql.JSON(astext_type=sa.Text()), nullable=True,
                  comment='抗原名称列表'),
        sa.Column('titers', postgresql.JSON(astext_type=sa.Text()), nullable=True,
                  comment='滴度矩阵（行=抗原，列=抗血清）'),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('quality_score', sa.Integer(), nullable=True),
        sa.Column('source_page', sa.Integer(), nullable=True),
        sa.Column('source_context', sa.String(length=500), nullable=True),
        sa.Column('confidence', sa.String(length=10), nullable=False, server_default='medium'),
        sa.Column('review_status', sa.String(length=20), nullable=False, server_default='pending', index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("assay_type IN ('hi', 'vnt', 'elisa')",
                           name='titer_table_assay_type_check'),
        sa.CheckConstraint("review_status IN ('pending', 'approved', 'rejected')",
                           name='titer_table_review_status_check'),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name='titer_table_quality_score_check',
        ),
    )


def downgrade() -> None:
    op.drop_table('titer_table')
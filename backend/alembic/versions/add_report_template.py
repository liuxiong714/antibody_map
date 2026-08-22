"""add report_template table

Revision ID: add_report_template
Revises: add_data_point_review_fields
Create Date: 2026-08-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_report_template'
down_revision: Union[str, None] = 'add_data_point_review_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'report_template',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('report_type', sa.String(length=30), nullable=False, server_default='antibody_analysis'),
        sa.Column('sections', sa.JSON(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('desc', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(
            "report_type IN ('antibody_analysis','vaccination_strategy')",
            name='report_template_type_check',
        ),
    )


def downgrade() -> None:
    op.drop_table('report_template')
"""add quality grading fields to data_point

Revision ID: add_dp_quality_fields
Revises: add_dp_composite_idx
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_dp_quality_fields'
down_revision: Union[str, None] = 'add_dp_composite_idx'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 质量分级（0-100 分 + A/B/C 三级 + 调查级别）
    op.add_column('data_point', sa.Column('quality_score', sa.Integer(), nullable=True))
    op.add_column('data_point', sa.Column('quality_grade', sa.String(length=1), nullable=True))
    op.add_column('data_point', sa.Column('estimate_grade', sa.String(length=20), nullable=True))
    # 索引：meta 合并按质量等级过滤、审核后打分查询
    op.create_index('ix_dp_quality_grade', 'data_point', ['quality_grade'])
    op.create_index('ix_dp_quality_score', 'data_point', ['quality_score'])


def downgrade() -> None:
    op.drop_index('ix_dp_quality_score', table_name='data_point')
    op.drop_index('ix_dp_quality_grade', table_name='data_point')
    op.drop_column('data_point', 'estimate_grade')
    op.drop_column('data_point', 'quality_grade')
    op.drop_column('data_point', 'quality_score')

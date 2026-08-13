"""add composite indexes for data_point

Revision ID: add_dp_composite_idx
Revises: add_tags
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'add_dp_composite_idx'
down_revision: Union[str, None] = 'add_tags'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 复合索引：地图/分析最常用的组合过滤条件 (review_status, disease, data_type)
    op.create_index(
        'ix_dp_review_disease_type',
        'data_point',
        ['review_status', 'disease', 'data_type'],
    )
    # 复合索引：按文献提取/删除数据点时加速
    op.create_index(
        'ix_dp_lit_review',
        'data_point',
        ['literature_id', 'review_status'],
    )


def downgrade() -> None:
    op.drop_index('ix_dp_lit_review', table_name='data_point')
    op.drop_index('ix_dp_review_disease_type', table_name='data_point')
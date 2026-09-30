"""add review comment / reviewer / reviewed_at to data_point

Revision ID: add_data_point_review_fields
Revises: add_local_model_config
Create Date: 2026-08-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_data_point_review_fields'
down_revision: Union[str, None] = 'add_local_model_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 审核意见（可空）
    op.add_column('data_point', sa.Column('review_comment', sa.Text(), nullable=True))
    # 审核人（可空，外键到 user.id；用户被删除时置空而非级联删除数据点）
    op.add_column('data_point', sa.Column('reviewer_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_data_point_reviewer_user', 'data_point', 'user',
        ['reviewer_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_dp_reviewer_id', 'data_point', ['reviewer_id'])
    # 审核时间（可空）
    op.add_column('data_point', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_dp_reviewed_at', 'data_point', ['reviewed_at'])


def downgrade() -> None:
    op.drop_index('ix_dp_reviewed_at', table_name='data_point')
    op.drop_column('data_point', 'reviewed_at')
    op.drop_index('ix_dp_reviewer_id', table_name='data_point')
    op.drop_constraint('fk_data_point_reviewer_user', 'data_point', type_='foreignkey')
    op.drop_column('data_point', 'reviewer_id')
    op.drop_column('data_point', 'review_comment')
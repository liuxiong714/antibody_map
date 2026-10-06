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
    op.execute("ALTER TABLE data_point ADD COLUMN IF NOT EXISTS quality_score INTEGER")
    op.execute("ALTER TABLE data_point ADD COLUMN IF NOT EXISTS quality_grade VARCHAR(1)")
    op.execute("ALTER TABLE data_point ADD COLUMN IF NOT EXISTS estimate_grade VARCHAR(20)")
    # 索引：meta 合并按质量等级过滤、审核后打分查询
    op.create_index('ix_dp_quality_grade', 'data_point', ['quality_grade'], if_not_exists=True)
    op.create_index('ix_dp_quality_score', 'data_point', ['quality_score'], if_not_exists=True)


def downgrade() -> None:
    op.drop_index('ix_dp_quality_score', table_name='data_point', if_exists=True)
    op.drop_index('ix_dp_quality_grade', table_name='data_point', if_exists=True)
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS estimate_grade")
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS quality_grade")
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS quality_score")

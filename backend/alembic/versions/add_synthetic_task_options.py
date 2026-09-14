"""add_synthetic_task_options

为 synthetic_task 增加 文献载体（output_format）与 是否含表格（include_table）两列，
支撑「AI 提取准确度自测」对 PDF 载体与表格形式的评估。仅新增列，不影响现有数据。

Revision ID: add_synthetic_task_options
Revises: add_synthetic_task
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_synthetic_task_options'
down_revision: Union[str, Sequence[str], None] = 'add_synthetic_task'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('synthetic_task', sa.Column('output_format', sa.String(10), server_default='text'))
    op.add_column('synthetic_task', sa.Column('include_table', sa.Boolean(), server_default=sa.text('true')))


def downgrade() -> None:
    op.drop_column('synthetic_task', 'include_table')
    op.drop_column('synthetic_task', 'output_format')
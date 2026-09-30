"""add_synthetic_task

新增合成文献自测任务表（synthetic_task），支撑「AI 提取准确度自测」功能。
仅新增表，不修改任何现有表结构，不影响历史数据。

Revision ID: add_synthetic_task
Revises: add_kg_tables
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_synthetic_task'
down_revision: Union[str, Sequence[str], None] = 'add_kg_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'synthetic_task',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('disease', sa.String(100), nullable=False),
        sa.Column('n_literatures', sa.Integer, server_default='20'),
        sa.Column('points_per_literature', sa.Integer, server_default='20'),
        sa.Column('generator_model', sa.String(100), nullable=False),
        sa.Column('extractor_model', sa.String(100), nullable=True),
        sa.Column('noise_ratio', sa.Float, server_default='0.2'),
        sa.Column('seed', sa.Integer, server_default='42'),
        sa.Column('status', sa.String(20), server_default='queued'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('gt_json', postgresql.JSON, nullable=True),
        sa.Column('report_json', postgresql.JSON, nullable=True),
        sa.Column('literature_ids', postgresql.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_synthetic_task_status', 'synthetic_task', ['status'])


def downgrade() -> None:
    op.drop_table('synthetic_task')
"""add_synthetic_task_stage_timestamps

为 synthetic_task 增加 4 个阶段计时时间戳列（generation_started_at / generated_at /
extraction_started_at / extracted_at），用于「AI 提取准确度自测」任务的耗时展示。
仅新增列，不影响现有数据。

Revision ID: add_synthetic_task_stage_timestamps
Revises: add_synthetic_task_options
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'add_synthetic_task_stage_timestamps'
down_revision: Union[str, Sequence[str], None] = 'add_synthetic_task_options'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 使用 IF NOT EXISTS：开发库可能已手动 ALTER 过，避免重复建列报错。
    op.execute('ALTER TABLE synthetic_task '
               'ADD COLUMN IF NOT EXISTS generation_started_at timestamptz, '
               'ADD COLUMN IF NOT EXISTS generated_at timestamptz, '
               'ADD COLUMN IF NOT EXISTS extraction_started_at timestamptz, '
               'ADD COLUMN IF NOT EXISTS extracted_at timestamptz')


def downgrade() -> None:
    op.execute('ALTER TABLE synthetic_task '
               'DROP COLUMN IF EXISTS extracted_at, '
               'DROP COLUMN IF EXISTS extraction_started_at, '
               'DROP COLUMN IF EXISTS generated_at, '
               'DROP COLUMN IF EXISTS generation_started_at')
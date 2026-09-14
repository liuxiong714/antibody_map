"""synthetic multi_model fields + synthetic_extraction table

AI 提取准确度自测扩展：
1) synthetic_task 增加 literature_source / reference_model / models 字段；
2) 新建 synthetic_extraction 表，独立存储多模型提取结果，避免污染真实文献 data_point。

仅新增列与表，不影响现有数据。

Revision ID: add_synthetic_multi_model
Revises: add_synthetic_task_stage_timestamps
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'add_synthetic_multi_model'
down_revision: Union[str, Sequence[str], None] = 'add_synthetic_task_stage_timestamps'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE synthetic_task '
               'ADD COLUMN IF NOT EXISTS literature_source VARCHAR(10) DEFAULT \'generated\' NOT NULL, '
               'ADD COLUMN IF NOT EXISTS reference_model VARCHAR(100), '
               'ADD COLUMN IF NOT EXISTS models JSON')
    op.execute(
        'CREATE TABLE IF NOT EXISTS synthetic_extraction ('
        ' id UUID PRIMARY KEY DEFAULT gen_random_uuid(),'
        ' task_id UUID NOT NULL,'
        ' literature_id UUID NOT NULL,'
        ' model VARCHAR(100) NOT NULL,'
        ' status VARCHAR(20) NOT NULL DEFAULT \'pending\','
        ' points_json JSON,'
        ' error VARCHAR(2000),'
        ' created_at TIMESTAMPTZ NOT NULL DEFAULT now(),'
        ' updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),'
        ' CONSTRAINT uq_syn_extr_task_lit_model UNIQUE (task_id, literature_id, model)'
        ')'
    )
    op.execute('CREATE INDEX IF NOT EXISTS ix_synthetic_extraction_task_id ON synthetic_extraction (task_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_synthetic_extraction_status ON synthetic_extraction (status)')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS synthetic_extraction')
    op.execute('ALTER TABLE synthetic_task '
               'DROP COLUMN IF EXISTS models, '
               'DROP COLUMN IF EXISTS reference_model, '
               'DROP COLUMN IF EXISTS literature_source')
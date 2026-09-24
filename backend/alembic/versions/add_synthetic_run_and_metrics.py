"""synthetic_run 表 + 多模型批量评测扩展字段

AI 提取自测扩展（编组 × 多模型批量评测）：
1) 新建 synthetic_run 表：每个模型跑一遍全部文献即一条运行记录，
   以 run_index + 起止时间区分同一模型的多次运行，保留全部历史；
2) synthetic_extraction 增加 run_id 与效率指标列，唯一约束从
   (task_id, literature_id, model) 改为 (run_id, literature_id)，
   使同一模型的多次运行结果各自保留、互不覆盖；
3) synthetic_task 增加 tag_id（记录测试文献来源编组）。

仅新增表/列并放宽唯一约束，不删除数据、不改现有列类型。

Revision ID: add_synthetic_run_and_metrics
Revises: add_pathogen_monitoring
Create Date: 2026-09-23
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'add_synthetic_run_and_metrics'
down_revision: Union[str, Sequence[str], None] = 'add_pathogen_monitoring'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 运行记录表
    op.execute(
        'CREATE TABLE IF NOT EXISTS synthetic_run ('
        ' id UUID PRIMARY KEY DEFAULT gen_random_uuid(),'
        ' task_id UUID NOT NULL,'
        ' model VARCHAR(100) NOT NULL,'
        ' run_index INTEGER NOT NULL DEFAULT 1,'
        ' status VARCHAR(20) NOT NULL DEFAULT \'pending\','
        ' literatures_total INTEGER NOT NULL DEFAULT 0,'
        ' literatures_done INTEGER NOT NULL DEFAULT 0,'
        ' literatures_failed INTEGER NOT NULL DEFAULT 0,'
        ' peak_vram_mb INTEGER,'
        ' summary_json JSON,'
        ' started_at TIMESTAMPTZ,'
        ' finished_at TIMESTAMPTZ,'
        ' duration_seconds DOUBLE PRECISION,'
        ' created_at TIMESTAMPTZ NOT NULL DEFAULT now(),'
        ' updated_at TIMESTAMPTZ NOT NULL DEFAULT now()'
        ')'
    )
    op.execute('CREATE INDEX IF NOT EXISTS ix_synthetic_run_task_id ON synthetic_run (task_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_synthetic_run_model ON synthetic_run (model)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_synthetic_run_status ON synthetic_run (status)')

    # 2) 提取结果表扩展（全部可空，兼容历史数据）
    op.execute(
        'ALTER TABLE synthetic_extraction '
        'ADD COLUMN IF NOT EXISTS run_id UUID, '
        'ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ, '
        'ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ, '
        'ADD COLUMN IF NOT EXISTS duration_ms INTEGER, '
        'ADD COLUMN IF NOT EXISTS first_token_ms INTEGER, '
        'ADD COLUMN IF NOT EXISTS gen_tokens INTEGER, '
        'ADD COLUMN IF NOT EXISTS tokens_per_sec DOUBLE PRECISION, '
        'ADD COLUMN IF NOT EXISTS json_ok BOOLEAN, '
        'ADD COLUMN IF NOT EXISTS points_total INTEGER, '
        'ADD COLUMN IF NOT EXISTS grounded_points INTEGER'
    )
    op.execute('CREATE INDEX IF NOT EXISTS ix_synthetic_extraction_run_id ON synthetic_extraction (run_id)')
    # 唯一约束切换：旧约束按 (task,lit,model) 唯一会阻止同模型多次运行，需放宽为 (run_id,lit)
    op.execute('ALTER TABLE synthetic_extraction DROP CONSTRAINT IF EXISTS uq_syn_extr_task_lit_model')
    op.execute(
        'DO $$ BEGIN '
        'IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = \'uq_syn_extr_run_lit\') THEN '
        'ALTER TABLE synthetic_extraction ADD CONSTRAINT uq_syn_extr_run_lit UNIQUE (run_id, literature_id); '
        'END IF; END $$'
    )

    # 3) 任务表增加来源编组
    op.execute('ALTER TABLE synthetic_task ADD COLUMN IF NOT EXISTS tag_id UUID')


def downgrade() -> None:
    op.execute('ALTER TABLE synthetic_task DROP COLUMN IF EXISTS tag_id')
    op.execute('ALTER TABLE synthetic_extraction DROP CONSTRAINT IF EXISTS uq_syn_extr_run_lit')
    op.execute(
        'DO $$ BEGIN '
        'IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = \'uq_syn_extr_task_lit_model\') THEN '
        'ALTER TABLE synthetic_extraction ADD CONSTRAINT uq_syn_extr_task_lit_model '
        'UNIQUE (task_id, literature_id, model); '
        'END IF; END $$'
    )
    op.execute(
        'ALTER TABLE synthetic_extraction '
        'DROP COLUMN IF EXISTS grounded_points, '
        'DROP COLUMN IF EXISTS points_total, '
        'DROP COLUMN IF EXISTS json_ok, '
        'DROP COLUMN IF EXISTS tokens_per_sec, '
        'DROP COLUMN IF EXISTS gen_tokens, '
        'DROP COLUMN IF EXISTS first_token_ms, '
        'DROP COLUMN IF EXISTS duration_ms, '
        'DROP COLUMN IF EXISTS finished_at, '
        'DROP COLUMN IF EXISTS started_at, '
        'DROP COLUMN IF EXISTS run_id'
    )
    op.execute('DROP TABLE IF EXISTS synthetic_run')
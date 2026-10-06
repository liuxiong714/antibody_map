"""add extraction robustness fields (F13/F14/F17/F19)

为文献提取管线的安全/健壮性改造新增字段：
- literature.extraction_generation : 提取代数（幂等写库 CAS 用）
- literature.worker_heartbeat      : worker 心跳时间戳（超时回收区分长任务与真卡死）
- data_point.truncation            : 截断值标记（"<"/">"）
- data_point.llm_raw_snapshot      : LLM 原始输出快照（diff 展示用）

Revision ID: add_extraction_robustness_fields
Revises: add_goal_threshold_config
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# revision identifiers, used by Alembic.
revision: str = 'add_extraction_robustness_fields'
down_revision: Union[str, Sequence[str], None] = 'add_goal_threshold_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- literature：F13 提取代数 + F14 worker 心跳 ----
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS extraction_generation INTEGER DEFAULT 0 NOT NULL")
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS worker_heartbeat TIMESTAMP WITH TIME ZONE")
    op.create_index(
        op.f('ix_lit_worker_heartbeat'), 'literature', ['worker_heartbeat'],
        if_not_exists=True,
    )

    # ---- data_point：F17 LLM 原始快照 + F19 截断标记 ----
    op.execute("ALTER TABLE data_point ADD COLUMN IF NOT EXISTS llm_raw_snapshot JSONB")
    op.execute("ALTER TABLE data_point ADD COLUMN IF NOT EXISTS truncation VARCHAR(10)")


def downgrade() -> None:
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS truncation")
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS llm_raw_snapshot")

    op.drop_index(op.f('ix_lit_worker_heartbeat'), table_name='literature', if_exists=True)
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS worker_heartbeat")
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS extraction_generation")

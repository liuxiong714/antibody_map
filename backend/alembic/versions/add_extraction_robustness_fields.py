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
    op.add_column(
        'literature',
        sa.Column('extraction_generation', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'literature',
        sa.Column('worker_heartbeat', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f('ix_lit_worker_heartbeat'), 'literature', ['worker_heartbeat'],
        if_not_exists=True,
    )

    # ---- data_point：F17 LLM 原始快照 + F19 截断标记 ----
    op.add_column(
        'data_point',
        sa.Column('llm_raw_snapshot', JSON, nullable=True),
    )
    op.add_column(
        'data_point',
        sa.Column('truncation', sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('data_point', 'truncation')
    op.drop_column('data_point', 'llm_raw_snapshot')

    op.drop_index(op.f('ix_lit_worker_heartbeat'), table_name='literature', if_exists=True)
    op.drop_column('literature', 'worker_heartbeat')
    op.drop_column('literature', 'extraction_generation')

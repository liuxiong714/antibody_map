"""merge_all_heads: 合并所有现存 head 成单一 head

B6 前置步骤。当前迁移链存在 4 个 head:
  1. add_extraction_history_processing_status  (经过 add_multidomain_extension mergepoint)
  2. fix_migration_chain                       (A8 新加，挂 add_extraction_history_timing_detail)
  3. add_synthetic_run_and_metrics             (挂 add_pathogen_monitoring)

三者最终都回溯到同一个 root (widen_alembic_version_num / init migration)。
env.py 的 create_all 已幂等建齐 25 张表，未执行的 ALTER/ADD COLUMN 迁移脚
本在 DB 上重跑均安全（IF NOT EXISTS 或幂等）。

此 merge 之后下一个迁移（add_kg_triple_source）将拥有单一父 revision。

Revision ID: merge_all_heads
Revises: add_extraction_history_processing_status, fix_migration_chain, add_synthetic_run_and_metrics
Create Date: 2026-09-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'merge_all_heads'
down_revision: Union[str, Sequence[str], None] = (
    'add_extraction_history_processing_status',
    'fix_migration_chain',
    'add_synthetic_run_and_metrics',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass  # mergepoint 本身无 DDL，仅声明多父 revision 合并


def downgrade() -> None:
    pass  # mergepoint 无法简单反降级

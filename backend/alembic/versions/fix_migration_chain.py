"""fix_migration_chain: 补 kg_triple.review_status 列（幂等）

A8 修复：恢复 alembic 迁移链的最后一环。
env.py 已改为先 Base.metadata.create_all 兜底再跑 alembic upgrade，
但 kg_triple.review_status 在模型里存在却从未进入任何迁移脚本，
靠 _ensure_tables 的 ALTER TABLE 临时修补。本迁移把它正式写入迁移链，
使"全新空库 -> alembic upgrade head -> 全部 25 张表 + 完整列"成立。

disease_dict / kg_qa_log 两张表完全无迁移覆盖，
但 env.py 的 create_all 兜底已能正确建表，无需单独迁移。

Revision ID: fix_migration_chain
Revises: add_extraction_history_timing_detail
Create Date: 2026-09-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fix_migration_chain'
down_revision: Union[str, Sequence[str], None] = 'add_extraction_history_timing_detail'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. kg_triple.review_status —— 模型有但迁移无
    #    对已有库：列已由 _ensure_tables 补齐，IF NOT EXISTS 跳过
    #    对空库：env.py 的 create_all 先建表，这里补列（若 create_all 未覆盖该列）
    op.execute(
        "ALTER TABLE kg_triple ADD COLUMN IF NOT EXISTS "
        "review_status VARCHAR(16) NOT NULL DEFAULT 'pending'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kg_triple_review_status "
        "ON kg_triple (review_status)"
    )


def downgrade() -> None:
    # 可逆：删列+索引（仅限全新迁移链场景）
    op.execute("DROP INDEX IF EXISTS ix_kg_triple_review_status")
    op.execute("ALTER TABLE kg_triple DROP COLUMN IF EXISTS review_status")

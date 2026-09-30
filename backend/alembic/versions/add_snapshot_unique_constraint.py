"""add unique constraint on analysis_snapshot(module, data_hash, params)

Revision ID: add_snapshot_unique_constraint
Revises: add_user_password_changed_at
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'add_snapshot_unique_constraint'
down_revision: Union[str, None] = 'add_user_password_changed_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 清理既有重复行：对同 (module, data_hash, params) 仅保留 created_at 最新的一条，
    #    避免后续唯一索引因现存重复行而创建失败。
    op.execute(
        """
        DELETE FROM analysis_snapshot a
        USING analysis_snapshot b
        WHERE a.created_at < b.created_at
          AND a.module = b.module
          AND a.data_hash = b.data_hash
          AND a.params IS NOT DISTINCT FROM b.params
        """
    )
    # 2. 并发安全的去重复用唯一约束：同模块 + 同数据指纹 + 同完整过滤参数
    op.create_unique_constraint(
        "uq_snapshot_identity",
        "analysis_snapshot",
        ["module", "data_hash", "params"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_snapshot_identity", "analysis_snapshot", type_="unique")
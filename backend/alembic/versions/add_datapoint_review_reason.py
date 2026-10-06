"""add_datapoint_review_reason

V2-06: DataPoint 加 review_reason — 标记 rejected 产生的原因。

原 duplicates.py:350 合并冲突时写入 review_status='rejected'，
并尝试写 review_reason（hasattr(s_dp, 'review_reason')），
但 DataPoint 模型无此列 → hasattr 恒 False → 理由全部丢失。
导致合并产生的 rejected 点与"人工驳回"语义混淆，无法区分。

取值示例: merged_conflict_prefer_target / merged_conflict_prefer_source
幂等: ADD COLUMN IF NOT EXISTS。
"""
from __future__ import annotations

from alembic import op

revision = "add_datapoint_review_reason"
down_revision = "add_datapoint_denominator_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE data_point ADD COLUMN IF NOT EXISTS review_reason VARCHAR(64) DEFAULT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS review_reason")

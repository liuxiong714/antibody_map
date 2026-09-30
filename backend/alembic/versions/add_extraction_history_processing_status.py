"""allow extraction_history status 'processing'

Revision ID: add_extraction_history_processing_status
Revises: add_multidomain_extension
Create Date: 2026-09-21

F21 预创建 ExtractionHistory 占位行时使用 status='processing'（提交前回填为
success/no_data/failed）。原 check 约束仅允许三个终态，导致占位 INSERT 直接
违反约束（CheckViolationError）。本迁移将 'processing' 加入允许集合，
与 F21 代码语义保持一致；占位行在最终提交前必被覆盖，不存在持久化终态风险。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "add_extraction_history_processing_status"
down_revision: Union[str, Sequence[str], None] = "add_multidomain_extension"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the old check constraint and re-add it allowing 'processing'."""
    op.drop_constraint(
        "extraction_history_status_check",
        "extraction_history",
        type_="check",
    )
    op.create_check_constraint(
        "extraction_history_status_check",
        "extraction_history",
        "status IN ('success','no_data','failed','processing')",
    )


def downgrade() -> None:
    """Restore the original check constraint (three terminal states only)."""
    op.drop_constraint(
        "extraction_history_status_check",
        "extraction_history",
        type_="check",
    )
    op.create_check_constraint(
        "extraction_history_status_check",
        "extraction_history",
        "status IN ('success','no_data','failed')",
    )

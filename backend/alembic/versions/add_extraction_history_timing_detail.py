"""merge heads + add extraction_history.timing_detail

Revision ID: add_extraction_history_timing_detail
Revises: ('add_synthetic_run_and_metrics', 'add_extraction_history_processing_status')
Create Date: 2026-09-25

合并两个 head 分支，并在 extraction_history 表中新增 timing_detail 列，
存储 LLMClientMixin.get_timing_summary() 输出的效率指标详情：
- avg_first_token_ms: 平均首 token 延迟（ms）
- gen_seconds: decode 阶段总时长（秒）
- tokens_per_sec: 平均生成速度（tokens/s）
- completion_tokens: 累计生成 token 数
- calls: LLM 调用次数
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_extraction_history_timing_detail"
down_revision: Union[str, Sequence[str], None] = (
    "add_synthetic_run_and_metrics",
    "add_extraction_history_processing_status",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add timing_detail JSON column to extraction_history table."""
    op.add_column(
        "extraction_history",
        sa.Column(
            "timing_detail",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove timing_detail column from extraction_history table."""
    op.drop_column("extraction_history", "timing_detail")

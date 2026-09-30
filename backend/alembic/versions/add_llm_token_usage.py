"""add_llm_token_usage

Revision ID: add_llm_token_usage
Revises: add_estimate_hierarchy
Create Date: 2026-08-05

新增 LLM 提取的 token 用量与费用统计字段到 literature 表：
- llm_model_used: 实际使用的主模型名（调用次数最多的模型）
- prompt_tokens: 累计输入 token 数
- completion_tokens: 累计输出 token 数
- total_tokens: 累计总 token 数
- llm_cost_usd: 估算费用（美元）
- llm_call_count: LLM 调用次数
- llm_usage_detail: 按模型分项明细（JSON，可选，用于多模型场景）

这些字段在 AI 提取完成时写入，前端在文献详情页展示，
帮助用户了解每次提取的 token 消耗和费用。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'add_llm_token_usage'
down_revision: Union[str, Sequence[str], None] = 'add_estimate_hierarchy'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add LLM token usage columns to literature table."""
    # 主模型名（调用次数最多的模型）
    op.add_column('literature', sa.Column(
        'llm_model_used',
        sa.String(length=100),
        nullable=True,
    ))
    # 累计输入 token 数
    op.add_column('literature', sa.Column(
        'prompt_tokens',
        sa.Integer(),
        nullable=False,
        server_default='0',
    ))
    # 累计输出 token 数
    op.add_column('literature', sa.Column(
        'completion_tokens',
        sa.Integer(),
        nullable=False,
        server_default='0',
    ))
    # 累计总 token 数
    op.add_column('literature', sa.Column(
        'total_tokens',
        sa.Integer(),
        nullable=False,
        server_default='0',
    ))
    # 估算费用（美元，6 位小数）
    op.add_column('literature', sa.Column(
        'llm_cost_usd',
        sa.Numeric(precision=10, scale=6),
        nullable=False,
        server_default='0',
    ))
    # LLM 调用次数
    op.add_column('literature', sa.Column(
        'llm_call_count',
        sa.Integer(),
        nullable=False,
        server_default='0',
    ))
    # 按模型分项明细（JSON）
    op.add_column('literature', sa.Column(
        'llm_usage_detail',
        postgresql.JSON(astext_type=sa.Text()),
        nullable=True,
    ))


def downgrade() -> None:
    """Remove LLM token usage columns from literature table."""
    op.drop_column('literature', 'llm_usage_detail')
    op.drop_column('literature', 'llm_call_count')
    op.drop_column('literature', 'llm_cost_usd')
    op.drop_column('literature', 'total_tokens')
    op.drop_column('literature', 'completion_tokens')
    op.drop_column('literature', 'prompt_tokens')
    op.drop_column('literature', 'llm_model_used')

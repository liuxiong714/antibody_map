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
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS llm_model_used VARCHAR(100)")
    # 累计输入 token 数
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER DEFAULT 0 NOT NULL")
    # 累计输出 token 数
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS completion_tokens INTEGER DEFAULT 0 NOT NULL")
    # 累计总 token 数
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS total_tokens INTEGER DEFAULT 0 NOT NULL")
    # 估算费用（美元，6 位小数）
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS llm_cost_usd NUMERIC(10,6) DEFAULT 0 NOT NULL")
    # LLM 调用次数
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS llm_call_count INTEGER DEFAULT 0 NOT NULL")
    # 按模型分项明细（JSON）
    op.execute("ALTER TABLE literature ADD COLUMN IF NOT EXISTS llm_usage_detail JSONB")


def downgrade() -> None:
    """Remove LLM token usage columns from literature table."""
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS llm_usage_detail")
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS llm_call_count")
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS llm_cost_usd")
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS total_tokens")
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS completion_tokens")
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS prompt_tokens")
    op.execute("ALTER TABLE literature DROP COLUMN IF EXISTS llm_model_used")

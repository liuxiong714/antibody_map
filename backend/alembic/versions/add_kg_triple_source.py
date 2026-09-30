"""add_kg_triple_source: kg_triple 表加 source 列（extracted/computed）

B6 修复：区分"LLM 从文献中抽取的三元组"与"系统从数据点计算出来的三元组"。
前端 KG 画布/问答需据此区分可信度，默认 extracted（人工审查过）优先级更高。

列类型 VARCHAR(16)，默认 'extracted'，历史数据无需回填。
computed 来源暂时不用：当前 persist_triples 写入的全是 LLM 提取，
source='computed' 预留给后续 data_point→kg_triple 的自动合成管道。

Revision ID: add_kg_triple_source
Revises: merge_all_heads
Create Date: 2026-09-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'add_kg_triple_source'
down_revision: Union[str, Sequence[str], None] = 'merge_all_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等：IF NOT EXISTS 对已有列安全跳过
    op.execute(
        "ALTER TABLE kg_triple ADD COLUMN IF NOT EXISTS "
        "source VARCHAR(16) NOT NULL DEFAULT 'extracted'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kg_triple_source ON kg_triple (source)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kg_triple_source")
    op.execute("ALTER TABLE kg_triple DROP COLUMN IF EXISTS source")

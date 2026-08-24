"""add_title_norm_and_trgm

F21: literature.title_norm 生成列 + 索引
     - 与 Python normalize_title 完全对齐的 SQL 表达式（_validate_norm 已验证）
     - 查重精确匹配由全表扫描改为走 title_norm 索引
F22: pg_trgm GIN 索引（title/authors/journal）
     - 支持 ilike('%kw%') 子串检索走索引，替代索引失效的全表扫描

Revision ID: add_title_norm_and_trgm
Revises: add_snapshot_unique_constraint
Create Date: 2026-08-24 00:00:00.000000
"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_title_norm_and_trgm'
down_revision: Union[str, Sequence[str], None] = 'add_snapshot_unique_constraint'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic")

# 与 app/services/literature/_common.py::normalize_title 逐步骤对齐：
#   lower + strip -> 连字符(- – —)替换为空格 -> 去非\w\s字符 -> 压缩空白
TITLE_NORM_EXPR = (
    "regexp_replace(regexp_replace(regexp_replace(btrim(lower(title)), "
    "'[-–—]', ' ', 'g'), "
    "'[^\\w\\s]', '', 'g'), '\\s+', ' ', 'g')"
)


def upgrade() -> None:
    # ---- F22 前置：启用 pg_trgm 扩展 ----
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ---- F21：title_norm 生成列（STORED）+ 索引 ----
    op.add_column(
        "literature",
        sa.Column(
            "title_norm",
            sa.String(500),
            sa.Computed(TITLE_NORM_EXPR, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("idx_lit_title_norm"), "literature", ["title_norm"],
        if_not_exists=True,
    )

    # ---- F22：trgm GIN 索引，支撑 title/authors/journal 的 ilike('%kw%') ----
    op.create_index(
        op.f("idx_lit_title_trgm"), "literature", ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
        if_not_exists=True,
    )
    op.create_index(
        op.f("idx_lit_authors_trgm"), "literature", ["authors"],
        postgresql_using="gin",
        postgresql_ops={"authors": "gin_trgm_ops"},
        if_not_exists=True,
    )
    op.create_index(
        op.f("idx_lit_journal_trgm"), "literature", ["journal"],
        postgresql_using="gin",
        postgresql_ops={"journal": "gin_trgm_ops"},
        if_not_exists=True,
    )

    logger.info("title_norm 生成列+索引 与 pg_trgm GIN 三列索引创建完成")


def downgrade() -> None:
    op.drop_index(op.f("idx_lit_title_norm"), table_name="literature", if_exists=True)
    op.drop_index(op.f("idx_lit_journal_trgm"), table_name="literature", if_exists=True)
    op.drop_index(op.f("idx_lit_authors_trgm"), table_name="literature", if_exists=True)
    op.drop_index(op.f("idx_lit_title_trgm"), table_name="literature", if_exists=True)
    op.drop_column("literature", "title_norm")
    # 保留 pg_trgm 扩展不删除（可能被其他对象使用，删除成本高）

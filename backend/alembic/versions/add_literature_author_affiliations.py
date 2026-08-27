"""add_literature_author_affiliations

为 literature 增加 author_affiliations（作者单位）字段。

背景：P1-1 元数据提取增强——LLM 已从文献中提取 author_affiliations，
但 literature 表此前无此字段导致提取结果被丢弃。仅做增量加列，不触碰已有数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_literature_author_affiliations'
down_revision: Union[str, Sequence[str], None] = 'widen_alembic_version_num'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add author_affiliations (nullable) to literature."""
    op.add_column(
        'literature',
        sa.Column('author_affiliations', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop author_affiliations column."""
    op.drop_column('literature', 'author_affiliations')

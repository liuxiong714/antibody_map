"""widen_alembic_version_num

将 alembic_version.version_num 由 varchar(32) 加宽为 varchar(64)，
以容纳 revision id 较长的迁移（如 add_literature_author_affiliations，34 字符）。

背景：生产库 alembic_version 列宽为 32，而部分迁移 revision 超过 32 字符，
导致这些迁移在写入版本号时报 value too long for type character varying(32)。
本迁移仅加宽该列，不触碰任何业务数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'widen_alembic_version_num'
down_revision: Union[str, Sequence[str], None] = 'add_extraction_history_duration'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Widen alembic_version.version_num to varchar(64)."""
    op.alter_column(
        'alembic_version',
        'version_num',
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Revert alembic_version.version_num back to varchar(32)."""
    op.alter_column(
        'alembic_version',
        'version_num',
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
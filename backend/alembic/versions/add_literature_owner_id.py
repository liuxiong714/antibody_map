"""add_literature_owner_id

为 literature 增加 owner_id（文献归属人）字段。

背景：用于「按归属人终止 AI 提取」——普通用户只能终止自己归属文献的提取，
管理员可终止全部。仅做增量加列 + 索引，不触碰任何已有数据；存量行 owner_id 为空
（可视为共享文献，普通用户不可终止，管理员可）。

Revision ID: add_literature_owner_id
Revises: add_api_model_config_expires_at
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_literature_owner_id'
down_revision: Union[str, Sequence[str], None] = 'add_api_model_config_expires_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add owner_id (nullable) to literature."""
    op.add_column(
        'literature',
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index('ix_literature_owner_id', 'literature', ['owner_id'])


def downgrade() -> None:
    """Drop owner_id column and its index."""
    op.drop_index('ix_literature_owner_id', table_name='literature')
    op.drop_column('literature', 'owner_id')
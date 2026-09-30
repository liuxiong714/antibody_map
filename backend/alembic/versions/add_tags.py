"""add tags and literature_tag tables

Revision ID: add_tags
Revises: e1c07278aa97
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_tags'
down_revision: Union[str, None] = 'e1c07278aa97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建 tag 表
    op.create_table(
        'tag',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('color', sa.String(7), nullable=True, server_default='#1677ff'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_tag_name'),
    )
    op.create_index('ix_tag_name', 'tag', ['name'])

    # 创建 literature_tag 关联表
    op.create_table(
        'literature_tag',
        sa.Column('literature_id', sa.Uuid(), nullable=False),
        sa.Column('tag_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['literature_id'], ['literature.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('literature_id', 'tag_id'),
    )


def downgrade() -> None:
    op.drop_table('literature_tag')
    op.drop_index('ix_tag_name', table_name='tag')
    op.drop_table('tag')
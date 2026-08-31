"""add_kg_tables

创建知识图谱实体表（kg_entity）和关系表（kg_triple）。
仅新增表，不修改任何现有表结构，不影响历史数据。

Revision ID: add_kg_tables
Revises: add_literature_author_affiliations
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_kg_tables'
down_revision: Union[str, Sequence[str], None] = 'add_literature_author_affiliations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'kg_entity',
        sa.Column('id', sa.String(16), primary_key=True),
        sa.Column('entity_type', sa.String(32), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('attributes', postgresql.JSON, nullable=True),
        sa.Column('source_literature_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('merged_into', sa.String(16), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['source_literature_id'], ['literature.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['merged_into'], ['kg_entity.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_kg_entity_type_name', 'kg_entity', ['entity_type', 'name'])
    op.create_index('ix_kg_entity_merged', 'kg_entity', ['merged_into'])
    op.create_index('ix_kg_entity_source_literature_id', 'kg_entity', ['source_literature_id'])

    op.create_table(
        'kg_triple',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('subject_id', sa.String(16), nullable=False),
        sa.Column('predicate', sa.String(32), nullable=False),
        sa.Column('object_id', sa.String(16), nullable=False),
        sa.Column('confidence', sa.Float, server_default='1.0'),
        sa.Column('source_context', sa.Text, nullable=True),
        sa.Column('literature_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['subject_id'], ['kg_entity.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['object_id'], ['kg_entity.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['literature_id'], ['literature.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('subject_id', 'predicate', 'object_id', 'literature_id', name='uq_kg_triple'),
    )
    op.create_index('ix_kg_triple_literature_id', 'kg_triple', ['literature_id'])
    op.create_index('ix_kg_triple_subject', 'kg_triple', ['subject_id'])
    op.create_index('ix_kg_triple_object', 'kg_triple', ['object_id'])


def downgrade() -> None:
    op.drop_table('kg_triple')
    op.drop_table('kg_entity')

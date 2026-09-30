"""add_extraction_history_and_done_no_data

Revision ID: e1c07278aa97
Revises: rebuild_indices
Create Date: 2026-08-13 10:14:20.396395

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e1c07278aa97'
down_revision: Union[str, Sequence[str], None] = 'rebuild_indices'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. 创建 extraction_history 表
    op.create_table('extraction_history',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('literature_id', sa.Uuid(), nullable=False),
    sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('data_point_count', sa.Integer(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('total_tokens', sa.Integer(), nullable=False),
    sa.Column('llm_cost_usd', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('llm_call_count', sa.Integer(), nullable=False),
    sa.Column('llm_usage_detail', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("status IN ('success','no_data','failed')", name='extraction_history_status_check'),
    sa.ForeignKeyConstraint(['literature_id'], ['literature.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_extraction_history_literature_id'), 'extraction_history', ['literature_id'], unique=False)
    op.create_index(op.f('ix_extraction_history_status'), 'extraction_history', ['status'], unique=False)

    # 2. 更新 literature 表的 extraction_status 检查约束，添加 done_no_data
    # 约束名可能为 lit_extraction_status_check（SQLAlchemy 生成）或
    # literature_extraction_status_check（init_db.sql 内联生成），
    # 使用 PL/pgSQL 动态 SQL 安全处理不存在的情况
    op.execute("""
        DO $$
        DECLARE
            _conname text;
            _defn text;
        BEGIN
            SELECT conname, pg_get_constraintdef(oid)
            INTO _conname, _defn
            FROM pg_constraint
            WHERE conrelid = 'literature'::regclass AND contype = 'c';

            IF _conname IS NOT NULL AND _defn IS NOT NULL AND position('done_no_data' in _defn) = 0 THEN
                EXECUTE format('ALTER TABLE literature DROP CONSTRAINT %I', _conname);
                EXECUTE 'ALTER TABLE literature ADD CONSTRAINT lit_extraction_status_check '
                    || 'CHECK (extraction_status IN (''pending'',''processing'',''done'',''done_no_data'',''failed''))';
            END IF;
        END;
        $$;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # 1. 恢复原来的检查约束（去掉 done_no_data）
    op.execute("""
        DO $$
        DECLARE
            _conname text;
            _defn text;
        BEGIN
            SELECT conname, pg_get_constraintdef(oid)
            INTO _conname, _defn
            FROM pg_constraint
            WHERE conrelid = 'literature'::regclass AND contype = 'c';

            IF _conname IS NOT NULL AND _defn IS NOT NULL AND position('done_no_data' in _defn) > 0 THEN
                EXECUTE format('ALTER TABLE literature DROP CONSTRAINT %I', _conname);
                EXECUTE 'ALTER TABLE literature ADD CONSTRAINT lit_extraction_status_check '
                    || 'CHECK (extraction_status IN (''pending'',''processing'',''done'',''failed''))';
            END IF;
        END;
        $$;
    """)

    # 2. 删除 extraction_history 表
    op.drop_index(op.f('ix_extraction_history_status'), table_name='extraction_history')
    op.drop_index(op.f('ix_extraction_history_literature_id'), table_name='extraction_history')
    op.drop_table('extraction_history')
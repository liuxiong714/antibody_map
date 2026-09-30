"""add extraction queued status

Revision ID: add_extraction_queued_status
Revises: (previous migration)
Create Date: 2026-08-22 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_extraction_queued_status"
down_revision: Union[str, None] = "add_soft_delete"


def upgrade() -> None:
    # 现有约束名可能为 lit_extraction_status_check（SQLAlchemy 生成）或
    # literature_extraction_status_check（init_db.sql 内联生成），动态查找后重建并加入 queued。
    op.execute("""
        DO $$
        DECLARE
            _conname text;
        BEGIN
            SELECT conname INTO _conname
            FROM pg_constraint
            WHERE conrelid = 'literature'::regclass AND contype = 'c'
            ORDER BY conname
            LIMIT 1;

            IF _conname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE literature DROP CONSTRAINT %I', _conname);
            END IF;

            EXECUTE 'ALTER TABLE literature ADD CONSTRAINT lit_extraction_status_check '
                || 'CHECK (extraction_status IN (''pending'',''queued'',''processing'',''done'',''done_no_data'',''failed''))';
        END;
        $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            _conname text;
        BEGIN
            SELECT conname INTO _conname
            FROM pg_constraint
            WHERE conrelid = 'literature'::regclass AND contype = 'c'
            ORDER BY conname
            LIMIT 1;

            IF _conname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE literature DROP CONSTRAINT %I', _conname);
            END IF;

            EXECUTE 'ALTER TABLE literature ADD CONSTRAINT lit_extraction_status_check '
                || 'CHECK (extraction_status IN (''pending'',''processing'',''done'',''done_no_data'',''failed''))';
        END;
        $$;
    """)
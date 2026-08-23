"""create_literature_file_history

新增 literature_file_history 表，记录文献文件的导入/软删除历史，
用于重复导入提示。

Revision ID: create_literature_file_history
Revises: add_immune_barrier_report
Create Date: 2026-08-23

"""
import sqlalchemy as sa
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'create_literature_file_history'
down_revision: Union[str, None] = 'add_immune_barrier_report'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'literature_file_history',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('pdf_hash', sa.String(64), nullable=False),
        sa.Column('file_name', sa.String(500), nullable=True),
        sa.Column('literature_id', sa.Uuid(), nullable=True),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('operator_id', sa.Uuid(), nullable=True),
        sa.Column('operator_name', sa.String(100), nullable=True),
        sa.Column('operated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('imported','deleted')",
            name='lit_file_history_action_check',
        ),
    )
    op.create_index('ix_literature_file_history_pdf_hash', 'literature_file_history', ['pdf_hash'])
    op.create_index('ix_literature_file_history_action', 'literature_file_history', ['action'])
    op.create_index('ix_literature_file_history_operated_at', 'literature_file_history', ['operated_at'])


def downgrade() -> None:
    op.drop_index('ix_literature_file_history_operated_at', table_name='literature_file_history')
    op.drop_index('ix_literature_file_history_action', table_name='literature_file_history')
    op.drop_index('ix_literature_file_history_pdf_hash', table_name='literature_file_history')
    op.drop_table('literature_file_history')
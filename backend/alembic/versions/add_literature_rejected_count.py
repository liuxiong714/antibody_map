"""add rejected_count to literature

Revision ID: add_literature_rejected_count
Revises: add_synthetic_multi_model
Create Date: 2026-09-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_literature_rejected_count'
down_revision: Union[str, None] = 'add_synthetic_multi_model'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 驳回计数：用于区分「已驳回」与「未审核」，仅记录数量不改动存量 approved_count/extracted_count
    op.add_column('literature', sa.Column('rejected_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('literature', 'rejected_count')
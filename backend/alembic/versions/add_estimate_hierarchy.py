"""add_estimate_hierarchy

Revision ID: add_estimate_hierarchy
Revises: add_precise_grounding
Create Date: 2026-08-04

P1-1: Adds primary/subgroup estimate hierarchy to data_point table.
- estimate_type: 'primary' (主估计, e.g. province-level summary) or 'subgroup' (子估计, e.g. age/region stratum)
- parent_id: self-referential FK; subgroup points to its primary estimate
This avoids double-counting in map/analysis (default to primary estimates only).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'add_estimate_hierarchy'
down_revision: Union[str, Sequence[str], None] = 'add_precise_grounding'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add estimate_type and parent_id columns to data_point."""
    # estimate_type: 默认 primary，保证向后兼容（已有数据全部视为主估计）
    op.add_column('data_point', sa.Column(
        'estimate_type',
        sa.String(length=20),
        nullable=False,
        server_default='primary',
    ))
    # parent_id: 自引用外键，子估计指向主估计；主估计为 NULL
    op.add_column('data_point', sa.Column(
        'parent_id',
        sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    ))
    op.create_foreign_key(
        'fk_data_point_parent_id',
        'data_point',
        'data_point',
        ['parent_id'],
        ['id'],
        ondelete='SET NULL',
    )
    # CHECK 约束：estimate_type 只能是 primary 或 subgroup
    op.create_check_constraint(
        'dp_estimate_type_check',
        'data_point',
        "estimate_type IN ('primary','subgroup')",
    )


def downgrade() -> None:
    """Remove estimate hierarchy columns."""
    op.drop_constraint('dp_estimate_type_check', 'data_point', type_='check')
    op.drop_constraint('fk_data_point_parent_id', 'data_point', type_='foreignkey')
    op.drop_column('data_point', 'parent_id')
    op.drop_column('data_point', 'estimate_type')

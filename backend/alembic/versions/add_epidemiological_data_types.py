"""add_epidemiological_data_types

Revision ID: add_epidemiological_data_types
Revises: add_literature_rejected_count
Create Date: 2026-09-18

Phase 1: extend data_point.data_type to cover epidemiological surveillance
indicators alongside existing antibody sero/gmc types.

New allowed data_type values (all additive, existing seroprevalence/gmc rows
are untouched):
- incidence   发病率
  case_count  发病人数
  mortality   死亡率/病死率
  death_count 死亡数

Implementation: CHECK constraint cannot be altered in place, so drop the
existing dp_data_type_check and recreate it with the extended enumeration.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'add_epidemiological_data_types'
down_revision: Union[str, Sequence[str], None] = 'add_literature_rejected_count'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Relax data_point.data_type CHECK constraint to include epidemiological types."""
    op.drop_constraint('data_point_data_type_check', 'data_point', type_='check')
    op.create_check_constraint(
        'data_point_data_type_check',
        'data_point',
        "data_type IN ('seroprevalence','gmc','incidence','case_count','mortality','death_count')",
    )


def downgrade() -> None:
    """Restore the original two-type constraint."""
    op.drop_constraint('data_point_data_type_check', 'data_point', type_='check')
    op.create_check_constraint(
        'data_point_data_type_check',
        'data_point',
        "data_type IN ('seroprevalence','gmc')",
    )
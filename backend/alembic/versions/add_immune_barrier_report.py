"""add_immune_barrier_report

新增「免疫屏障评估报告」类型：扩展 report 与 report_template 的 report_type 合法值约束。

Revision ID: add_immune_barrier_report
Revises: add_reference_import_log
Create Date: 2026-08-23

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'add_immune_barrier_report'
down_revision: Union[str, None] = 'add_reference_import_log'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # report 表：先删旧约束，再加含新类型的新约束
    op.drop_constraint('report_type_check', 'report', type_='check')
    op.create_check_constraint(
        "report_type_check",
        'report',
        "report_type IN ('antibody_analysis','vaccination_strategy','immune_barrier_assessment')",
    )
    # report_template 表
    op.drop_constraint('report_template_type_check', 'report_template', type_='check')
    op.create_check_constraint(
        "report_template_type_check",
        'report_template',
        "report_type IN ('antibody_analysis','vaccination_strategy','immune_barrier_assessment')",
    )


def downgrade() -> None:
    op.drop_constraint('report_type_check', 'report', type_='check')
    op.create_check_constraint(
        "report_type_check",
        'report',
        "report_type IN ('antibody_analysis','vaccination_strategy')",
    )
    op.drop_constraint('report_template_type_check', 'report_template', type_='check')
    op.create_check_constraint(
        "report_template_type_check",
        'report_template',
        "report_type IN ('antibody_analysis','vaccination_strategy')",
    )
"""add goal_threshold_config table

Revision ID: add_goal_threshold_config
Revises: add_title_norm_and_trgm
Create Date: 2026-08-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_goal_threshold_config"
down_revision: Union[str, None] = "add_title_norm_and_trgm"


# 与 app.core.goal_thresholds.GOAL_THRESHOLDS 保持一致的默认值（迁移种子数据）。
# 后续管理员可通过系统设置 API 覆盖，删除记录即恢复默认。
_GOAL_THRESHOLDS: dict[str, float] = {
    "measles": 95.0, "rubella": 95.0, "mumps": 90.0, "polio": 95.0,
    "varicella": 85.0, "diphtheria": 90.0, "tetanus": 90.0,
    "pertussis": 90.0, "meningitis": 85.0, "hepatitis_a": 90.0,
    "hepatitis_b": 95.0, "influenza": 65.0, "covid19": 75.0,
    "hfmd": 75.0, "rotavirus": 80.0,
}


def upgrade() -> None:
    op.create_table(
        "goal_threshold_config",
        sa.Column("disease", sa.String(length=64), primary_key=True),
        sa.Column("threshold_percent", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
    )
    for key, value in _GOAL_THRESHOLDS.items():
        op.execute(
            sa.text(
                "INSERT INTO goal_threshold_config (disease, threshold_percent) "
                "VALUES (:d, :v)"
            ).bindparams(d=key, v=value)
        )


def downgrade() -> None:
    op.drop_table("goal_threshold_config")

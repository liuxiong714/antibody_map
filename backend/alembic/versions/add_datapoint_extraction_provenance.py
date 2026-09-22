"""DataPoint 加提取批次溯源字段（model_used + extraction_history_id）

Revision ID: add_datapoint_extraction_provenance
Revises: widen_alembic_version_num
Create Date: 2026-09-20

Adds two columns to data_point for F21 extraction provenance:
  - model_used (VARCHAR(100), nullable) — 冗余直存该数据点由哪个 LLM 模型提取
  - extraction_history_id (UUID FK nullable) — 关联 extraction_history.id 用于追溯完整批次

Backfill strategy: 对每个 DataPoint，按 literature_id + created_at 时间邻近（±5 min）
匹配 ExtractionHistory 行，回填 model_used + extraction_history_id。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_datapoint_extraction_provenance'
down_revision: Union[str, Sequence[str], None] = 'widen_alembic_version_num'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. 加列 ---
    op.add_column(
        'data_point',
        sa.Column('model_used', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'data_point',
        sa.Column('extraction_history_id', sa.UUID(as_uuid=True), nullable=True),
    )

    op.create_index(
        op.f('ix_data_point_model_used'),
        'data_point', ['model_used'], unique=False,
    )
    op.create_index(
        op.f('ix_data_point_extraction_history_id'),
        'data_point', ['extraction_history_id'], unique=False,
    )
    op.create_foreign_key(
        'fk_dp_extraction_history',
        'data_point', 'extraction_history',
        ['extraction_history_id'], ['id'],
        ondelete='SET NULL',
    )

    # --- 2. 回填：用窗口函数按 literature_id 分组，取 created_at 时间邻近的 ExtractionHistory ---
    # 思路：先把每个 DataPoint 关联到同一 literature 下、extracted_at <= dp.created_at 且最接近的那条 history
    op.execute("""
        WITH ranked_hist AS (
            SELECT
                dp.id AS dp_id,
                eh.id AS eh_id,
                eh.model AS eh_model,
                row_number() OVER (
                    PARTITION BY dp.id
                    ORDER BY
                        abs(EXTRACT(EPOCH FROM (eh.extracted_at - dp.created_at))),
                        eh.extracted_at DESC
                ) AS rn
            FROM data_point dp
            JOIN extraction_history eh
              ON eh.literature_id = dp.literature_id
             AND eh.status IN ('success', 'no_data')
            WHERE eh.extracted_at <= dp.created_at + INTERVAL '5 minutes'
              AND eh.extracted_at >= dp.created_at - INTERVAL '10 minutes'
              AND dp.model_used IS NULL
        )
        UPDATE data_point dp
        SET
            model_used = rh.eh_model,
            extraction_history_id = rh.eh_id
        FROM ranked_hist rh
        WHERE dp.id = rh.dp_id AND rh.rn = 1
    """)


def downgrade() -> None:
    op.drop_constraint('fk_dp_extraction_history', 'data_point', type_='foreignkey')
    op.drop_index(op.f('ix_data_point_extraction_history_id'), table_name='data_point')
    op.drop_index(op.f('ix_data_point_model_used'), table_name='data_point')
    op.drop_column('data_point', 'extraction_history_id')
    op.drop_column('data_point', 'model_used')

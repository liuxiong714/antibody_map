"""add_api_model_config_expires_at

为 api_model_config 补上 expires_at 列（临时配置自动过期回收）。

背景：模型 ApiModelConfig 在 v1.19.0 引入了 expires_at 字段（临时配置过期时间），
但当时漏写了对应迁移，导致运行中数据库的表缺列，/models 等接口查询时抛
UndefinedColumnError。此迁移仅做增量补列 + 索引，不触碰任何已有数据。

Revision ID: add_api_model_config_expires_at
Revises: add_report_data_snapshot_hash
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_api_model_config_expires_at'
down_revision: Union[str, Sequence[str], None] = 'add_report_data_snapshot_hash'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add expires_at column (nullable, indexed) to api_model_config."""
    op.add_column(
        'api_model_config',
        sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_api_model_config_expires_at',
        'api_model_config',
        ['expires_at'],
    )


def downgrade() -> None:
    """Drop expires_at column and its index."""
    op.drop_index('ix_api_model_config_expires_at', table_name='api_model_config')
    op.drop_column('api_model_config', 'expires_at')
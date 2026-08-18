"""add_local_model_config

Revision ID: add_local_model_config
Revises: add_titer_table
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_local_model_config'
down_revision: Union[str, Sequence[str], None] = 'add_titer_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 默认种子本地模型（合并原前端静态列表与后端 LOCAL_MODELS，去重）
_DEFAULT_LOCAL_MODELS = [
    {"name": "Qwen3.8:27B", "model_name": "qwen3.8:27b", "description": "本地 Qwen3.8 27B 模型"},
    {"name": "Qwen3:32B", "model_name": "qwen3:32b", "description": "本地 Qwen3 32B 模型"},
    {"name": "Qwen3:8B", "model_name": "qwen3:8b", "description": "本地 Qwen3 8B 模型"},
    {"name": "Qwen2.5:14B", "model_name": "qwen2.5:14b", "description": "本地 Qwen2.5 14B 模型"},
    {"name": "Qwen2.5:7B", "model_name": "qwen2.5:7b", "description": "本地 Qwen2.5 7B 模型"},
    {"name": "DeepSeek R1:14B", "model_name": "deepseek-r1:14b", "description": "本地 DeepSeek R1 14B 模型"},
    {"name": "DeepSeek R1:7B", "model_name": "deepseek-r1:7b", "description": "本地 DeepSeek R1 7B 模型"},
    {"name": "Llama 3.1:8B", "model_name": "llama3.1:8b", "description": "本地 Llama 3.1 8B 模型"},
    {"name": "Llama 3.1:70B", "model_name": "llama3.1:70b", "description": "本地 Llama 3.1 70B 模型"},
    {"name": "Mistral:7B", "model_name": "mistral:7b", "description": "本地 Mistral 7B 模型"},
    {"name": "GLM4:9B", "model_name": "glm4:9b", "description": "本地 GLM4 9B 模型"},
]


def upgrade() -> None:
    """Create local_model_config table and seed default local models."""
    op.create_table(
        'local_model_config',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('model_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('model_name'),
    )

    # 种子默认本地模型
    bind = op.get_bind()
    for item in _DEFAULT_LOCAL_MODELS:
        bind.execute(
            sa.text(
                "INSERT INTO local_model_config (id, name, model_name, description, is_active, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :name, :model_name, :description, true, now(), now()) "
                "ON CONFLICT (model_name) DO NOTHING"
            ),
            {"name": item["name"], "model_name": item["model_name"], "description": item["description"]},
        )


def downgrade() -> None:
    """Drop local_model_config table."""
    op.drop_table('local_model_config')

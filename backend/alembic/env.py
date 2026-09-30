import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# 将 backend 目录加入 sys.path，确保可以导入 app 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings
from app.models.base import Base

# 一次性导入所有模型，确保 Base.metadata 包含全部 25 张表
# （不能逐文件导入——容易遗漏，改用 models/__init__.py 的集中导入）
import app.models  # noqa: F401  registers all models into Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without connecting to DB)."""
    url = settings.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connects to DB).

    重要：先 Base.metadata.create_all 幂等建表，再跑 alembic upgrade。
    原因：init 迁移（94cbbc6f286f）内部全是 ALTER COLUMN / DROP INDEX，
    无 CREATE TABLE —— 这是 alembic 首次 autogenerate 时在已有库上生成的结果。
    全新空库上直接跑 init 迁移会因 "relation does not exist" 失败。
    先 create_all 能在空库上补齐所有模型表（25 张），且对已有库是 no-op。
    """
    connectable = create_async_engine(
        settings.DATABASE_URL,
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        # 1. 幂等建表（空库上补所有表；已有库上 CREATE TABLE IF NOT EXISTS，无副作用）
        await connection.run_sync(Base.metadata.create_all)
        # 2. 正常跑 alembic 升级链（在已有表上做 ALTER / 加列 / 加索引等）
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

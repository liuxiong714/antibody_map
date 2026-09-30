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

    IMPORTANT: Two SEPARATE connections for create_all and do_run_migrations.

    Why? Base.metadata.create_all() opens an implicit asyncpg transaction
    (autocommit=False). Then do_run_migrations() wraps context.begin_transaction()
    around context.run_migrations() — this creates a NESTED transaction in
    asyncpg, and alembic's internal "mark as applied" state gets confused:
    revision versions silently skipped instead of being written to
    alembic_version. That's why 	est_migration_drift.py keeps catching
    current=X heads=X+1 after a clean alembic upgrade.

    Two separate connections = two separate transaction boundaries. Each gets
    its own clean commit scope. alembic's version marking works correctly.
    """
    url = settings.DATABASE_URL
    # 两个 connection，各自独立 transaction scope
    # --- Connection 1: create_all 幂等建表（空库上补所有 25 张表） ---
    eng1 = create_async_engine(url, poolclass=pool.NullPool)
    async with eng1.connect() as conn1:
        await conn1.run_sync(Base.metadata.create_all)
    await eng1.dispose()

    # --- Connection 2: alembic upgrade 链上的 ALTER/加列/加索引 ---
    eng2 = create_async_engine(url, poolclass=pool.NullPool)
    async with eng2.connect() as conn2:
        await conn2.run_sync(do_run_migrations)
    await eng2.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

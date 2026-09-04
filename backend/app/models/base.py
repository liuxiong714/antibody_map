from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 数据库连接池配置：
# - pool_size：常驻连接数
# - max_overflow：池满后可临时额外创建的连接数（峰值弹性）
# - pool_timeout：获取连接的等待超时（秒），避免高并发下无限等待
# - pool_pre_ping：取连接前校验存活，避免使用失效连接
# 注意：asyncpg 对池中已失效连接做 pre_ping 时可能抛 MissingGreenlet（SQLAlchemy
# 已知问题）。SQLAlchemy 在使用到真正失效连接时会自动判定并断开重连，故不依赖 pre_ping。
# --- 修正说明（2026-08-31）---
# SQLAlchemy 2.0.52 已修复 asyncpg pre_ping 相关 MissingGreenlet 问题，且本仓库存在
# LLM/网络长调用后复用池中陈旧连接导致 commit 报 "connection is closed" 的问题，
# 因此恢复启用 pool_pre_ping，取连接前强制做存活校验。
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,
    pool_recycle=1800,
    # 数据库写入保险（防文献提取长事务导致整表行锁被长时间占用、列表查询卡死）：
    # - statement_timeout：单条 SQL 执行超过 120s 主动终止，兜住异常慢语句
    # - idle_in_transaction_session_timeout：事务空转（语句已执行完却不提交/回滚）超过
    #   10 分钟自动回滚并断开。此前 120s 为早期"卡死"根因修复；现任务已确保 LLM 推理
    #   期间不持有数据库连接（见 extract_task F13），故可将空转宽限延长到 10 分钟，
    #   避免偶发长事务被过早强断；若再出现行锁积压可回调至 120s。
    connect_args={
        "server_settings": {
            "statement_timeout": "120000",
            "idle_in_transaction_session_timeout": "600000",
        }
    },
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_async_session() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

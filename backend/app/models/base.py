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
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=False,
    pool_recycle=1800,
    # 数据库写入保险（防文献提取长事务导致整表行锁被长时间占用、列表查询卡死）：
    # - statement_timeout：单条 SQL 执行超过 120s 主动终止，兜住异常慢语句
    # - idle_in_transaction_session_timeout：事务空转（语句已执行完却不提交/回滚）超过
    #   120s 自动回滚并断开，防止 idle-in-transaction 长期持有行锁（本次卡死根因）
    connect_args={
        "server_settings": {
            "statement_timeout": "120000",
            "idle_in_transaction_session_timeout": "120000",
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

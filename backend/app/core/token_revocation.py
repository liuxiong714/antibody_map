"""Token 吊销服务

使用 Redis 存储已吊销的 JWT jti（黑名单），支持：
- 吊销 token（添加 jti 到黑名单，有效期与 token 自身过期时间一致）
- 检查 token 是否已被吊销
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger("uvicorn")

# Redis 连接（复用 settings 中的 Redis URL）
_redis: Optional[aioredis.Redis] = None


async def _get_redis() -> aioredis.Redis:
    """获取 Redis 连接（懒初始化）"""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _redis


def _get_ttl(exp: Optional[int]) -> int:
    """计算 token 剩余有效期（秒），至少 60 秒"""
    if exp is None:
        return 3600  # 默认 1 小时
    remaining = int(exp - datetime.now(timezone.utc).timestamp())
    return max(remaining, 60)


async def revoke_token(jti: str, exp: Optional[int] = None) -> None:
    """将 token 加入黑名单

    Args:
        jti: JWT 令牌的唯一 ID
        exp: 令牌的过期时间戳（Unix 时间），用于设置黑名单自动过期

    fail-closed：Redis 连接异常时抛出 RedisError，调用方决定是否拒绝/降级，
    绝不静默吞掉写失败（否则重放保护形同虚设）。
    """
    r = await _get_redis()
    ttl = _get_ttl(exp)
    key = f"token_revoked:{jti}"
    await r.setex(key, ttl, "1")


async def is_token_revoked(jti: str) -> bool:
    """检查 token 是否已被吊销

    Args:
        jti: JWT 令牌的唯一 ID

    Returns:
        True 表示已吊销

    fail-closed：Redis 连接异常时抛出 RedisError，绝不 return False 放行，
    保证吊销检查在缓存不可用时拒绝令牌而非静默通过。
    """
    r = await _get_redis()
    key = f"token_revoked:{jti}"
    result = await r.get(key)
    return result == "1"


def token_issued_before_password_change(iat, password_changed_at) -> bool:
    """F3：判断令牌是否签发于用户最近一次改密之前。

    用于改密后吊销既有令牌：若令牌的签发时间(iat)早于密码变更时间，
    则认为该令牌已失效，应拒绝使用（access 与 refresh 令牌均适用）。

    Args:
        iat: 令牌签发时间戳（JWT payload 中的 iat，Unix 秒）
        password_changed_at: 用户最近一次改密时间（datetime，可空）

    Returns:
        True 表示令牌签发早于改密（应拒绝）；False / 无法判断返回 False。
    """
    if iat is None or password_changed_at is None:
        return False
    try:
        changed_ts = password_changed_at.timestamp()
    except Exception:
        return False
    return changed_ts > int(iat)
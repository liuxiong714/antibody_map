"""Token 吊销服务

使用 Redis 存储已吊销的 JWT jti（黑名单），支持：
- 吊销 token（添加 jti 到黑名单，有效期与 token 自身过期时间一致）
- 检查 token 是否已被吊销
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

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
    """
    try:
        r = await _get_redis()
        ttl = _get_ttl(exp)
        key = f"token_revoked:{jti}"
        await r.setex(key, ttl, "1")
    except Exception as e:
        logger.warning(f"Token 吊销写入 Redis 失败: {e}")


async def is_token_revoked(jti: str) -> bool:
    """检查 token 是否已被吊销

    Args:
        jti: JWT 令牌的唯一 ID

    Returns:
        True 表示已吊销
    """
    try:
        r = await _get_redis()
        key = f"token_revoked:{jti}"
        result = await r.get(key)
        return result == "1"
    except Exception as e:
        logger.warning(f"Token 吊销检查 Redis 失败: {e}")
        return False  # Redis 不可用时，放行（降级处理）
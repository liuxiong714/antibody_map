"""速率限制器（S-3：Redis 后端 + X-Forwarded-For 取真实 IP）。

架构：
  - Redis 可用 → Redis 滑动窗口（多进程/分布式安全）。
  - Redis 不可用 → 降级为单进程内存实现（_SlidingWindowCounter）。
  - IP 提取优先 X-Forwarded-For 首个 IP（nginx 透传链最左端），回退 request.client.host。

Key 模式：
  登录限流：ratelimit:login:{ip}  窗口 60s，max 5 次
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


# ============================================================
# IP 提取（X-Forwarded-For 感知）
# ============================================================

def _extract_client_ip(request: Request) -> str:
    """从请求中抽取客户端 IP（支持 X-Forwarded-For 代理链）。

    代理链（nginx → ... → backend）通常：
      X-Forwarded-For: <client_ip>, <proxy1_ip>, <proxy2_ip>
    最左侧是真实客户端 IP，右侧是中间代理。
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


# ============================================================
# 内存后端（降级 / 开发环境）
# ============================================================

class _SlidingWindowCounter:
    """滑动窗口计数器（线程安全近似）——单进程内存实现"""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.window_seconds
        timestamps = self._requests[key]

        while timestamps and timestamps[0] < window_start:
            timestamps.pop(0)

        if len(timestamps) >= self.max_requests:
            return False

        timestamps.append(now)
        return True


# 登录速率限制：每 IP 每分钟最多 5 次
_LOGIN_MAX = 5
_LOGIN_WINDOW = 60

# 内存 fallback（Redis 停用时使用）
_login_mem = _SlidingWindowCounter(_LOGIN_MAX, _LOGIN_WINDOW)


# ============================================================
# Redis 后端（分布式 / 多进程安全）
# ============================================================

async def _redis_login_allowed(ip: str) -> bool | None:
    """Redis 滑动窗口。返回 True/False/None（None 表示 Redis 不可用）。"""
    try:
        from redis.asyncio import Redis
        from app.config import settings
    except Exception:
        return None

    client = None
    try:
        client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=10,
            retry_on_timeout=True,
            socket_connect_timeout=2,
        )

        key = f"ratelimit:login:{ip}"
        now = time.time()
        window_start = now - _LOGIN_WINDOW

        # ZADD 当前时间戳（score=time）
        await client.zadd(key, {f"{now}": now})
        # 清理过期
        await client.zremrangebyscore(key, "-inf", window_start)
        # 设置窗口 TTL（登录限流用完就扔）
        await client.expire(key, _LOGIN_WINDOW)
        # 计数
        count = await client.zcard(key)
        return count is not None and count <= _LOGIN_MAX
    except Exception as e:
        logger.debug(f"[rate_limiter] Redis 登录限流失败，降级内存: {e}")
        return None
    finally:
        if client is not None:
            with contextlib_suppress():
                await client.aclose()


def contextlib_suppress():
    """导入一次 contextlib.suppress 的便捷函数（避免在模块顶部 import）。"""
    import contextlib
    return contextlib.suppress(Exception)


# ============================================================
# FastAPI 依赖入口
# ============================================================

async def login_rate_limit(request: Request) -> None:
    """登录接口速率限制依赖（Redis 优先 + X-Forwarded-For IP + 内存降级）。"""
    ip = _extract_client_ip(request)

    # 先试 Redis
    redis_result = await _redis_login_allowed(ip)
    if redis_result is None:
        # Redis 不可用 → 降级内存
        if not _login_mem.is_allowed(ip):
            raise HTTPException(
                status_code=429,
                detail="登录请求过于频繁，请 1 分钟后再试",
            )
    elif not redis_result:
        raise HTTPException(
            status_code=429,
            detail="登录请求过于频繁，请 1 分钟后再试",
        )

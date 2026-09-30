"""速率限制器（S-3：Redis 后端 + X-Forwarded-For 取真实 IP）。

架构：
  - Redis 可用 → Redis 滑动窗口（多进程/分布式安全）。
  - Redis 不可用 → 降级为单进程内存实现（_SlidingWindowCounter）。
  - IP 提取优先 X-Forwarded-For 首个 IP（nginx 透传链最左端），回退 request.client.host。

Key 模式：
  登录限流：ratelimit:login:{ip}     窗口 60s，max 5 次
  提取触发：ratelimit:extract:{ip}   窗口 60s，max 20 次（防刷 LLM token）
"""
from __future__ import annotations

import contextlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass

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


# ============================================================
# Redis 后端（分布式 / 多进程安全）
# ============================================================

async def _redis_sliding_window_check(
    key: str, max_requests: int, window_seconds: int
) -> bool | None:
    """通用 Redis 滑动窗口检查。

    返回 True=允许 / False=拒绝 / None=Redis 不可用（需降级内存）。
    """
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

        now = time.time()
        window_start = now - window_seconds

        # ZADD 当前时间戳（score=time）
        await client.zadd(key, {f"{now}": now})
        # 清理过期
        await client.zremrangebyscore(key, "-inf", window_start)
        # 设置窗口 TTL
        await client.expire(key, window_seconds)
        # 计数
        count = await client.zcard(key)
        return count is not None and count <= max_requests
    except Exception as e:
        logger.debug(f"[rate_limiter] Redis 限流失败，降级内存: {e}")
        return None
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()


# ============================================================
# 限流配置注册表
# ============================================================

@dataclass
class _LimitConfig:
    """单个限流规则的运行时配置。"""
    name: str              # 名称（用于日志）
    key_prefix: str        # Redis key 前缀：ratelimit:{prefix}:{ip}
    max_requests: int
    window_seconds: int
    message: str           # 429 响应消息
    _mem_counter: _SlidingWindowCounter | None = None


# 登录限流：每 IP 每分钟最多 20 次（开发环境 nginx 健康检查 + 浏览器重试可能触发）
_login_cfg = _LimitConfig(
    name="login",
    key_prefix="login",
    max_requests=20,
    window_seconds=60,
    message="登录请求过于频繁，请 1 分钟后再试",
    _mem_counter=_SlidingWindowCounter(20, 60),
)

# 提取触发限流：每 IP 每分钟最多 20 次（批量提取算 1 次请求，但会入队多个任务）
_extract_cfg = _LimitConfig(
    name="extract",
    key_prefix="extract",
    max_requests=20,
    window_seconds=60,
    message="提取请求过于频繁，请稍后再试（每分钟最多 20 次）",
    _mem_counter=_SlidingWindowCounter(20, 60),
)


async def _check_limit(cfg: _LimitConfig, ip: str) -> None:
    """通用限流检查：Redis 优先，降级内存；超限抛 429。"""
    key = f"ratelimit:{cfg.key_prefix}:{ip}"
    redis_result = await _redis_sliding_window_check(
        key, cfg.max_requests, cfg.window_seconds
    )
    if redis_result is None:
        # Redis 不可用 → 降级内存
        if cfg._mem_counter is not None and not cfg._mem_counter.is_allowed(ip):
            raise HTTPException(status_code=429, detail=cfg.message)
    elif not redis_result:
        raise HTTPException(status_code=429, detail=cfg.message)


# ============================================================
# FastAPI 依赖入口
# ============================================================

async def login_rate_limit(request: Request) -> None:
    """登录接口速率限制依赖。"""
    ip = _extract_client_ip(request)
    await _check_limit(_login_cfg, ip)


async def extraction_rate_limit(request: Request) -> None:
    """AI 提取触发速率限制依赖（单篇 + 批量端点共用）。"""
    ip = _extract_client_ip(request)
    await _check_limit(_extract_cfg, ip)

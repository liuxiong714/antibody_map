"""轻量级内存速率限制器

使用滑动窗口算法，基于 IP 地址限制请求频率。
仅适用于单进程部署场景；多进程/分布式部署需改用 Redis 实现。
"""
import time
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class _SlidingWindowCounter:
    """滑动窗口计数器（线程安全近似）"""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """检查是否允许请求，并记录本次请求"""
        now = time.time()
        window_start = now - self.window_seconds
        timestamps = self._requests[key]

        # 清理过期记录
        while timestamps and timestamps[0] < window_start:
            timestamps.pop(0)

        if len(timestamps) >= self.max_requests:
            return False

        timestamps.append(now)
        return True


# 登录速率限制：每 IP 每分钟最多 5 次
_login_limiter = _SlidingWindowCounter(max_requests=5, window_seconds=60)


async def login_rate_limit(request: Request) -> None:
    """登录接口速率限制依赖"""
    client_ip = request.client.host if request.client else "unknown"
    if not _login_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=429,
            detail="登录请求过于频繁，请 1 分钟后再试",
        )
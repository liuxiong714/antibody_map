"""外部 HTTP 统一层：共享连接池 + 重试 + 限速 + TTL 缓存。

供 Crossref / OpenAlex / Europe PMC 等外部学术 API 服务复用，解决：
- F26：每次请求新建 httpx.AsyncClient 无连接池复用 → 模块级共享客户端（连接池）
- F25：无重试/限速/缓存统一层 → 指数退避重试 + 同域名最小间隔限速 +
       URL 维度 TTL 缓存，且单次超时上限仍保持既有 60s 行为
"""
import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("uvicorn")

# 单次请求超时（秒）：与既有各服务的 60s 行为保持一致
REQUEST_TIMEOUT = 60
# 连接池上限（并发连接数与 keepalive 复用数）
_POOL_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
# 失败重试次数（1 次初始 + _MAX_RETRIES 次重试），指数退避 _RETRY_BACKOFF * 2**attempt 秒
_MAX_RETRIES = 2
_RETRY_BACKOFF = 1.0
# 同域名两次请求的最小间隔（秒），对上游保持礼貌限速
_MIN_INTERVAL = 1.0
# URL 维度缓存 TTL（秒）：同一检索词重复请求直接命中缓存，避免重复打上游
_CACHE_TTL_SECONDS = 300

# 共享连接池客户端（惰性单例）
_client: httpx.AsyncClient | None = None
# 限速状态：host -> 该 host 最近一次请求时间戳（monotonic）
_last_request_at: dict[str, float] = {}
# 每 host 一把锁：仅串行化对同一 host 的请求，不同 host 并发不受影响
_host_locks: dict[str, asyncio.Lock] = {}
# 保护 _client/_last_request_at/_host_locks/_cache 的并发访问（均只做快速读改写，不持有等待）
_guard = asyncio.Lock()
# URL -> (过期时间戳, data) 的简单 TTL 缓存
_cache: dict[str, tuple[float, Any]] = {}


def get_client() -> httpx.AsyncClient:
    """返回共享连接池客户端（惰性创建）。"""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, limits=_POOL_LIMITS)
    return _client


async def close_client() -> None:
    """应用关闭时释放共享连接池，避免残留连接阻塞退出。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _throttle(url: str) -> None:
    """同域名最小间隔限速：保证相邻两次对同一 host 的请求至少间隔 _MIN_INTERVAL 秒。"""
    host = urlparse(url).netloc
    async with _guard:
        lock = _host_locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            _host_locks[host] = lock
    async with lock:
        last = _last_request_at.get(host, 0.0)
        wait = _MIN_INTERVAL - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at[host] = time.monotonic()


async def get_json(url: str, *,
                   headers: dict | None = None,
                   cache_ttl: float | None = None) -> Any:
    """GET 请求并解析 JSON，带 共享连接池 + 限速 + 重试 + TTL 缓存。

    - 命中缓存直接返回（默认 TTL 300s，传 cache_ttl=0 可禁用）；
    - 失败时对网络错误 / 5xx / 429 指数退避重试；
    - 4xx 业务错误（除 429）不重试直接抛出；
    - 最终失败抛出最后一次异常，由调用方决定兜底策略。
    """
    ttl = _CACHE_TTL_SECONDS if cache_ttl is None else cache_ttl
    now = time.monotonic()
    if ttl > 0:
        async with _guard:
            hit = _cache.get(url)
        if hit is not None and hit[0] > now:
            return hit[1]

    await _throttle(url)
    client = get_client()
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if ttl > 0:
                async with _guard:
                    _cache[url] = (time.monotonic() + ttl, data)
            return data
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last_exc = e
            # 4xx 业务错误（除 429 可稍后重试）不重试
            if isinstance(e, httpx.HTTPStatusError) and e.response is not None \
                    and e.response.status_code < 500 and e.response.status_code != 429:
                raise
            if attempt < _MAX_RETRIES:
                backoff = _RETRY_BACKOFF * (2 ** attempt)
                logger.warning(
                    f"[external_http] 请求失败(第{attempt + 1}次): {url[:120]} → {e}，"
                    f"{backoff}s 后重试"
                )
                await asyncio.sleep(backoff)
    assert last_exc is not None
    raise last_exc

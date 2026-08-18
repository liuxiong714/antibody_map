"""PDF 解析结果缓存模块。

以文件字节的 sha256 摘要作为 key，将 PDF 解析（MinerU / PyMuPDF / OCR 等耗时
操作）得到的文本缓存到 Redis，避免失败重试、多次提取时重复跑最慢的解析与 OCR。

- key = sha256(file_bytes).hexdigest()
- 缓存 TTL 写死 86400 秒（1 天）
- 单次操作超时 10 秒
- Redis 不可用 / 出错时静默降级为"不缓存"：不抛异常、不影响主流程
"""
import hashlib
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger("uvicorn")

CACHE_TTL = 86400
CACHE_TIMEOUT = 10.0
_CACHE_KEY_PREFIX = "pdf_parse:"


def compute_cache_key(file_bytes: bytes) -> str:
    """计算缓存 key：sha256(file_bytes).hexdigest()。"""
    return hashlib.sha256(file_bytes).hexdigest()


def _create_redis():
    """惰性创建 Redis 客户端。

    每次调用都新建客户端，避免客户端与某个事件循环绑定后跨循环复用的问题；
    且只在用到时导入 redis.asyncio，不阻塞 pdf_parser 等模块的冷启动。
    """
    from redis.asyncio import Redis

    return Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=CACHE_TIMEOUT,
        socket_timeout=CACHE_TIMEOUT,
    )


async def get_cache(key: str) -> Optional[str]:
    """读取缓存文本；未命中或 Redis 不可用时返回 None（不抛异常）。"""
    client = None
    try:
        client = _create_redis()
        value = await client.get(f"{_CACHE_KEY_PREFIX}{key}")
        return value if isinstance(value, str) and value else None
    except Exception as e:
        logger.debug(f"[解析缓存] 读取失败，静默降级为不缓存: {e}")
        return None
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


async def set_cache(key: str, text: str) -> None:
    """写入缓存文本；Redis 不可用时静默忽略（不抛异常）。"""
    client = None
    try:
        client = _create_redis()
        await client.set(f"{_CACHE_KEY_PREFIX}{key}", text, ex=CACHE_TTL)
    except Exception as e:
        logger.debug(f"[解析缓存] 写入失败，静默降级为不缓存: {e}")
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass

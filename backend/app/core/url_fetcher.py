"""URL 抓取模块：从 URL 获取 HTML 内容。"""

import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("uvicorn")

DEFAULT_TIMEOUT = 30

# 常见 User-Agent 模拟浏览器请求
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _host_is_safe(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


async def fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """从 URL 获取内容，返回字节数据。

    自动跟随重定向，超时由 timeout 参数控制。
    失败时抛 httpx.HTTPError 或 httpx.TimeoutException。
    """
    # SSRF 防护：拒绝访问内网/回环/链路本地地址（hostname 解析出的任一 IP 不安全即拒绝）
    host = urlparse(url).hostname
    if not host or not _host_is_safe(host):
        raise ValueError("目标地址不安全，已拒绝访问")

    logger.info(f"[URL 抓取] 开始抓取: {url}, 超时={timeout}s")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        headers=_DEFAULT_HEADERS,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_len = len(resp.content)
        logger.info(f"[URL 抓取] 成功: {url} → HTTP {resp.status_code}, {content_len} 字节")
        return resp.content


def guess_title_from_html(html_bytes: bytes) -> Optional[str]:
    """从 HTML 字节数据中提取 <title> 标签内容。"""
    try:
        from bs4 import BeautifulSoup

        html_text = None
        for enc in ("utf-8", "gbk", "gb18030"):
            try:
                html_text = html_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if html_text is None:
            html_text = html_bytes.decode("utf-8", errors="ignore")

        soup = BeautifulSoup(html_text, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()[:500]
            logger.info(f"[URL 抓取] 从 HTML 提取到标题: {title}")
            return title
        logger.warning("[URL 抓取] HTML 中未找到 <title> 标签")
    except Exception as e:
        logger.warning(f"[URL 抓取] 从 HTML 提取标题失败: {e}")
    return None
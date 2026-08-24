"""LLM 调用封装（从原 app.core.llm_extractor 拆分）。

包含：
- 模块级错误分类函数：_classify_llm_error / _is_connection_error
- LLMClientMixin：API 配置解析、URL 链容错、客户端构建、单次调用与 HTTP 兜底
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.core.extraction.schema import EXTRACTION_JSON_SCHEMA

logger = logging.getLogger("uvicorn")


class LLMBudgetExceeded(Exception):
    """F11：单任务 token 预算或日配额超限。

    属于"任务失败"而非可重试错误（重试只会继续消耗 token），
    由任务层标记 failed 并告警，不触发 URL 切换/重试。
    """


# F11：进程内所有提取任务共享的全局并发信号量（懒创建，绑定当前事件循环）
_global_llm_sem: Optional[asyncio.Semaphore] = None


def _get_global_sem() -> Optional[asyncio.Semaphore]:
    """获取全局并发信号量；LLM_GLOBAL_CONCURRENCY<=0 时返回 None（不限流）。"""
    global _global_llm_sem
    cap = int(getattr(settings, "LLM_GLOBAL_CONCURRENCY", 0) or 0)
    if cap <= 0:
        return None
    if _global_llm_sem is None:
        _global_llm_sem = asyncio.Semaphore(cap)
    return _global_llm_sem


async def _consume_daily_quota(tokens: int) -> None:
    """按自然日计数全平台 token 用量，超过 LLM_DAILY_QUOTA 时抛 LLMBudgetExceeded。

    Redis 不可用时 fail-open（不阻断提取，仅记录日志）。
    """
    quota = int(getattr(settings, "LLM_DAILY_QUOTA", 0) or 0)
    if quota <= 0 or tokens <= 0:
        return
    client = None
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        key = "llm:daily_tokens:" + datetime.now(timezone.utc).strftime("%Y%m%d")
        used = await client.incrby(key, tokens)
        await client.expire(key, 172800)  # 48h 后自动过期（覆盖两个自然日）
        if used > quota:
            raise LLMBudgetExceeded(
                f"今日 LLM token 配额已用尽（{used}/{quota}），"
                "请明日再试或提高 LLM_DAILY_QUOTA 配置"
            )
    except LLMBudgetExceeded:
        raise
    except Exception as e:
        logger.warning(f"日配额检查失败（fail-open，不阻断提取）: {e}")
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


def _classify_llm_error(exc: Exception) -> dict:
    """对 LLM 调用异常分类，便于重试决策与日志诊断。

    返回: {"type": str, "message": str}
    type 取值:
      - connection_error: DNS 解析失败 / TCP 连接失败 / 连接超时 / "All connection attempts failed"
      - read_timeout:     读响应超时（请求已发出，可能已消耗 token，禁止重试/切换，避免双倍计费）
      - auth_error:       401 / API Key 无效（重试无意义）
      - rate_limit:       429 限流（退避重试）
      - http_4xx / http_5xx: 其他 HTTP 状态
      - json_error:       响应内容无法解析为 JSON
      - other:            其他异常
    """
    msg = str(exc) or exc.__class__.__name__
    lower = msg.lower()

    # 沿异常链向上收集所有消息（httpx/openai 常把根因藏在 __cause__）
    chain = [msg]
    cur = exc
    seen = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        cause = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
        if cause is None:
            break
        cause_msg = str(cause) or cause.__class__.__name__
        chain.append(cause_msg)
        cur = cause
    full = " | ".join(chain)
    lower_full = full.lower()

    if "response_format" in lower or "json" in lower and (
        "json.loads" in lower or "expecting value" in lower or "invalid json" in lower
        or "json.decoder" in lower
    ):
        return {"type": "json_error", "message": full[:2000]}
    if "429" in full or "rate limit" in lower_full or "too many requests" in lower_full:
        return {"type": "rate_limit", "message": full[:2000]}
    if "401" in full or "unauthorized" in lower_full or "api key" in lower_full or "authentication" in lower_full:
        return {"type": "auth_error", "message": full[:2000]}
    if "404" in full:
        return {"type": "http_4xx", "message": full[:2000]}
    # F12：读响应超时单独归类。请求已发出、可能已消耗 token，若再切换 URL/重试
    # 会导致同一请求双倍计费。本地 Ollama 推理慢，读超时多属正常慢而非故障，
    # 直接透传为 read_timeout（交由上层决定是否重试），不触发 URL 切换。
    if any(
        k in lower_full
        for k in (
            "timed out",
            "timedout",
            "readtimeout",
            "read timeout",
            "read_error_code",
        )
    ):
        return {"type": "read_timeout", "message": full[:2000]}
    if any(
        k in lower_full
        for k in (
            "all connection attempts failed",
            "connecterror",
            "connect timeout",
            "connection refused",
            "connection reset",
            "connection aborted",
            "network is unreachable",
            "name or service not known",
            "failed to resolve",
            "getaddrinfo",
            "dns",
            "errno 111",
            "errno 101",
            "errno 110",
            "proxyerror",
        )
    ):
        return {"type": "connection_error", "message": full[:2000]}
    if lower.startswith(("4", "5")) and len(lower) >= 3 and lower[1:3].isdigit():
        return {"type": "http_5xx" if lower.startswith("5") else "http_4xx", "message": full[:2000]}
    return {"type": "other", "message": full[:2000]}


def _is_connection_error(exc: Exception) -> bool:
    """判断异常是否为连接类错误（可重试/可切换 URL）。"""
    return _classify_llm_error(exc)["type"] == "connection_error"


class LLMClientMixin:
    """LLM 调用封装：API 配置解析、URL 链容错、客户端构建与单次调用。"""

    # P2-2：旧的前缀映射表保留用于向后兼容（_resolve_api_config_legacy），
    # 新代码通过 providers 注册中心自动匹配。
    _MODEL_CONFIG_MAP = {
        "deepseek": "DEEPSEEK",
        "gpt-": "OPENAI",
        "o1-": "OPENAI",
        "o3-": "OPENAI",
        "qwen": "QWEN",
        "ollama/": "OLLAMA",
        "llama": "OLLAMA",
        "mistral": "OLLAMA",
        "gemma": "OLLAMA",
        "glm4": "OLLAMA",
        "phi": "OLLAMA",
    }

    @staticmethod
    def _resolve_api_config(model: str):
        """根据模型名解析对应的 API key 和 base_url。

        P2-2：优先使用 providers 注册中心，无匹配时回退到旧的前缀映射表。
        """
        # P2-2：优先使用 provider 注册中心
        try:
            from app.core.providers import get_provider_for_model
            provider_cls = get_provider_for_model(model)
            if provider_cls is not None:
                api_key, base_url = provider_cls.get_config()
                return api_key, base_url
        except ImportError:
            pass  # providers 包未安装时回退到旧逻辑

        # 回退：旧的前缀映射表逻辑（向后兼容）
        api_key = settings.LLM_API_KEY
        base_url = settings.LLM_BASE_URL

        model_lower = model.lower()
        for prefix, config_key in LLMClientMixin._MODEL_CONFIG_MAP.items():
            if model_lower.startswith(prefix):
                vendor_key = getattr(settings, f"{config_key}_API_KEY", "")
                vendor_url = getattr(settings, f"{config_key}_BASE_URL", "")
                if vendor_key:
                    api_key = vendor_key
                if vendor_url:
                    base_url = vendor_url
                break

        return api_key, base_url

    @staticmethod
    def _supports_response_format(model: str) -> bool:
        """检查模型是否支持 response_format 参数。

        P2-2：优先查询 provider 注册中心，无匹配时回退到旧逻辑。
        """
        try:
            from app.core.providers import get_provider_for_model
            provider_cls = get_provider_for_model(model)
            if provider_cls is not None:
                return provider_cls.supports_response_format()
        except ImportError:
            pass

        # 回退：旧逻辑
        model_lower = model.lower()
        return "deepseek" in model_lower or "gpt-" in model_lower

    def _is_ollama_model(self, url: Optional[str] = None) -> bool:
        """判断当前是否使用 Ollama 本地模型（用于决定是否透传 think=False 等参数）。

        传入 url 时按该地址判定（支持候选 URL 链中的非主地址）；
        不传时按解析出的主地址判定。
        """
        base_url = (url or self._resolved_url or "").lower()
        return ":11434" in base_url or "localhost" in base_url or "127.0.0.1" in base_url

    @staticmethod
    def _normalize_ollama_url(url: str) -> str:
        """将指向 localhost/127.0.0.1 的 Ollama 地址改写为当前运行环境可达的主机。

        Celery worker 运行在容器内，localhost 指向容器自身而非宿主机，
        无法访问宿主机的 Ollama。当 settings.OLLAMA_BASE_URL 配置了可达主机
        （如 WSL 网关 IP）时，用它替换 localhost/127.0.0.1 主机。
        浏览器直连场景 localhost 语义正确，不受影响。
        """
        try:
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if host in ("localhost", "127.0.0.1") and ":11434" in url:
                cfg = (getattr(settings, "OLLAMA_BASE_URL", "") or "").strip()
                if cfg:
                    c_parsed = urlparse(cfg)
                    c_host = (c_parsed.hostname or "").lower()
                    if c_host and c_host not in ("localhost", "127.0.0.1"):
                        port = parsed.port or c_parsed.port or 11434
                        return urlunparse(parsed._replace(netloc=f"{c_host}:{port}"))
        except Exception:
            pass
        return url

    def _build_url_chain(self) -> list[str]:
        """构建候选 base_url 链（去重保序）。

        顺序：主地址 → LLM_FALLBACK_BASE_URLS 配置的备用地址 → 自动探测候选。
        自动探测候选用于 Ollama 场景：当主地址是 172.27.x.x 等 WSL 网关 IP 时，
        若主地址失效（WSL 重启后网段漂移），依次尝试 host.docker.internal、
        容器网关等常见可达地址。
        """
        chain: list[str] = []
        primary = self._resolved_url or settings.LLM_BASE_URL
        if primary:
            chain.append(primary)

        # 配置的备用地址
        fallback_raw = (getattr(settings, "LLM_FALLBACK_BASE_URLS", "") or "").strip()
        for item in fallback_raw.split(","):
            item = (item or "").strip().rstrip("/")
            if item and item not in chain:
                chain.append(item)

        # 本地 Ollama 场景的自动候选（仅当主地址是 :11434 才追加，避免污染远程 API 链）
        if ":11434" in primary.lower():
            candidates = []
            ollama_cfg = (getattr(settings, "OLLAMA_BASE_URL", "") or "").strip().rstrip("/")
            if ollama_cfg and ollama_cfg not in chain:
                candidates.append(ollama_cfg)
            # host.docker.internal 仅在 Docker Desktop 下指向宿主
            candidates.append("http://host.docker.internal:11434/v1")
            # 容器默认网关（部分 docker 网络配置下可直达宿主/网关 Ollama）
            candidates.append("http://172.17.0.1:11434/v1")
            for c in candidates:
                if c and c not in chain:
                    chain.append(c)

        return chain

    @staticmethod
    def _strip_vendor_prefix(model: str) -> str:
        """剥离模型名中的 vendor 前缀（如 ollama:qwen3:32b → qwen3:32b）。"""
        if ':' in model:
            parts = model.split(':')
            if parts[0] in ('ollama', 'deepseek', 'qwen', 'openai'):
                return ':'.join(parts[1:])
        return model

    def _build_client(self, url: str) -> AsyncOpenAI:
        """按给定 base_url 构建 AsyncOpenAI 客户端（必须显式传 timeout）。"""
        return AsyncOpenAI(
            api_key=self._resolved_key,
            base_url=url,
            timeout=self._llm_timeout,
        )

    async def _chat_once(self, client: AsyncOpenAI, prompt: str, system_prompt: str) -> str:
        """对指定客户端执行一次 chat.completions 调用并累加 token 用量。

        B6：支持 system prompt 分离，启用 prompt caching。返回值仍为 str。
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs = dict(
            model=self._api_model,
            messages=messages,
            temperature=0.1,
            max_tokens=16384,
            timeout=self._llm_timeout,
        )
        # P2-2：通过 provider 注册中心查询是否支持 response_format
        if self._supports_response_format(self.model):
            kwargs["response_format"] = {"type": "json_object"}

        # 本地 Ollama 模型优化（按实际使用的 URL 判定，兼容多候选链）：
        # client.base_url 是 openai.URL 对象而非 str，需先转字符串再判定
        _raw_url = getattr(client, "base_url", None) or self._resolved_url
        if self._is_ollama_model(str(_raw_url)):
            kwargs["extra_body"] = {
                "options": {
                    "num_ctx": 16384,
                    "num_predict": 16384,
                    "think": False,
                },
                # P2-3：Ollama 原生 JSON Schema 结构化输出强约束（顶层字段）
                "format": EXTRACTION_JSON_SCHEMA,
            }
            kwargs["max_tokens"] = 16384
            kwargs["temperature"] = 0.05

        response = await client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        # 捕获 token 用量并累加（response.usage 可能为 None，如某些 ollama 部署）
        usage_dict = None
        if getattr(response, "usage", None):
            u = response.usage
            usage_dict = {
                "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                "total_tokens": getattr(u, "total_tokens", 0) or 0,
            }
        # 优先用 response.model（实际使用的模型，可能与请求不同，如自动路由）
        actual_model = getattr(response, "model", None) or self.model
        self._accumulate_usage(actual_model, usage_dict)
        # F11：日配额熔断。响应已返回（已实际消耗 token），按本次用量计数并检查日配额。
        if usage_dict:
            await _consume_daily_quota(usage_dict["total_tokens"])
        if content:
            logger.info(f"LLM 返回内容长度: {len(content)}")
        return content or ""

    async def _call_llm_api(self, prompt: str, system_prompt: str = "") -> str:
        """调用 LLM API 获取响应。B6：支持 system prompt 分离，启用 prompt caching。

        连接容错增强：
        - 候选 URL 链：主地址连接失败时自动切换备用地址（LLM_FALLBACK_BASE_URLS / 自动探测）；
        - 连接类错误（DNS/连接/超时）做 LLM_CONNECT_RETRIES 次短退避重试（不消耗 token）；
        - 认证/HTTP 状态/JSON 等非连接错误不重试，直接走 HTTP 兜底（与历史行为一致）。

        Token 用量会通过 _accumulate_usage 累加到实例，后续可通过 get_usage_summary() 获取。
        返回值仍为 str（保持向后兼容）；usage 单向累加，不破坏调用方签名。
        """
        url_chain = self._url_chain or [self._resolved_url or settings.LLM_BASE_URL]
        last_conn_exc: Optional[Exception] = None

        # F11：全局并发上限。跨所有提取任务共享信号量，超限时在此排队等待，
        # 防止同一进程内大量并发任务同时打爆 LLM / 本地 Ollama。
        sem = _get_global_sem()
        if sem is not None:
            await sem.acquire()
        try:
            return await self._call_llm_api_locked(
                url_chain, prompt, system_prompt, last_conn_exc
            )
        finally:
            if sem is not None:
                sem.release()

    async def _call_llm_api_locked(
        self,
        url_chain: list[str],
        prompt: str,
        system_prompt: str,
        last_conn_exc: Optional[Exception],
    ) -> str:
        """持有全局并发信号量时执行实际的 LLM 调用（见 _call_llm_api）。"""
        for attempt in range(self._connect_retries + 1):
            for url in url_chain:
                try:
                    client = self._build_client(url)
                    return await self._chat_once(client, prompt, system_prompt)
                except Exception as e:
                    err = _classify_llm_error(e)
                    if err["type"] == "connection_error":
                        last_conn_exc = e
                        logger.warning(
                            f"LLM 连接失败（url={url}, attempt={attempt + 1}）: {err['message'][:300]}"
                        )
                        continue  # 尝试下一个候选 URL
                    if err["type"] == "read_timeout":
                        # F12：读响应超时——请求已发出、可能已消耗 token。不得切换 URL 或重试，
                        # 直接透传，避免双倍计费。
                        logger.warning(
                            f"LLM 读响应超时（url={url}）: {err['message'][:300]}，不重试以避免双倍计费"
                        )
                        raise e
                    # 非连接/超时错误（认证/HTTP/JSON 等）：走 HTTP 兜底，与历史行为一致
                    logger.warning(f"LLM API 调用失败（非连接错误）: {err['message'][:300]}，尝试 HTTP 兜底...")
                    return await self._fallback_http_call(prompt, system_prompt)
            # 本轮所有候选 URL 均连接失败：短退避后重试
            if attempt < self._connect_retries:
                await asyncio.sleep(2 * (attempt + 1))

        # 2) 连接彻底失败：HTTP 兜底（内部跨 URL 链尝试），仍失败则抛出带诊断的异常
        logger.error(
            f"LLM 所有候选地址连接失败（{len(url_chain)} 个）: "
            f"{_classify_llm_error(last_conn_exc)['message'][:300] if last_conn_exc else 'unknown'}"
        )
        return await self._fallback_http_call(prompt, system_prompt)

    async def _fallback_http_call(self, prompt: str, system_prompt: str = "") -> str:
        """HTTP 兜底调用（不依赖 OpenAI SDK）。B6：支持 system prompt。

        连接容错增强：按候选 URL 链逐个尝试，首个成功的地址返回。
        """
        url_chain = self._url_chain or [self._resolved_url or settings.LLM_BASE_URL]
        api_key = self._resolved_key or settings.LLM_API_KEY
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self._api_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 16384,
        }
        # P2-2：通过 provider 注册中心查询是否支持 response_format
        if self._supports_response_format(self.model):
            payload["response_format"] = {"type": "json_object"}

        last_exc: Optional[Exception] = None
        for url in url_chain:
            try:
                # 同步 Ollama 原生参数（兜底路径，num_ctx 需在嵌套 options 中）
                p = dict(payload)
                if self._is_ollama_model(url):
                    p["max_tokens"] = 16384
                    p["temperature"] = 0.05
                    p["options"] = {
                        "num_ctx": 16384,
                        "num_predict": 16384,
                        "think": False,
                    }
                    # P2-3：Ollama 原生 JSON Schema 结构化输出强约束（顶层字段，不放 options 里）
                    p["format"] = EXTRACTION_JSON_SCHEMA

                async with httpx.AsyncClient(timeout=self._llm_timeout) as client:
                    resp = await client.post(
                        f"{url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=p,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    # 捕获 usage 并累加
                    usage_raw = data.get("usage")
                    if usage_raw and isinstance(usage_raw, dict):
                        self._accumulate_usage(
                            data.get("model") or self.model,
                            {
                                "prompt_tokens": usage_raw.get("prompt_tokens", 0) or 0,
                                "completion_tokens": usage_raw.get("completion_tokens", 0) or 0,
                                "total_tokens": usage_raw.get("total_tokens", 0) or 0,
                            },
                        )
                        # F11：日配额熔断（HTTP 兜底路径同样计数）
                        await _consume_daily_quota(
                            int(usage_raw.get("total_tokens", 0) or 0)
                        )
                    return data["choices"][0]["message"]["content"]
            except Exception as e:
                last_exc = e
                if _classify_llm_error(e)["type"] == "read_timeout":
                    # F12：读响应超时不切换地址，避免同一请求双倍计费
                    logger.warning(f"HTTP 兜底调用读超时（url={url}），不再切换地址: {e}")
                    break
                logger.warning(f"HTTP 兜底调用失败（url={url}）: {_classify_llm_error(e)['message'][:300]}")
                continue

        logger.error(f"HTTP 兜底调用全部地址失败: {last_exc}")
        raise last_exc

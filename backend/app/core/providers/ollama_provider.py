"""Ollama (本地 LLM) Provider"""
from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.core.providers.base import BaseLLMProvider, register_provider

logger = logging.getLogger("uvicorn")


def get_ollama_root() -> str:
    """由 OLLAMA_BASE_URL 推导 Ollama 服务根地址（去掉末尾的 /v1 等子路径）。"""
    base = settings.OLLAMA_BASE_URL.rstrip("/")
    # 常见的 OpenAI 兼容路径为 http://host:11434/v1，/api 端点挂在根地址下
    if base.endswith("/v1"):
        return base[:-3]
    return base


async def fetch_installed_model_names(timeout: float = 3.0) -> set[str] | None:
    """查询 Ollama 已安装（已 pull）的模型名集合。

    - 走 Ollama 原生 /api/tags 接口；
    - 成功返回小写的模型名集合；Ollama 连接失败/不可达返回 None（表示"未知"），
      由调用方决定如何展示，避免因 Ollama 未启动导致本地模型管理页面异常。
    """
    url = f"{get_ollama_root()}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        names = set()
        for model in data.get("models", []):
            name = (model.get("name") or "").strip().lower()
            if name:
                names.add(name)
        return names
    except Exception as exc:
        logger.warning(f"[ollama_provider] 无法获取已安装模型列表 {url}: {exc}")
        return None


def is_model_installed(model_name: str, installed: set[str]) -> bool:
    """判断某个本地模型配置是否已在 Ollama 下载。

    规则：精确匹配；配置未带 tag（如 qwen2.5）时，
    兼容 Ollama 默认 tag latest 及任一同名不同 tag 的模型（取冒号前缀）。
    """
    mn = (model_name or "").strip().lower()
    if not mn:
        return False
    if not installed:
        return False
    if mn in installed:
        return True
    if ":" in mn:
        return mn in installed
    if f"{mn}:latest" in installed:
        return True
    return any(n.startswith(f"{mn}:") for n in installed)


@register_provider
class OllamaProvider(BaseLLMProvider):
    """Ollama 本地 LLM Provider

    Ollama 暴露 OpenAI 兼容 API（/v1/chat/completions），无需 API Key。
    常用本地模型：llama3, qwen2.5, glm4, mistral, gemma, phi 等。

    注意：Ollama 模型名通常包含冒号（如 qwen3:32b），
    以此区分远程 API 的同名模型（如 qwen2.5-7b 走 DashScope）。
    """

    name = "ollama"
    model_prefixes = (
        "ollama/",
        "llama",
        "mistral",
        "gemma",
        "glm4",
        "phi",
    )

    @classmethod
    def matches(cls, model: str) -> bool:
        """检查模型名是否匹配此 Provider。

        Ollama 模型名通常包含冒号（如 qwen3:32b、qwen2.5:14b），
        以此区分远程 API 的同名模型（如 qwen2.5-7b）。

        前端可能带 vendor 前缀（如 ollama:qwen3:32b），需正确识别。
        """
        model_lower = model.lower()
        # 先检查标准前缀
        if any(model_lower.startswith(prefix) for prefix in cls.model_prefixes):
            return True
        # 检查带冒号的 Ollama 风格模型名（如 qwen3:32b, qwen2.5:14b）
        if ':' in model_lower:
            parts = model_lower.split(':')
            # 处理 "ollama:qwen3:32b" 这种带 vendor 前缀的格式
            if parts[0] == 'ollama' and len(parts) >= 2:
                return True
            # 提取冒号前的部分，检查是否是已知 Ollama 模型族
            # 注意：模型名可能包含次级版本号，如 qwen2.5:14b 分割后为 ['qwen2.5', '14b']
            # 需要检查 model_family 是否以某个已知族开头（如 qwen2.5 匹配 qwen2）
            model_family = parts[0]
            ollama_families = {'qwen', 'qwen2', 'qwen3', 'llama', 'mistral', 'gemma', 'glm4', 'phi', 'deepseek'}
            if model_family in ollama_families:
                return True
            # 处理次级版本号：qwen2.5 → qwen2, qwen2.7 → qwen2 等
            if any(model_family.startswith(f) for f in ollama_families):
                return True
        return False

    @classmethod
    def get_config(cls) -> tuple[str, str]:
        api_key = settings.OLLAMA_API_KEY
        base_url = settings.OLLAMA_BASE_URL
        return api_key, base_url

    @classmethod
    def supports_response_format(cls) -> bool:
        # Ollama 本地模型不支持 response_format 参数
        return False

    @classmethod
    def get_pricing(cls) -> tuple[float, float]:
        """Ollama 本地部署，无 API 费用。"""
        return (0.0, 0.0)

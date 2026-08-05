"""Ollama (本地 LLM) Provider"""
from __future__ import annotations

from app.config import settings
from app.core.providers.base import BaseLLMProvider, register_provider


@register_provider
class OllamaProvider(BaseLLMProvider):
    """Ollama 本地 LLM Provider

    Ollama 暴露 OpenAI 兼容 API（/v1/chat/completions），无需 API Key。
    常用本地模型：llama3, qwen2.5, glm4, mistral, gemma, phi 等。
    """

    name = "ollama"
    model_prefixes = [
        "ollama/",
        "llama",
        "mistral",
        "gemma",
        "glm4",
        "phi",
    ]

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
    def get_pricing(cls) -> Optional[tuple[float, float]]:
        """Ollama 本地部署，无 API 费用。"""
        return (0.0, 0.0)

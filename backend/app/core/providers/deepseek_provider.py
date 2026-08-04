"""DeepSeek Provider"""
from __future__ import annotations

from app.config import settings
from app.core.providers.base import BaseLLMProvider, register_provider


@register_provider
class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek API Provider"""

    name = "deepseek"
    model_prefixes = ["deepseek"]

    @classmethod
    def get_config(cls) -> tuple[str, str]:
        api_key = settings.DEEPSEEK_API_KEY or settings.LLM_API_KEY
        base_url = settings.DEEPSEEK_BASE_URL or settings.LLM_BASE_URL
        return api_key, base_url

    @classmethod
    def supports_response_format(cls) -> bool:
        return True

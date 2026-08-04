"""OpenAI Provider"""
from __future__ import annotations

from app.config import settings
from app.core.providers.base import BaseLLMProvider, register_provider


@register_provider
class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT Provider"""

    name = "openai"
    model_prefixes = ["gpt-", "o1-", "o3-", "o4-"]

    @classmethod
    def get_config(cls) -> tuple[str, str]:
        api_key = settings.OPENAI_API_KEY or settings.LLM_API_KEY
        base_url = settings.OPENAI_BASE_URL or settings.LLM_BASE_URL
        return api_key, base_url

    @classmethod
    def supports_response_format(cls) -> bool:
        return True

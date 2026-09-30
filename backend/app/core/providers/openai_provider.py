"""OpenAI Provider"""
from __future__ import annotations

from app.config import settings
from app.core.providers.base import BaseLLMProvider, register_provider


@register_provider
class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT Provider"""

    name = "openai"
    model_prefixes = ("gpt-", "o1-", "o3-", "o4-")

    @classmethod
    def get_config(cls) -> tuple[str, str]:
        api_key = settings.OPENAI_API_KEY or settings.LLM_API_KEY
        base_url = settings.OPENAI_BASE_URL or settings.LLM_BASE_URL
        return api_key, base_url

    @classmethod
    def supports_response_format(cls) -> bool:
        return True

    @classmethod
    def get_pricing(cls) -> tuple[float, float] | None:
        """OpenAI 默认定价（美元/百万 token）。
        各子模型（gpt-4o/gpt-4o-mini/o1 等）单价不同，精确计价由 LLMExtractor._MODEL_PRICING_OVERRIDES 处理。
        这里返回 gpt-4o-mini 作为兜底默认值。
        """
        return (0.15, 0.60)

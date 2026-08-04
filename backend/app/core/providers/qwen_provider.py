"""Qwen (通义千问) Provider"""
from __future__ import annotations

from app.config import settings
from app.core.providers.base import BaseLLMProvider, register_provider


@register_provider
class QwenProvider(BaseLLMProvider):
    """阿里通义千问 Provider（通过 DashScope OpenAI 兼容接口）"""

    name = "qwen"
    model_prefixes = ["qwen"]

    @classmethod
    def get_config(cls) -> tuple[str, str]:
        api_key = settings.QWEN_API_KEY or settings.LLM_API_KEY
        base_url = settings.QWEN_BASE_URL or settings.LLM_BASE_URL
        return api_key, base_url

    @classmethod
    def supports_response_format(cls) -> bool:
        # Qwen 通过 prompt 引导 JSON 输出，不使用 response_format 参数
        return False

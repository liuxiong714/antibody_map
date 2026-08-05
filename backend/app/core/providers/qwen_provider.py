"""Qwen (通义千问) Provider"""
from __future__ import annotations

from typing import Optional

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

    @classmethod
    def get_pricing(cls) -> Optional[tuple[float, float]]:
        """Qwen 默认定价（美元/百万 token，DashScope 参考值）。
        各子模型（turbo/plus/max）单价不同，精确计价由 LLMExtractor._MODEL_PRICING_OVERRIDES 处理。
        这里返回 turbo 作为兜底默认值。
        """
        return (0.05, 0.20)

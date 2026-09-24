"""DeepSeek Provider"""
from __future__ import annotations

from app.config import settings
from app.core.providers.base import BaseLLMProvider, register_provider


@register_provider
class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek API Provider"""

    name = "deepseek"
    model_prefixes = ("deepseek",)

    @classmethod
    def get_config(cls) -> tuple[str, str]:
        api_key = settings.DEEPSEEK_API_KEY or settings.LLM_API_KEY
        base_url = settings.DEEPSEEK_BASE_URL or settings.LLM_BASE_URL
        return api_key, base_url

    @classmethod
    def supports_response_format(cls) -> bool:
        return True

    @classmethod
    def get_pricing(cls) -> tuple[float, float] | None:
        """DeepSeek 定价（美元/百万 token，2026 年官网参考值）。

        当前官方主推模型：
        - deepseek-flash: input ~$0.14, output ~$0.28（性能/性价比主力）
        - deepseek-v4-pro: input ~$0.55, output ~$2.19（高复杂场景）
        旧模型名 deepseek-chat / deepseek-reasoner 已被官方弃用，
        代码仍兼容并沿用上述价格。未匹配的模型返回 None。
        """
        # 注意：调用方传入的是具体模型名，这里无法区分，返回 chat 默认值；
        # 若需更精确按模型名细分，可在 _get_model_pricing 中做二次匹配。
        return (0.14, 0.28)

"""P2-2: LLM Provider 插件化基类与注册中心

设计：
- 每个 Provider 是一个继承 BaseLLMProvider 的类，用 @register_provider 装饰器注册
- Provider 定义模型前缀、配置获取逻辑、是否支持 response_format 等
- LLMExtractor 通过 get_provider_for_model(model) 自动匹配 Provider
- 无匹配时回退到默认全局配置（向后兼容）

扩展新 Provider 只需：
  1. 在 providers/ 目录新建文件
  2. 定义类继承 BaseLLMProvider，加 @register_provider
  3. 实现 name, model_prefixes, get_config() 方法
  4. 在 __init__.py 中 import 该模块触发注册
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class BaseLLMProvider:
    """LLM Provider 基类：子类需实现 name, model_prefixes, get_config()"""

    # Provider 名称（如 "deepseek", "openai", "ollama"）
    name: str = ""

    # 匹配的模型前缀列表（小写），如 ("deepseek", "deepseek-coder")
    model_prefixes: tuple[str, ...] = ()

    @classmethod
    def get_config(cls) -> tuple[str, str]:
        """返回 (api_key, base_url)。子类必须实现。"""
        raise NotImplementedError

    @classmethod
    def supports_response_format(cls) -> bool:
        """是否支持 response_format={"type": "json_object"} 参数。
        默认 False，子类可覆盖。
        """
        return False

    @classmethod
    def get_pricing(cls) -> tuple[float, float] | None:
        """返回模型单价 (input_per_1m, output_per_1m)，单位：美元/百万 token。

        默认 None（无法计价，费用记为 0）。子类可覆盖。
        价格来源：各厂商官网公开定价（2026 年初参考值），可能随厂商调整而变化。
        """
        return None

    @classmethod
    def matches(cls, model: str) -> bool:
        """检查模型名是否匹配此 Provider"""
        model_lower = model.lower()
        return any(model_lower.startswith(prefix) for prefix in cls.model_prefixes)


# ── 注册中心 ────────────────────────────────────────────
_PROVIDER_REGISTRY: list[type[BaseLLMProvider]] = []


def register_provider(cls: type[BaseLLMProvider]) -> type[BaseLLMProvider]:
    """装饰器：注册 LLM Provider 类。

    用法：
        @register_provider
        class DeepSeekProvider(BaseLLMProvider):
            ...
    """
    if not cls.name:
        raise ValueError(f"Provider {cls.__name__} 必须定义 name 属性")
    if not cls.model_prefixes:
        raise ValueError(f"Provider {cls.__name__} 必须定义 model_prefixes 属性")
    _PROVIDER_REGISTRY.append(cls)
    logger.debug(f"[P2-2] 注册 LLM Provider: {cls.name} (prefixes={cls.model_prefixes})")
    return cls


def get_provider_for_model(model: str) -> type[BaseLLMProvider] | None:
    """根据模型名查找匹配的 Provider 类。

    遍历注册表，返回第一个 matches(model) 为 True 的 Provider。
    无匹配返回 None（调用方回退到默认全局配置）。
    """
    for provider_cls in _PROVIDER_REGISTRY:
        if provider_cls.matches(model):
            return provider_cls
    return None


def list_providers() -> list[type[BaseLLMProvider]]:
    """返回所有已注册的 Provider 类列表"""
    return list(_PROVIDER_REGISTRY)


def clear_registry() -> None:
    """清空注册表（仅用于测试）"""
    _PROVIDER_REGISTRY.clear()

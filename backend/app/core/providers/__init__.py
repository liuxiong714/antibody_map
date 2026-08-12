"""P2-2: LLM Provider 插件化包

导入所有 Provider 模块以触发注册。
扩展新 Provider 只需：
  1. 在本目录新建 xxx_provider.py
  2. 定义类继承 BaseLLMProvider，加 @register_provider
  3. 在下方 import 该模块
"""
from app.core.providers.base import (
    BaseLLMProvider,
    register_provider,
    get_provider_for_model,
    list_providers,
    clear_registry,
)

# 导入所有 Provider 模块以触发 @register_provider 注册
from app.core.providers import deepseek_provider  # noqa: F401
from app.core.providers import openai_provider  # noqa: F401
from app.core.providers import qwen_provider  # noqa: F401
from app.core.providers import ollama_provider  # noqa: F401

__all__ = [
    "BaseLLMProvider",
    "register_provider",
    "get_provider_for_model",
    "list_providers",
    "clear_registry",
]

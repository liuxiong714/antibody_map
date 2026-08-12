"""Ollama (本地 LLM) Provider"""
from __future__ import annotations

from app.config import settings
from app.core.providers.base import BaseLLMProvider, register_provider


@register_provider
class OllamaProvider(BaseLLMProvider):
    """Ollama 本地 LLM Provider

    Ollama 暴露 OpenAI 兼容 API（/v1/chat/completions），无需 API Key。
    常用本地模型：llama3, qwen2.5, glm4, mistral, gemma, phi 等。

    注意：Ollama 模型名通常包含冒号（如 qwen3:32b），
    以此区分远程 API 的同名模型（如 qwen2.5-7b 走 DashScope）。
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

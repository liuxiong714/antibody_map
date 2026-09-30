"""P2-2 LLM Provider 插件化测试

测试目标：
1. 注册中心：@register_provider 正确注册
2. 模型匹配：get_provider_for_model 正确匹配
3. 各 Provider 配置：deepseek/openai/qwen/ollama
4. supports_response_format：DeepSeek/OpenAI=True, Qwen/Ollama=False
5. LLMExtractor 集成：_resolve_api_config 使用 provider
6. LLMExtractor._supports_response_format 正确委派
7. 向后兼容：无匹配时回退到全局配置
8. 动态注册：运行时新增 Provider
9. 已注册 Provider 数量正确
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.core.providers import (
    BaseLLMProvider,
    register_provider,
    get_provider_for_model,
    list_providers,
    clear_registry,
)
from app.core.providers import deepseek_provider, openai_provider, qwen_provider, ollama_provider
from app.core.llm_extractor import LLMExtractor


# ── 测试 1: 4 个内置 Provider 已注册 ───────────────────
def test_builtin_providers_registered():
    """导入 providers 包后，4 个内置 Provider 自动注册"""
    # 重新导入以触发注册（如果之前被 clear 了）
    import importlib
    import app.core.providers as providers_pkg
    importlib.reload(providers_pkg)

    names = [p.name for p in list_providers()]
    assert "deepseek" in names
    assert "openai" in names
    assert "qwen" in names
    assert "ollama" in names
    print(f"✓ test_builtin_providers_registered ({len(names)} 个: {names})")


# ── 测试 2: 模型匹配 ───────────────────────────────────
def test_model_matching():
    """get_provider_for_model 正确匹配各 Provider"""
    import importlib
    import app.core.providers as providers_pkg
    importlib.reload(providers_pkg)

    # DeepSeek
    p = get_provider_for_model("deepseek-chat")
    assert p is not None and p.name == "deepseek"

    # OpenAI
    p = get_provider_for_model("gpt-4o")
    assert p is not None and p.name == "openai"
    p = get_provider_for_model("o1-preview")
    assert p is not None and p.name == "openai"

    # Qwen
    p = get_provider_for_model("qwen-max")
    assert p is not None and p.name == "qwen"

    # Ollama
    p = get_provider_for_model("llama3")
    assert p is not None and p.name == "ollama"
    p = get_provider_for_model("mistral:7b")
    assert p is not None and p.name == "ollama"
    p = get_provider_for_model("ollama/qwen2.5")
    assert p is not None and p.name == "ollama"
    print("✓ test_model_matching")


# ── 测试 3: 无匹配返回 None ────────────────────────────
def test_no_match_returns_none():
    """未知模型返回 None"""
    import importlib
    import app.core.providers as providers_pkg
    importlib.reload(providers_pkg)

    p = get_provider_for_model("unknown-model-xyz")
    assert p is None
    print("✓ test_no_match_returns_none")


# ── 测试 4: DeepSeek 配置 ──────────────────────────────
def test_deepseek_provider_config():
    """DeepSeek Provider 返回正确的 api_key 和 base_url"""
    key, url = deepseek_provider.DeepSeekProvider.get_config()
    # 回退到全局或 DEEPSEEK_*
    assert key in (settings.DEEPSEEK_API_KEY, settings.LLM_API_KEY)
    assert url in (settings.DEEPSEEK_BASE_URL, settings.LLM_BASE_URL)
    print("✓ test_deepseek_provider_config")


# ── 测试 5: OpenAI 配置 + supports_response_format ─────
def test_openai_provider_config():
    """OpenAI Provider 配置和 response_format 支持"""
    key, url = openai_provider.OpenAIProvider.get_config()
    assert key in (settings.OPENAI_API_KEY, settings.LLM_API_KEY)
    assert url in (settings.OPENAI_BASE_URL, settings.LLM_BASE_URL)
    assert openai_provider.OpenAIProvider.supports_response_format() is True
    print("✓ test_openai_provider_config")


# ── 测试 6: Qwen 配置 + 不支持 response_format ─────────
def test_qwen_provider_config():
    """Qwen Provider 配置和不支持 response_format"""
    key, url = qwen_provider.QwenProvider.get_config()
    assert key in (settings.QWEN_API_KEY, settings.LLM_API_KEY)
    assert url in (settings.QWEN_BASE_URL, settings.LLM_BASE_URL)
    assert qwen_provider.QwenProvider.supports_response_format() is False
    print("✓ test_qwen_provider_config")


# ── 测试 7: Ollama 配置 + 不支持 response_format ───────
def test_ollama_provider_config():
    """Ollama Provider 配置和不支持 response_format"""
    key, url = ollama_provider.OllamaProvider.get_config()
    assert key == settings.OLLAMA_API_KEY
    assert url == settings.OLLAMA_BASE_URL
    assert ollama_provider.OllamaProvider.supports_response_format() is False
    print("✓ test_ollama_provider_config")


# ── 测试 8: LLMExtractor 集成 - _resolve_api_config ────
def test_extractor_uses_provider_registry():
    """LLMExtractor._resolve_api_config 使用 provider 注册中心"""
    import importlib
    import app.core.providers as providers_pkg
    importlib.reload(providers_pkg)

    # Ollama 模型应通过 provider 解析
    key, url = LLMExtractor._resolve_api_config("llama3")
    assert url == settings.OLLAMA_BASE_URL
    assert key == "ollama"

    # DeepSeek 模型
    key, url = LLMExtractor._resolve_api_config("deepseek-chat")
    assert url in (settings.DEEPSEEK_BASE_URL, settings.LLM_BASE_URL)
    print("✓ test_extractor_uses_provider_registry")


# ── 测试 9: LLMExtractor._supports_response_format ─────
def test_extractor_supports_response_format():
    """LLMExtractor._supports_response_format 正确委派到 provider"""
    import importlib
    import app.core.providers as providers_pkg
    importlib.reload(providers_pkg)

    # DeepSeek/OpenAI 支持
    assert LLMExtractor._supports_response_format("deepseek-chat") is True
    assert LLMExtractor._supports_response_format("gpt-4o") is True

    # Qwen/Ollama 不支持
    assert LLMExtractor._supports_response_format("qwen-max") is False
    assert LLMExtractor._supports_response_format("llama3") is False
    print("✓ test_extractor_supports_response_format")


# ── 测试 10: 向后兼容 - 无匹配回退 ─────────────────────
def test_backward_compatibility_no_match():
    """无匹配 provider 时回退到全局 LLM_API_KEY / LLM_BASE_URL"""
    import importlib
    import app.core.providers as providers_pkg
    importlib.reload(providers_pkg)

    key, url = LLMExtractor._resolve_api_config("unknown-model-xyz")
    # 回退到全局配置
    assert key == settings.LLM_API_KEY
    assert url == settings.LLM_BASE_URL

    # response_format 回退到旧逻辑（不包含 deepseek/gpt- → False）
    assert LLMExtractor._supports_response_format("unknown-model-xyz") is False
    print("✓ test_backward_compatibility_no_match")


# ── 测试 11: 动态注册新 Provider ───────────────────────
def test_dynamic_provider_registration():
    """运行时动态注册新 Provider"""
    import importlib
    import app.core.providers as providers_pkg
    importlib.reload(providers_pkg)

    @register_provider
    class ClaudeProvider(BaseLLMProvider):
        name = "claude"
        model_prefixes = ["claude-", "anthropic/"]

        @classmethod
        def get_config(cls):
            return ("claude-key", "https://api.anthropic.com/v1")

        @classmethod
        def supports_response_format(cls):
            return False

    try:
        p = get_provider_for_model("claude-3-opus")
        assert p is not None
        assert p.name == "claude"
        key, url = p.get_config()
        assert key == "claude-key"
        assert url == "https://api.anthropic.com/v1"
    finally:
        # 清理：移除动态注册的 provider
        from app.core.providers.base import _PROVIDER_REGISTRY
        _PROVIDER_REGISTRY.remove(ClaudeProvider)
    print("✓ test_dynamic_provider_registration")


# ── 测试 12: @register_provider 校验 ───────────────────
def test_register_provider_validation():
    """@register_provider 校验 name 和 model_prefixes 必须定义"""
    import importlib
    import app.core.providers as providers_pkg
    importlib.reload(providers_pkg)

    # 缺少 name
    try:
        @register_provider
        class NoNameProvider(BaseLLMProvider):
            model_prefixes = ["test-"]
            @classmethod
            def get_config(cls):
                return ("", "")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "name" in str(e).lower()

    # 缺少 model_prefixes
    try:
        @register_provider
        class NoPrefixProvider(BaseLLMProvider):
            name = "noprefix"
            @classmethod
            def get_config(cls):
                return ("", "")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "model_prefixes" in str(e).lower()
    print("✓ test_register_provider_validation")


def run_all():
    tests = [
        test_builtin_providers_registered,
        test_model_matching,
        test_no_match_returns_none,
        test_deepseek_provider_config,
        test_openai_provider_config,
        test_qwen_provider_config,
        test_ollama_provider_config,
        test_extractor_uses_provider_registry,
        test_extractor_supports_response_format,
        test_backward_compatibility_no_match,
        test_dynamic_provider_registration,
        test_register_provider_validation,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: 异常 {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"P2-2 LLM Provider 插件化测试: {passed}/{len(tests)} 通过, {failed} 失败")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)

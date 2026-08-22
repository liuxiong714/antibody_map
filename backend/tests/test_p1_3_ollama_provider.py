"""P1-3 本地 LLM 支持（Ollama provider）测试

测试目标：
1. 配置存在：OLLAMA_API_KEY / OLLAMA_BASE_URL 在 settings 中
2. 模型前缀解析：ollama/, llama, mistral, gemma, glm4, phi → OLLAMA 配置
3. response_format 跳过：Ollama 模型不传 response_format
4. 兜底 HTTP 调用使用解析后的 base_url（非全局默认）
5. 向后兼容：deepseek/gpt-/qwen 仍走原有配置
6. 实例属性 _resolved_key / _resolved_url 正确
"""
from __future__ import annotations

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.core.llm_extractor import LLMExtractor


# ── 测试 1: 配置存在 ───────────────────────────────────
def test_ollama_config_exists():
    """OLLAMA_API_KEY / OLLAMA_BASE_URL 在 settings 中有默认值"""
    assert hasattr(settings, "OLLAMA_API_KEY")
    assert hasattr(settings, "OLLAMA_BASE_URL")
    # OLLAMA_BASE_URL 指向 Ollama OpenAI 兼容端点（主机随运行环境变化：
    # 本地为 localhost，容器/WSL 内为网关 IP 如 172.27.96.1）
    assert settings.OLLAMA_BASE_URL.startswith("http")
    assert ":11434" in settings.OLLAMA_BASE_URL
    assert settings.OLLAMA_BASE_URL.endswith("/v1")
    assert settings.OLLAMA_API_KEY == "ollama"
    print("✓ test_ollama_config_exists")


# ── 测试 2: 模型前缀解析 ───────────────────────────────
def test_ollama_model_prefix_resolution():
    """ollama/, llama, mistral, gemma, glm4, phi → OLLAMA 配置"""
    test_cases = [
        ("ollama/llama3", "ollama", settings.OLLAMA_BASE_URL),
        ("llama3", "ollama", settings.OLLAMA_BASE_URL),
        ("llama3:8b", "ollama", settings.OLLAMA_BASE_URL),
        ("mistral", "ollama", settings.OLLAMA_BASE_URL),
        ("mistral:7b", "ollama", settings.OLLAMA_BASE_URL),
        ("gemma:2b", "ollama", settings.OLLAMA_BASE_URL),
        ("glm4", "ollama", settings.OLLAMA_BASE_URL),
        ("phi3", "ollama", settings.OLLAMA_BASE_URL),
    ]
    for model, expected_key, expected_url in test_cases:
        key, url = LLMExtractor._resolve_api_config(model)
        assert key == expected_key, f"模型 {model}: key={key}, 期望 {expected_key}"
        assert url == expected_url, f"模型 {model}: url={url}, 期望 {expected_url}"
    print(f"✓ test_ollama_model_prefix_resolution ({len(test_cases)} 个模型)")


# ── 测试 3: 向后兼容 ───────────────────────────────────
def test_backward_compatibility_deepseek_openai_qwen():
    """deepseek/gpt-/qwen 仍走原有配置（未被 Ollama 劫持）"""
    # deepseek
    key, url = LLMExtractor._resolve_api_config("deepseek-chat")
    # 回退到全局 LLM_API_KEY / LLM_BASE_URL（除非设置了 DEEPSEEK_*）
    assert url in (settings.LLM_BASE_URL, settings.DEEPSEEK_BASE_URL)

    # gpt-4o
    key, url = LLMExtractor._resolve_api_config("gpt-4o")
    assert url in (settings.LLM_BASE_URL, settings.OPENAI_BASE_URL)

    # qwen-max（注意：qwen 前缀优先于 ollama 的 llama 等）
    key, url = LLMExtractor._resolve_api_config("qwen-max")
    assert url in (settings.LLM_BASE_URL, settings.QWEN_BASE_URL)
    # 确保 qwen 没有被错误地解析为 ollama
    assert "11434" not in url or settings.QWEN_BASE_URL == "http://localhost:11434/v1"
    print("✓ test_backward_compatibility_deepseek_openai_qwen")


# ── 测试 4: 实例属性 _resolved_key/_resolved_url ────────
def test_instance_resolved_attributes():
    """实例创建后 _resolved_key/_resolved_url 正确"""
    # Ollama 模型
    ext = LLMExtractor(model="llama3")
    assert ext._resolved_url == settings.OLLAMA_BASE_URL
    assert ext._resolved_key == "ollama"
    assert ext.model == "llama3"

    # 显式参数覆盖
    ext2 = LLMExtractor(model="llama3", base_url="http://192.168.1.100:11434/v1", api_key="mykey")
    assert ext2._resolved_url == "http://192.168.1.100:11434/v1"
    assert ext2._resolved_key == "mykey"
    print("✓ test_instance_resolved_attributes")


# ── 测试 5: response_format 对 Ollama 跳过 ──────────────
def test_response_format_skipped_for_ollama():
    """Ollama 模型调用时不传 response_format 参数"""
    ext = LLMExtractor(model="llama3")

    # Mock client.chat.completions.create 捕获 kwargs
    captured_kwargs = {}

    async def fake_create(**kwargs):
        captured_kwargs.update(kwargs)
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"data_points": []}'
        return mock_resp

    ext.client.chat.completions.create = AsyncMock(side_effect=fake_create)

    asyncio.run(ext._call_llm_api("test prompt"))

    assert "response_format" not in captured_kwargs, \
        f"Ollama 模型不应传 response_format, 实际传了: {captured_kwargs.get('response_format')}"
    assert captured_kwargs["model"] == "llama3"
    assert captured_kwargs["temperature"] == 0.1
    print("✓ test_response_format_skipped_for_ollama")


# ── 测试 6: response_format 对 DeepSeek 保留 ────────────
def test_response_format_kept_for_deepseek():
    """DeepSeek 模型调用时仍传 response_format 参数（向后兼容）"""
    ext = LLMExtractor(model="deepseek-chat")

    captured_kwargs = {}

    async def fake_create(**kwargs):
        captured_kwargs.update(kwargs)
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"data_points": []}'
        return mock_resp

    ext.client.chat.completions.create = AsyncMock(side_effect=fake_create)

    asyncio.run(ext._call_llm_api("test prompt"))

    assert "response_format" in captured_kwargs, \
        "DeepSeek 模型应传 response_format"
    assert captured_kwargs["response_format"] == {"type": "json_object"}
    print("✓ test_response_format_kept_for_deepseek")


# ── 测试 7: 兜底 HTTP 调用使用解析后的 base_url ─────────
def test_fallback_http_uses_resolved_url():
    """_fallback_http_call 使用 self._resolved_url 而非全局 LLM_BASE_URL"""
    ext = LLMExtractor(model="llama3", base_url="http://my-ollama:11434/v1")

    captured_url = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"data_points": []}'}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            captured_url["url"] = url
            return FakeResponse()

    with patch("app.core.extraction.llm_client.httpx.AsyncClient", FakeClient):
        result = asyncio.run(ext._fallback_http_call("test"))

    assert "my-ollama:11434" in captured_url["url"], \
        f"兜底调用应使用解析后的 URL, 实际: {captured_url['url']}"
    assert result == '{"data_points": []}'
    print("✓ test_fallback_http_uses_resolved_url")


# ── 测试 8: 兜底 HTTP 调用对 Ollama 跳过 response_format ─
def test_fallback_http_skips_response_format_for_ollama():
    """兜底 HTTP 调用对 Ollama 模型不传 response_format"""
    ext = LLMExtractor(model="llama3")

    captured_payload = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None, **kwargs):
            captured_payload.update(json or {})
            return FakeResponse()

    with patch("app.core.extraction.llm_client.httpx.AsyncClient", FakeClient):
        asyncio.run(ext._fallback_http_call("test"))

    assert "response_format" not in captured_payload, \
        f"Ollama 兜底调用不应传 response_format: {captured_payload.get('response_format')}"
    print("✓ test_fallback_http_skips_response_format_for_ollama")


# ── 测试 9: 环境变量覆盖 Ollama 配置 ───────────────────
def test_ollama_env_override():
    """通过环境变量覆盖 OLLAMA_BASE_URL（模拟用户自定义 Ollama 服务器地址）"""
    # 由于 settings 在模块加载时已初始化，这里测试 _resolve_api_config 能正确读取 settings
    # 用户可以通过 .env 文件或环境变量设置 OLLAMA_BASE_URL=http://192.168.1.100:11434/v1
    # 我们模拟 settings 被修改的情况
    original_url = settings.OLLAMA_BASE_URL
    try:
        # 模拟用户自定义 Ollama 地址
        settings.OLLAMA_BASE_URL = "http://192.168.1.100:11434/v1"
        key, url = LLMExtractor._resolve_api_config("llama3")
        assert url == "http://192.168.1.100:11434/v1"
        assert key == "ollama"
    finally:
        settings.OLLAMA_BASE_URL = original_url
    print("✓ test_ollama_env_override")


def run_all():
    tests = [
        test_ollama_config_exists,
        test_ollama_model_prefix_resolution,
        test_backward_compatibility_deepseek_openai_qwen,
        test_instance_resolved_attributes,
        test_response_format_skipped_for_ollama,
        test_response_format_kept_for_deepseek,
        test_fallback_http_uses_resolved_url,
        test_fallback_http_skips_response_format_for_ollama,
        test_ollama_env_override,
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
    print(f"P1-3 Ollama 本地 LLM 测试: {passed}/{len(tests)} 通过, {failed} 失败")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)

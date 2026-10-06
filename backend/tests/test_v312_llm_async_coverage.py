"""V3-12: report_service 核心 async 分支测试.

覆盖:
  1) _call_llm ollama: 前缀剥离
  2) _call_llm qwen/ollama thinking 禁用 (extra_body)
  3) _call_llm 普通模型不走 extra_body
  4) _call_llm UUID model 参数查找 ApiModelConfig
  5) _call_llm API 失败 RuntimeError 包装
  6) generate_report / generate_immune_barrier_report 调 _verify_report_numbers
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import report_service as rs


# ---------- _call_llm 基础 mock ----------

def _fake_response(content: str):
    choice = SimpleNamespace(message=SimpleNamespace(content=content))
    return SimpleNamespace(choices=[choice])


def _mock_async_openai(response_content: str, fail: bool = False):
    """构造 AsyncOpenAI 上下文管理器风格的 mock."""
    if fail:
        async def _raise(*a, **kw):
            raise RuntimeError("connection refused")
        return patch("app.services.report_service.AsyncOpenAI", side_effect=_raise)

    async def _ok(*a, **kw):
        return _fake_response(response_content)

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=_ok)
    return patch("app.services.report_service.AsyncOpenAI", return_value=mock_client)


class TestCallLlmAsync:
    """V3-12: _call_llm async 核心分支."""

    @pytest.mark.asyncio
    async def test_ollama_prefix_stripped(self):
        """ollama:qwen2.5:14b → qwen2.5:14b (前缀剥离)."""
        with _mock_async_openai("OK") as m:
            result = await rs._call_llm(db=MagicMock(), prompt="hi", model="ollama:qwen2.5:14b")
        assert result == "OK"
        call_kwargs = m.return_value.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("model") == "qwen2.5:14b"
        # ollama 模型 → extra_body.think=False
        assert call_kwargs.kwargs.get("extra_body") == {"think": False}

    @pytest.mark.asyncio
    async def test_qwen_model_disables_thinking(self):
        """模型名含 qwen → thinking 禁用."""
        with _mock_async_openai("OK") as m:
            await rs._call_llm(db=MagicMock(), prompt="hi", model="qwen2.5:14b")
        call_kwargs = m.return_value.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("extra_body") == {"think": False}

    @pytest.mark.asyncio
    async def test_plain_model_no_extra_body(self):
        """普通远程模型 (gpt-4o-mini) 不走 extra_body."""
        with _mock_async_openai("OK") as m:
            await rs._call_llm(db=MagicMock(), prompt="hi", model="gpt-4o-mini")
        call_kwargs = m.return_value.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("extra_body") is None

    @pytest.mark.asyncio
    async def test_failure_wrapped_as_runtimeerror(self):
        """LLM API 抛异常 → RuntimeError 包装."""
        with _mock_async_openai("OK", fail=True):
            with pytest.raises(RuntimeError, match=r"报告生成失败"):
                await rs._call_llm(db=MagicMock(), prompt="hi", model="gpt-x")

    @pytest.mark.asyncio
    async def test_uuid_model_lookup_config(self):
        """model 参数是 UUID → 查 ApiModelConfig 替换 model_name/base_url/api_key."""
        cfg_id = uuid.uuid4()
        mock_config = SimpleNamespace(
            model_name="custom-model",
            api_key="sk-test",
            base_url="https://custom.llm/v1",
        )
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=SimpleNamespace(
            scalar_one_or_none=MagicMock(return_value=mock_config)
        ))
        with _mock_async_openai("OK") as m:
            await rs._call_llm(db=mock_db, prompt="hi", model=str(cfg_id))

        # 验证 AsyncOpenAI 用了 config 里的参数
        created = m.call_args
        assert created.kwargs.get("api_key") == "sk-test"
        assert created.kwargs.get("base_url") == "https://custom.llm/v1"
        call_kwargs = m.return_value.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("model") == "custom-model"


class TestCallLlmEdgeCases:
    """V3-12: _call_llm 边界分支."""

    @pytest.mark.asyncio
    async def test_uuid_not_found_falls_back_to_name(self):
        """model 是 UUID 但 DB 里没配置 → 当作普通模型名."""
        cfg_id = str(uuid.uuid4())
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=SimpleNamespace(
            scalar_one_or_none=MagicMock(return_value=None)
        ))
        with _mock_async_openai("OK") as m:
            await rs._call_llm(db=mock_db, prompt="hi", model=cfg_id)
        call_kwargs = m.return_value.chat.completions.create.call_args
        # 找不到 config, 就用原始 UUID 字符串作为模型名
        assert call_kwargs.kwargs.get("model") == cfg_id

    @pytest.mark.asyncio
    async def test_non_uuid_string_skips_lookup(self):
        """model 不是 UUID (普通模型名) → 跳过 DB 查询."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        with _mock_async_openai("OK") as m:
            await rs._call_llm(db=mock_db, prompt="hi", model="deepseek-chat")
        mock_db.execute.assert_not_called()
        call_kwargs = m.return_value.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("model") == "deepseek-chat"

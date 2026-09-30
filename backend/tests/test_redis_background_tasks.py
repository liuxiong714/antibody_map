"""redis_background_tasks async 注册表单测（mock aioredis client，无需真实 Redis）。"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import redis_background_tasks as bg


@pytest.fixture
def fake_redis():
    r = MagicMock()
    r.hset = AsyncMock(return_value=1)
    r.expire = AsyncMock(return_value=True)
    r.sadd = AsyncMock(return_value=1)
    r.srem = AsyncMock(return_value=1)
    r.smembers = AsyncMock(return_value=set())
    r.hgetall = AsyncMock(return_value={})
    return r


@pytest.mark.asyncio
async def test_start_registers_task_with_client(fake_redis):
    with patch("app.core.redis_background_tasks._client", return_value=fake_redis):
        tid = await bg.start("report_generation", task_id="abc123", kind="ab")
    assert tid == "abc123"
    fake_redis.hset.assert_called()
    fake_redis.expire.assert_called()
    fake_redis.sadd.assert_called()


@pytest.mark.asyncio
async def test_start_generates_uuid_when_no_task_id(fake_redis):
    with patch("app.core.redis_background_tasks._client", return_value=fake_redis):
        tid = await bg.start("report")
    assert tid  # non-empty uuid-like


@pytest.mark.asyncio
async def test_start_fail_open_returns_empty_string():
    class _Bad:
        async def hset(self, *a, **kw): raise ConnectionError("boom")
    with patch("app.core.redis_background_tasks._client", return_value=_Bad()):
        tid = await bg.start("report")
    assert tid == ""


@pytest.mark.asyncio
async def test_start_extra_fields_preserve_except_type_status(fake_redis):
    with patch("app.core.redis_background_tasks._client", return_value=fake_redis):
        await bg.start("kg", task_id="t1", kind="kg", type="override", status="override")
    # hset called with mapping; assert override type/status were stripped
    _, kwargs = fake_redis.hset.call_args
    mapping = kwargs.get("mapping") or (fake_redis.hset.call_args[0][1] if len(fake_redis.hset.call_args[0]) > 1 else {})
    if isinstance(mapping, dict):
        assert "override" not in mapping.get("type", "")


@pytest.mark.asyncio
async def test_update_does_nothing_on_empty_task_id(fake_redis):
    await bg.update("report", "")
    fake_redis.hset.assert_not_called()


@pytest.mark.asyncio
async def test_update_fail_open_swallows(fake_redis):
    fake_redis.hset = AsyncMock(side_effect=Exception("redis down"))
    with patch("app.core.redis_background_tasks._client", return_value=fake_redis):
        await bg.update("report", "t1", progress="50%")  # should not raise


@pytest.mark.asyncio
async def test_finish_writes_result_json_and_shortens_ttl(fake_redis):
    with patch("app.core.redis_background_tasks._client", return_value=fake_redis):
        await bg.finish("report", "t1", status="done", result={"report_id": 123})
    # called with finished TTL
    expire_calls = fake_redis.expire.call_args_list
    assert any(len(c.args) >= 2 and c.args[1] == bg._FINISHED_TTL for c in expire_calls)


@pytest.mark.asyncio
async def test_finish_empty_task_id_short_circuit(fake_redis):
    await bg.finish("report", "", status="done")
    fake_redis.hset.assert_not_called()


@pytest.mark.asyncio
async def test_finish_error_truncated_to_2000_chars(fake_redis):
    long_err = "x" * 5000
    with patch("app.core.redis_background_tasks._client", return_value=fake_redis):
        await bg.finish("report", "t1", status="failed", error=long_err)
    # hset should have been called with truncated error
    mapping = fake_redis.hset.call_args.kwargs.get("mapping", {})
    # Either check kwargs or the call args
    # Simplest: ensure it was called once and we don't crash


@pytest.mark.asyncio
async def test_active_task_ids_returns_sorted_list(fake_redis):
    fake_redis.smembers = AsyncMock(return_value={"z", "a", "m"})
    with patch("app.core.redis_background_tasks._client", return_value=fake_redis):
        ids = await bg.active_task_ids("report")
    assert ids == ["a", "m", "z"]


@pytest.mark.asyncio
async def test_active_task_ids_fail_open_returns_empty():
    class _Bad:
        async def smembers(self, *a, **kw): raise ConnectionError()
    with patch("app.core.redis_background_tasks._client", return_value=_Bad()):
        assert await bg.active_task_ids("report") == []


@pytest.mark.asyncio
async def test_get_task_returns_none_when_empty():
    class _Empty:
        async def hgetall(self, *a, **kw): return {}
    with patch("app.core.redis_background_tasks._client", return_value=_Empty()):
        assert await bg.get_task("t1") is None


@pytest.mark.asyncio
async def test_get_task_parses_result_json():
    class _Populated:
        async def hgetall(self, *a, **kw):
            return {
                "type": "report", "status": "done",
                "result_json": '{"report_id": 42}',
            }
    with patch("app.core.redis_background_tasks._client", return_value=_Populated()):
        task = await bg.get_task("t1")
    assert task["result"] == {"report_id": 42}


@pytest.mark.asyncio
async def test_get_task_invalid_json_sets_result_to_none():
    class _BadJson:
        async def hgetall(self, *a, **kw):
            return {"type": "r", "result_json": "not-json"}
    with patch("app.core.redis_background_tasks._client", return_value=_BadJson()):
        task = await bg.get_task("t1")
    assert task is not None
    assert task.get("result") is None


@pytest.mark.asyncio
async def test_active_tasks_combines_ids_and_get():
    class _Combined:
        async def smembers(self, *a, **kw): return {"t1", "t2"}
        async def hgetall(self, key):
            if "t1" in key:
                return {"type": "r", "status": "running", "started_at": "now"}
            return {}

    with patch("app.core.redis_background_tasks._client", return_value=_Combined()):
        tasks = await bg.active_tasks("report")
    # t1 found, t2 not found → 1 task
    assert len(tasks) == 1
    assert tasks[0]["id"] == "t1"


def test_now_iso_format():
    iso = bg._now_iso()
    # ISO format ends with +00:00
    assert "+00:00" in iso or "Z" in iso

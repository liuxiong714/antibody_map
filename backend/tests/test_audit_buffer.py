"""audit.py C4 buffering logic unit tests (separate from stdout-path tests)."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import audit as audit_module


@pytest.fixture(autouse=True)
def _reset_buffers():
    audit_module._pending.clear()
    yield
    audit_module._pending.clear()


class TestAuditBuffer:

    def test_buffer_pending_adds_entry(self):
        audit_module._buffer_pending({"action": "test"})
        audit_module._buffer_pending({"action": "test2"})
        assert len(audit_module._pending) == 2

    def test_buffer_pending_drops_oldest_beyond_max(self):
        for i in range(audit_module._PENDING_MAX + 5):
            audit_module._buffer_pending({"action": f"a{i}"})
        assert len(audit_module._pending) == audit_module._PENDING_MAX
        assert audit_module._pending[0]["action"] == f"a5"

    def test_pop_pending_clears_and_returns_copy(self):
        audit_module._buffer_pending({"a": 1})
        audit_module._buffer_pending({"b": 2})
        got = audit_module._pop_pending()
        assert len(got) == 2
        assert audit_module._pending == []

    def test_flush_pending_success_clears_buffer(self):
        # Use AsyncMock for async context manager
        fake_conn = MagicMock()
        fake_conn.execute = AsyncMock()
        fake_cm = MagicMock()
        fake_cm.__aenter__ = AsyncMock(return_value=fake_conn)
        fake_cm.__aexit__ = AsyncMock(return_value=False)

        fake_engine = MagicMock()
        fake_engine.begin = MagicMock(return_value=fake_cm)

        audit_module._buffer_pending({"action": "x"})

        with patch("app.core.audit._get_async_engine", return_value=fake_engine):
            asyncio.run(audit_module._flush_pending())

        assert audit_module._pending == []
        fake_conn.execute.assert_called()

    def test_flush_pending_failure_requeues_entries(self):
        fake_engine = MagicMock()
        fake_engine.begin.side_effect = Exception("db down")

        audit_module._buffer_pending({"action": "keep"})

        with patch("app.core.audit._get_async_engine", return_value=fake_engine):
            with pytest.raises(Exception):
                asyncio.run(audit_module._flush_pending())

        assert len(audit_module._pending) == 1

    def test_flush_pending_no_op_when_empty(self):
        fake_engine = MagicMock()
        fake_engine.begin = MagicMock(side_effect=AssertionError("should not be called"))

        with patch("app.core.audit._get_async_engine", return_value=fake_engine):
            asyncio.run(audit_module._flush_pending())


class TestLogAuditFailureBranch:

    def test_log_audit_db_failure_buffers_entry(self):
        audit_module._pending.clear()

        def _boom(coro):
            raise RuntimeError("redis down")

        with patch("app.tasks.async_runner.run_async", side_effect=_boom), \
             patch("app.core.metrics.record_audit_log_drop") as m_drop:
            audit_module.log_audit("test_action", username="u1", detail={"k": "v"})

        assert len(audit_module._pending) == 1
        m_drop.assert_called_once()

    def test_log_audit_previous_flush_failure_does_not_block(self):
        audit_module._pending.clear()

        call_n = {"n": 0}

        def _boom_sometimes(coro):
            call_n["n"] += 1
            raise RuntimeError(f"boom #{call_n['n']}")

        with patch("app.tasks.async_runner.run_async", side_effect=_boom_sometimes):
            audit_module.log_audit("action", username="u1")

        assert len(audit_module._pending) >= 1


class TestFmtSnapshot:

    def test_fmt_snapshot_none(self):
        assert audit_module._fmt_snapshot(None) is None

    def test_fmt_snapshot_string(self):
        assert audit_module._fmt_snapshot("hi") == "hi"

    def test_fmt_snapshot_dict_serializes(self):
        result = audit_module._fmt_snapshot({"a": 1, "b": "CN"})
        assert "a" in result and "CN" in result

    def test_fmt_snapshot_truncates_long_string(self):
        long_val = "x" * 5000
        result = audit_module._fmt_snapshot({"big": long_val})
        assert len(result) <= 2500


class TestFmtDetail:

    def test_fmt_detail_none_empty(self):
        assert audit_module._fmt_detail(None) == ""

    def test_fmt_detail_string(self):
        assert audit_module._fmt_detail("hello") == "hello"

    def test_fmt_detail_long_string_truncates(self):
        assert len(audit_module._fmt_detail("x" * 2000)) <= 1000

    def test_fmt_detail_dict_json(self):
        out = audit_module._fmt_detail({"key": "value"})
        assert "key" in out and "value" in out

    def test_fmt_detail_unserializable_falls_back(self):
        result = audit_module._fmt_detail(object())
        assert isinstance(result, str)

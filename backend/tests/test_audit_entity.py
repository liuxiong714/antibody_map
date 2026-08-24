"""4.2：审计日志实体列写入测试（纯单测，mock 会话，无需真实 DB/Redis）。"""
import asyncio
import json

import pytest

from app.core import audit as audit_module
from app.models.audit_log import AuditLog


class _FakeSession:
    def __init__(self):
        self.log = None

    def add(self, obj):
        self.log = obj

    async def commit(self):
        return None


class _FakeCM:
    def __init__(self):
        self.session = _FakeSession()

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _run(coro):
    return asyncio.run(coro)


def test_log_audit_persists_entity_columns(monkeypatch):
    """log_audit 应把 entity_type/entity_id/old_value/new_value 落库到 AuditLog。"""
    cm = _FakeCM()
    monkeypatch.setattr(audit_module, "async_session", lambda: cm)

    async def _do():
        # 空会话传入仅作兼容占位
        await audit_module.log_audit(
            None,
            "data_point_update",
            user_id="u1",
            username="zhangsan",
            target="literature/lit1",
            entity_type="data_point",
            entity_id="dp1",
            old_value={"value": 1.0},
            new_value={"value": 2.5},
            detail={"review_status": "approved"},
        )

    _run(_do())

    log = cm.session.log
    assert isinstance(log, AuditLog)
    assert log.action == "data_point_update"
    assert log.entity_type == "data_point"
    assert log.entity_id == "dp1"
    assert json.loads(log.old_value) == {"value": 1.0}
    assert json.loads(log.new_value) == {"value": 2.5}
    assert json.loads(log.detail) == {"review_status": "approved"}


def test_log_audit_without_entity_columns(monkeypatch):
    """仅登录类操作不传 entity 字段时，实体列为空不报错（向后兼容）。"""
    cm = _FakeCM()
    monkeypatch.setattr(audit_module, "async_session", lambda: cm)

    async def _do():
        await audit_module.log_audit(None, "login", user_id="u1", username="zhangsan")

    _run(_do())

    log = cm.session.log
    assert log.entity_type is None
    assert log.entity_id is None
    assert log.old_value is None
    assert log.new_value is None
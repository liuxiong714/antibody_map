"""审计日志模块单测（同步结构化输出，纯单测无需 DB/Redis）。

log_audit 为同步函数，直接向 uvicorn.audit logger 输出 [AUDIT] 结构化行。
"""
import json
import logging

import pytest

from app.core import audit as audit_module


@pytest.fixture(autouse=True)
def _audit_caplog(caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.audit"):
        yield caplog


def test_log_audit_outputs_structured_line(_audit_caplog):
    audit_module.log_audit(
        "data_point_update",
        target="literature/lit1",
        user_id="u1",
        username="zhangsan",
        detail={"review_status": "approved"},
    )

    assert len(_audit_caplog.records) == 1
    msg = _audit_caplog.records[0].message
    assert msg.startswith("[AUDIT] ")
    assert "action=data_point_update" in msg
    assert "target=literature/lit1" in msg
    assert "user_id=u1" in msg
    assert "username=zhangsan" in msg
    assert "result=success" in msg
    assert json.loads(msg.split("detail=", 1)[1].split(" ip=", 1)[0]) == {
        "review_status": "approved"
    }


def test_log_audit_fail_uses_warning_level(_audit_caplog):
    audit_module.log_audit("login_failed", username="u1", result="fail")

    assert len(_audit_caplog.records) == 1
    assert _audit_caplog.records[0].levelno == logging.WARNING
    assert "result=fail" in _audit_caplog.records[0].message


def test_log_audit_minimal_call(_audit_caplog):
    audit_module.log_audit("login")

    assert len(_audit_caplog.records) == 1
    msg = _audit_caplog.records[0].message
    assert "action=login" in msg
    assert "user_id=" in msg
    assert "detail=" in msg

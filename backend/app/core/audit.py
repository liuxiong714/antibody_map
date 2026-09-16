"""轻量审计日志模块。

不建 DB 表，直接往 uvicorn audit logger 输出结构化行，格式：
  [AUDIT] action=backup target=db user_id=xxx result=success detail=...

生产环境可通过 loguru/uvicorn access log 统一收集；未来想落库时只需把
log_audit 内部改成写 AuditLog 表，调用方无需改。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

_logger = logging.getLogger("uvicorn.audit")


def _fmt_detail(detail: object) -> str:
    """把 detail (dict/list/str) 压缩成单行。"""
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail[:300].replace("\n", " ")
    try:
        import json
        return json.dumps(detail, ensure_ascii=False, default=str)[:300]
    except Exception:
        return str(detail)[:300]


def log_audit(
    action: str,
    target: str = "",
    user_id: str | None = None,
    username: str | None = None,
    result: str = "success",
    detail: object = None,
    ip: str | None = None,
) -> None:
    """记录一次管理员操作。

    Args:
        action:     动作标识，如 "backup", "restore", "delete_literature"
        target:     操作目标，如 "db", "literature:abc123", "model_config:f022..."
        user_id:    操作者用户 ID（require_admin 解出来的）
        username:   操作者用户名（可选）
        result:     "success" | "fail"
        detail:     附加信息（dict/str，会被 json 压缩到 300 字符）
        ip:         客户端 IP（可选，从 request.state.client_ip 读）
    """
    ts = datetime.now(timezone.utc).isoformat()
    fields = [
        f"action={action}",
        f"target={target}",
        f"user_id={user_id or ''}",
        f"username={username or ''}",
        f"result={result}",
        f"detail={_fmt_detail(detail)}",
        f"ip={ip or ''}",
        f"ts={ts}",
    ]
    msg = " ".join(fields)
    if result == "fail":
        _logger.warning(f"[AUDIT] {msg}")
    else:
        _logger.info(f"[AUDIT] {msg}")

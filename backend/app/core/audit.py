"""审计日志模块（v2 — DB 落库 + stdout 双通道）。

log_audit 会同时：
  1. 写入 audit_log 表（async engine + asyncpg，worker 与 web 进程通用）
  2. 向 uvicorn.audit logger 输出一行结构化 stdout（留作运维旁路 / 排障兜底）

C4：DB 落库失败不再仅 warning——升级为 error + 指标计数 + **有界内存缓冲**，
后续 log_audit 调用先补写欠账（顺带重试），瞬时故障自愈，审计断档可观测。
调用方业务始终不受影响。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger("uvicorn.audit")

# ---------------------------------------------------------------------------
# 独立 async engine（asyncpg）—— 与 base.py 的 engine 完全解耦，
# 避免 cross-loop 冲突；lazy load，进程首次调用时才创建。
# ---------------------------------------------------------------------------
_async_engine = None
_async_engine_lock = threading.Lock()

# C4：落库失败暂存的内存缓冲（有界，超出丢最旧），供下次调用补写重试
_PENDING_MAX = 500
_pending_lock = threading.Lock()
_pending: list[dict] = []


def _get_async_engine():
    global _async_engine
    if _async_engine is not None:
        return _async_engine
    with _async_engine_lock:
        if _async_engine is not None:
            return _async_engine
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.config import settings
        url = settings.DATABASE_URL  # 已是 postgresql+asyncpg://
        _async_engine = create_async_engine(
            url,
            pool_size=2,
            max_overflow=2,
            pool_pre_ping=True,
        )
        return _async_engine


def _audit_insert_sql():
    from sqlalchemy import text

    return text(
        """
        INSERT INTO audit_log
            (id, user_id, username, action, target, detail, client_ip,
             entity_type, entity_id, old_value, new_value, created_at)
        VALUES (gen_random_uuid(), :user_id, :username, :action, :target, :detail, :ip,
                :entity_type, :entity_id, :old_value, :new_value, NOW())
        """
    )


def _buffer_pending(entry: dict) -> None:
    """将一条审计条目放入内存缓冲（有界，超出丢弃最旧）。"""
    with _pending_lock:
        _pending.append(entry)
        if len(_pending) > _PENDING_MAX:
            _pending.pop(0)


def _pop_pending() -> list[dict]:
    with _pending_lock:
        entries = list(_pending)
        _pending.clear()
        return entries


async def _flush_pending() -> None:
    """尽力补写历史欠账（缓冲中的审计条目）。失败时重新入队，等待下次重试。"""
    entries = _pop_pending()
    if not entries:
        return
    engine = _get_async_engine()
    sql = _audit_insert_sql()
    try:
        async with engine.begin() as conn:
            for entry in entries:
                await conn.execute(sql, entry)
    except Exception:
        # 补写失败：重新入队（有界，防无限增长）
        for entry in entries:
            _buffer_pending(entry)
        raise


async def _async_write_audit(
    action: str,
    target: str | None,
    user_id: str | None,
    username: str | None,
    detail: str | None,
    ip: str | None,
    entity_type: str | None,
    entity_id: str | None,
    old_value: str | None,
    new_value: str | None,
) -> None:
    engine = _get_async_engine()
    sql = _audit_insert_sql()
    async with engine.begin() as conn:
        await conn.execute(
            sql,
            {
                "user_id": user_id,
                "username": username,
                "action": action,
                "target": target,
                "detail": detail,
                "ip": ip,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "old_value": old_value,
                "new_value": new_value,
            },
        )


def _fmt_detail(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail[:1000].replace("\n", " ")
    try:
        return json.dumps(detail, ensure_ascii=False, default=str)[:2000]
    except Exception:
        return str(detail)[:1000]


def _fmt_snapshot(snapshot: Any) -> str | None:
    if snapshot is None:
        return None
    if isinstance(snapshot, str):
        return snapshot[:2000] or None
    try:
        s = json.dumps(snapshot, ensure_ascii=False, default=str)
        return s[:2000]
    except Exception:
        return str(snapshot)[:1000] or None


def log_audit(
    action: str,
    target: str = "",
    user_id: str | None = None,
    username: str | None = None,
    result: str = "success",
    detail: Any = None,
    ip: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
) -> None:
    """记录一次审计动作（stdout + DB 双通道）。

    Args:
        action      动作标识，如 "login" / "extraction_completed" / "report_generated"
        target      操作目标描述
        user_id     操作者用户 ID
        username    操作者用户名
        result      "success" | "fail"
        detail      附加信息（dict/str），会被压缩到 2000 字符 JSON
        ip          客户端 IP
        entity_type 实体类型（如 "data_point" / "literature"）
        entity_id   实体 ID
        old_value   变更前快照（dict/JSON-string）
        new_value   变更后快照
    """
    # --- stdout（保留原行为，运维排障兜底）---
    ts_iso = datetime.now(timezone.utc).isoformat()
    fields = [
        f"action={action}",
        f"target={target}",
        f"user_id={user_id or ''}",
        f"username={username or ''}",
        f"result={result}",
        f"detail={_fmt_detail(detail)[:300]}",
        f"ip={ip or ''}",
        f"ts={ts_iso}",
    ]
    msg = " ".join(fields)
    if result == "fail":
        _logger.warning(f"[AUDIT] {msg}")
    else:
        _logger.info(f"[AUDIT] {msg}")

    # --- DB 落库（asyncpg + 独立 engine；失败 → error + 指标 + 缓冲待重试）---
    entry = {
        "user_id": user_id,
        "username": username,
        "action": action,
        "target": target or None,
        "detail": _fmt_detail(detail) or None,
        "ip": ip,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "old_value": _fmt_snapshot(old_value),
        "new_value": _fmt_snapshot(new_value),
    }
    try:
        from app.tasks.async_runner import run_async

        # C4：先补写历史欠账（失败不影响本条）
        try:
            run_async(_flush_pending())
        except Exception as flush_e:
            _logger.warning(f"[AUDIT] 缓冲补写失败（等待下次重试）: {type(flush_e).__name__}: {flush_e}")
        run_async(_async_write_audit(**entry))
    except Exception as e:
        # C4：不再静默——错误级日志 + 指标计数 + 入内存缓冲，下次调用顺带重试补写
        _buffer_pending(entry)
        try:
            from app.core.metrics import record_audit_log_drop

            record_audit_log_drop()
        except Exception:
            pass
        _logger.error(
            f"[AUDIT] DB 落库失败，已缓冲待重试（缓冲 {len(_pending)} 条，超 {_PENDING_MAX} 条丢最旧）: "
            f"{type(e).__name__}: {e}"
        )

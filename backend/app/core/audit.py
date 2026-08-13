"""审计日志工具

提供统一的审计日志记录函数，供关键操作（登录、登出、密码修改、用户管理等）调用。
"""
import json
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_audit(
    db: AsyncSession,
    action: str,
    *,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    target: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    client_ip: Optional[str] = None,
) -> None:
    """记录一条审计日志

    Args:
        db: 数据库会话
        action: 操作类型，如 "login", "login_failed", "logout", "change_password" 等
        user_id: 操作人 ID
        username: 操作人用户名
        target: 操作目标（如被修改的用户名、被删除的模型配置名）
        detail: 操作详情（JSON 可序列化字典）
        client_ip: 客户端 IP 地址
    """
    log = AuditLog(
        user_id=user_id,
        username=username,
        action=action,
        target=target,
        detail=json.dumps(detail, ensure_ascii=False) if detail else None,
        client_ip=client_ip,
    )
    db.add(log)
    # 不提交，由调用方在事务提交时一并写入
"""审计日志工具

提供统一的审计日志记录函数，供关键操作（登录、登出、密码修改、用户管理等）调用。
"""
import json
import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.base import async_session

logger = logging.getLogger("uvicorn")


async def log_audit(
    db: AsyncSession,
    action: str,
    *,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    target: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    client_ip: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    old_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
) -> None:
    """记录一条审计日志

    内部自行提交事务，不依赖调用方 commit。写入失败时降级记录 error 日志，
    不影响主业务流。

    Args:
        db: 数据库会话（仅用于兼容旧调用；实际写入使用独立会话，避免提交主请求事务）
        action: 操作类型，如 "login", "login_failed", "logout", "change_password",
            "data_point_create", "data_point_update", "data_point_review" 等
        user_id: 操作人 ID
        username: 操作人用户名
        target: 操作目标（如被修改的用户名、被删除的模型配置名）
        detail: 操作详情（JSON 可序列化字典）
        client_ip: 客户端 IP 地址
        entity_type: 业务实体类型（如 "data_point"），用于实体变更审计/过滤
        entity_id: 业务实体 ID
        old_value: 变更前快照（仅记录发生变化的字段），JSON 可序列化字典
        new_value: 变更后快照
    """
    try:
        # 使用独立会话自行提交，绝不提交调用方传入的主请求会话，
        # 以免 commit 导致会话中的业务对象过期（expire），进而触发异步 reload 引发 MissingGreenlet。
        async with async_session() as session:
            log = AuditLog(
                user_id=user_id,
                username=username,
                action=action,
                target=target,
                detail=json.dumps(detail, ensure_ascii=False) if detail else None,
                client_ip=client_ip,
                entity_type=entity_type,
                entity_id=entity_id,
                old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None,
                new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None,
            )
            session.add(log)
            await session.commit()
    except Exception as e:
        logger.error(f"审计日志写入失败 (action={action}): {e}")
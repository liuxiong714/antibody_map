"""审计日志模型

记录关键安全操作的审计追踪，包括操作人、操作类型、目标、IP 地址和时间戳。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """审计日志"""
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 操作人 ID（null 表示未登录操作，如登录失败）
    user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    # 操作人用户名
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # 操作类型，如 "login", "login_failed", "logout", "change_password",
    # "create_user", "update_user", "delete_user", "create_model_config" 等
    action: Mapped[str] = mapped_column(String(50), index=True)
    # 操作目标描述
    target: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # 操作详情（JSON 字符串，记录关键参数）
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 实体维度（4.2：数据点等业务对象的变更审计，便于按实体过滤 / 追溯 / 回滚）
    # 实体类型，如 "data_point"
    entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    # 实体 ID（如数据点 ID）
    entity_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    # 变更前快照（JSON 字符串，仅记录发生变化的字段）
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 变更后快照（JSON 字符串）
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 客户端 IP 地址
    client_ip: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 操作时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
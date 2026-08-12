import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApiModelConfig(Base):
    """远程 API 模型配置"""
    __tablename__ = "api_model_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 显示名称，如 "DeepSeek Chat"
    name: Mapped[str] = mapped_column(String(100))
    # 模型名，如 "deepseek-chat"
    model_name: Mapped[str] = mapped_column(String(100))
    # API Key
    api_key: Mapped[str] = mapped_column(String(500))
    # API 地址，如 "https://api.deepseek.com/v1"
    base_url: Mapped[str] = mapped_column(String(500))
    # 备注说明
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 是否启用
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
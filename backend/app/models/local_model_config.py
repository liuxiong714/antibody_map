import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LocalModelConfig(Base):
    """本地大模型配置（Ollama 等）

    用户可在系统设置中管理本地模型列表，实现所有功能模块的模型选择候选项统一。
    """
    __tablename__ = "local_model_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 显示名称，如 "Qwen2.5:14B"
    name: Mapped[str] = mapped_column(String(100))
    # 模型名，如 "qwen2.5:14b"
    model_name: Mapped[str] = mapped_column(String(100), unique=True)
    # 备注说明
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 是否启用
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.hybrid import hybrid_property

from app.core.crypto import decrypt, encrypt
from app.models.base import Base


class ApiModelConfig(Base):
    """远程 API 模型配置

    安全说明：api_key 与 base_url 在数据库中以 Fernet 密文存储，
    通过 hybrid_property 在 Python 层透明加解密。
    业务代码读写 config.api_key / config.base_url 时无感知，均为明文。
    expires_at 用于临时配置（如单次提取注入的自定义凭证）的自动过期回收，
    永久配置为 NULL。
    """
    __tablename__ = "api_model_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 显示名称，如 "DeepSeek Chat"
    name: Mapped[str] = mapped_column(String(100))
    # 模型名，如 "deepseek-chat"
    model_name: Mapped[str] = mapped_column(String(100))
    # API Key 密文（列名保持 api_key 兼容历史数据，存储 Fernet 密文）
    _api_key_enc: Mapped[str] = mapped_column("api_key", String(500))
    # API 地址密文（列名保持 base_url 兼容历史数据，存储 Fernet 密文）
    _base_url_enc: Mapped[str] = mapped_column("base_url", String(500))
    # 临时配置过期时间（永久配置为 NULL；过期后由后台清理任务删除）
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
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

    @hybrid_property
    def api_key(self) -> str:
        """读取时自动解密为明文（供业务调用 LLM 使用）

        类级别访问（如 ApiModelConfig.api_key）返回原始密文列表达式，
        不支持在 SQL 查询中按 api_key 过滤（密文不可比较）。
        """
        if isinstance(self, ApiModelConfig):
            # 实例访问：解密返回明文
            return decrypt(self._api_key_enc)
        # 类级别访问：返回原始列（避免触发 SQL 表达式布尔判断）
        return self._api_key_enc

    @api_key.setter
    def api_key(self, value: str) -> None:
        """写入时自动加密为密文"""
        self._api_key_enc = encrypt(value)

    @hybrid_property
    def base_url(self) -> str:
        """读取时自动解密为明文（供业务调用 LLM 使用）"""
        if isinstance(self, ApiModelConfig):
            return decrypt(self._base_url_enc)
        # 类级别访问：返回原始列
        return self._base_url_enc

    @base_url.setter
    def base_url(self, value: str) -> None:
        """写入时自动加密为密文"""
        self._base_url_enc = encrypt(value)

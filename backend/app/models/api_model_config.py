import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import decrypt, encrypt
from app.models.base import Base

logger = logging.getLogger(__name__)


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
    # 模型名，如 "deepseek-flash"（旧名 deepseek-chat 仍兼容）
    model_name: Mapped[str] = mapped_column(String(100))
    # API Key 密文（列名保持 api_key 兼容历史数据，存储 Fernet 密文）
    _api_key_enc: Mapped[str] = mapped_column("api_key", String(500))
    # API 地址密文（列名保持 base_url 兼容历史数据，存储 Fernet 密文）
    _base_url_enc: Mapped[str] = mapped_column("base_url", String(500))
    # 临时配置过期时间（永久配置为 NULL；过期后由后台清理任务删除）
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
    # 备注说明
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        """读取时自动解密为明文。

        S-4：解密失败（SECRET_KEY 变更/密文损坏）不再返回密文原值，
        记 error 日志后返回空字符串——让下游调用方走"缺 key"路径
        （否则密文会被当作 API Key 外发造成安全事故）。
        """
        if isinstance(self, ApiModelConfig):
            try:
                return decrypt(self._api_key_enc)
            except ValueError:
                logger.error(
                    f"API Key 解密失败（config id={self.id}, name={self.name}), "
                    f"SECRET_KEY 可能已变更，请重新录入模型配置"
                )
                return ""
        return self._api_key_enc

    @api_key.setter
    def api_key(self, value: str) -> None:
        """写入时自动加密为密文"""
        self._api_key_enc = encrypt(value)

    @hybrid_property
    def base_url(self) -> str:
        """读取时自动解密为明文（供业务调用 LLM 使用）。S-4：解密失败返回空串。"""
        if isinstance(self, ApiModelConfig):
            try:
                return decrypt(self._base_url_enc)
            except ValueError:
                logger.error(
                    f"base_url 解密失败（config id={self.id}, name={self.name}), "
                    f"SECRET_KEY 可能已变更"
                )
                return ""
        return self._base_url_enc

    @base_url.setter
    def base_url(self, value: str) -> None:
        """写入时自动加密为密文"""
        self._base_url_enc = encrypt(value)

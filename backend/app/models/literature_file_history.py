"""文献文件导入/删除历史模型

记录每个文献文件（以 pdf_hash 为指纹）的导入与软删除历史，
用于重复导入时提示用户该文件首次导入时间、删除时间与操作人，
避免同一文件被反复导入而不自知。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LiteratureFileHistory(Base):
    """文献文件导入/删除历史记录"""
    __tablename__ = "literature_file_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 文件指纹（sha256），用于跨软删除/永久删除追踪同一文件
    pdf_hash: Mapped[str] = mapped_column(String(64), index=True)
    # 原始文件名
    file_name: Mapped[Optional[str]] = mapped_column(String(500))
    # 关联的文献记录（若仍存在）
    literature_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID, nullable=True)
    # 动作：imported=导入，deleted=移入回收站（软删除）
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 操作人
    operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID, nullable=True)
    operator_name: Mapped[Optional[str]] = mapped_column(String(100))
    # 操作时间
    operated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('imported','deleted')",
            name="lit_file_history_action_check",
        ),
    )
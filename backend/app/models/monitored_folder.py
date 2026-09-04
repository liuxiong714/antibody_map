"""文件夹监控相关数据模型。

MonitoredFolder: 用户配置的监控文件夹
MonitoredFile:   每个被扫描过的文件的处理记录
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class MonitoredFolder(Base):
    __tablename__ = "monitored_folder"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    folder_path: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    scan_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    file_extensions: Mapped[str | None] = mapped_column(Text)  # 逗号分隔，如 .pdf,.caj
    auto_extract: Mapped[bool] = mapped_column(Boolean, default=True)
    extraction_model: Mapped[str | None] = mapped_column(String(100))
    extraction_api_key: Mapped[str | None] = mapped_column(String(200))
    extraction_base_url: Mapped[str | None] = mapped_column(String(300))
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scan_new_count: Mapped[int] = mapped_column(Integer, default=0)
    total_imported_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="idle")  # idle / scanning / error
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    files: Mapped[list["MonitoredFile"]] = relationship(
        back_populates="folder", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('idle','scanning','error')",
            name="mf_status_check",
        ),
    )


class MonitoredFile(Base):
    __tablename__ = "monitored_file"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitored_folder.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str] = mapped_column(String(500))
    file_name: Mapped[str] = mapped_column(String(300))
    file_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    file_size: Mapped[int | None] = mapped_column(Integer)
    file_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending / imported / skipped_duplicate / failed
    literature_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    folder: Mapped["MonitoredFolder"] = relationship(back_populates="files")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','imported','skipped_duplicate','failed')",
            name="mf_file_status_check",
        ),
    )

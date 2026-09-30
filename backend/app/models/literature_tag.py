import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

# 多对多关联表：文献 ↔ 标签
literature_tag = Table(
    "literature_tag",
    Base.metadata,
    Column("literature_id", ForeignKey("literature.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    color: Mapped[str | None] = mapped_column(String(7), default="#1677ff")  # HEX color
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # 可选的反向关系（用于查询某个标签下的所有文献）
    literatures = relationship("Literature", secondary=literature_tag, back_populates="tags", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("name", name="uq_tag_name"),
    )
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KgQaLog(Base):
    """知识图谱问答日志：记录每次问答与用户反馈（点赞/点踩）。

    供问答质量分析与后续优化使用；反馈列由用户显式提交（up/down）。
    """
    __tablename__ = "kg_qa_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str | None] = mapped_column(String(32), default=None)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    feedback: Mapped[str | None] = mapped_column(String(16), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_kg_qa_log_created", "created_at"),
        Index("ix_kg_qa_log_feedback", "feedback"),
    )

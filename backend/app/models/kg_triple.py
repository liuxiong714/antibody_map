import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KGTriple(Base):
    """知识图谱关系表：存储 LLM 抽取的持久化三元组。

    subject_id / object_id 引用 kg_entity.id。
    联合唯一索引防止同一文献内重复三元组。
    """
    __tablename__ = "kg_triple"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("kg_entity.id", ondelete="CASCADE"), nullable=False,
    )
    predicate: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("kg_entity.id", ondelete="CASCADE"), nullable=False,
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_context: Mapped[str | None] = mapped_column(Text)
    literature_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("literature.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("subject_id", "predicate", "object_id", "literature_id", name="uq_kg_triple"),
    )

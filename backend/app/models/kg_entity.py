import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import JSON, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KGEntity(Base):
    """知识图谱实体表：存储 LLM 抽取的持久化节点。

    与计算式推导（knowledge_graph_service.py 从数据点实时生成）互补，
    本表存储从文献全文中抽取的实体（含 institution/author/vaccine 等数据点无法覆盖的维度）。
    计算式图谱不入库，仅 API 响应时动态生成。
    """
    __tablename__ = "kg_entity"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    source_literature_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("literature.id", ondelete="SET NULL"),
        index=True,
    )
    merged_into: Mapped[Optional[str]] = mapped_column(
        String(16), ForeignKey("kg_entity.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_kg_entity_type_name", "entity_type", "name"),
        Index("ix_kg_entity_merged", "merged_into"),
    )

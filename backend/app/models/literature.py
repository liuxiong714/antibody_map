import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, Integer, String, Text, ARRAY, DateTime, CheckConstraint, Numeric
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.literature_tag import literature_tag


class Literature(Base):
    __tablename__ = "literature"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500))
    title_en: Mapped[Optional[str]] = mapped_column(String(500))
    authors: Mapped[Optional[str]] = mapped_column(Text)
    journal: Mapped[Optional[str]] = mapped_column(String(300))
    pub_year: Mapped[Optional[int]]
    doi: Mapped[Optional[str]] = mapped_column(String(200))
    pmid: Mapped[Optional[str]] = mapped_column(String(20))
    abstract: Mapped[Optional[str]] = mapped_column(Text)
    keywords: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    region: Mapped[Optional[str]] = mapped_column(String(100))
    province: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    publication_types: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    source_db: Mapped[Optional[str]] = mapped_column(String(50))
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    pdf_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    has_fulltext: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    extracted_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    # LLM 提取的 token 用量与费用统计（AI 提取完成时写入）
    llm_model_used: Mapped[Optional[str]] = mapped_column(String(100))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_usd: Mapped[Any] = mapped_column(Numeric(10, 6), default=0)
    llm_call_count: Mapped[int] = mapped_column(Integer, default=0)
    llm_usage_detail: Mapped[Optional[dict]] = mapped_column(JSON)
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=literature_tag, back_populates="literatures", lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # 软删除：deleted_at 非空时表示已移入回收站
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True, default=None
    )
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID,  # 仅记录删除者，不设外键约束
        nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "extraction_status IN ('pending','queued','processing','done','done_no_data','failed')",
            name="lit_extraction_status_check",
        ),
    )

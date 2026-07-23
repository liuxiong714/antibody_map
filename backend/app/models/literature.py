import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Integer, String, Text, ARRAY, DateTime, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


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
    province: Mapped[Optional[str]] = mapped_column(String(100))
    publication_types: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    source_db: Mapped[Optional[str]] = mapped_column(String(50))
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    has_fulltext: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending")
    extracted_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        CheckConstraint(
            "extraction_status IN ('pending','processing','done','failed')",
            name="lit_extraction_status_check",
        ),
    )

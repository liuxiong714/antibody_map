import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Numeric, DateTime, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DataPoint(Base):
    __tablename__ = "data_point"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    literature_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("literature.id", ondelete="CASCADE")
    )
    disease: Mapped[Optional[str]] = mapped_column(String(100))
    region: Mapped[Optional[str]] = mapped_column(String(100))
    province: Mapped[Optional[str]] = mapped_column(String(100))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    latitude: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    age_group: Mapped[Optional[str]] = mapped_column(String(50))
    age_min: Mapped[Optional[int]]
    age_max: Mapped[Optional[int]]
    sample_size: Mapped[Optional[int]]
    data_type: Mapped[Optional[str]] = mapped_column(String(20))
    value: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    unit: Mapped[Optional[str]] = mapped_column(String(50))
    ci_lower: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    ci_upper: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    method: Mapped[Optional[str]] = mapped_column(String(200))
    assay: Mapped[Optional[str]] = mapped_column(String(200))
    population: Mapped[Optional[str]] = mapped_column(String(200))
    collection_year: Mapped[Optional[int]]
    confidence: Mapped[str] = mapped_column(String(10), default="medium")
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        CheckConstraint(
            "data_type IN ('seroprevalence','gmc')",
            name="dp_data_type_check",
        ),
        CheckConstraint(
            "confidence IN ('high','medium','low')",
            name="dp_confidence_check",
        ),
        CheckConstraint(
            "review_status IN ('pending','approved','rejected')",
            name="dp_review_status_check",
        ),
    )

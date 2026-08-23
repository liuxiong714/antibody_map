import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Report(Base):
    __tablename__ = "report"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    report_type: Mapped[str] = mapped_column(String(30), default="antibody_analysis")
    disease: Mapped[Optional[str]] = mapped_column(String(50))
    province: Mapped[Optional[str]] = mapped_column(String(100))
    data_type: Mapped[Optional[str]] = mapped_column(String(50))
    language: Mapped[str] = mapped_column(String(10), default="zh")
    literature_count: Mapped[int] = mapped_column(Integer, default=0)
    data_point_count: Mapped[int] = mapped_column(Integer, default=0)
    # 疫苗接种策略报告专用字段
    task_type: Mapped[Optional[str]] = mapped_column(String(100))
    task_time: Mapped[Optional[str]] = mapped_column(String(200))
    task_location: Mapped[Optional[str]] = mapped_column(String(200))
    personnel_count: Mapped[Optional[int]] = mapped_column(Integer)
    personnel_gender: Mapped[Optional[str]] = mapped_column(String(100))
    personnel_age: Mapped[Optional[str]] = mapped_column(String(100))
    personnel_vaccination_history: Mapped[Optional[str]] = mapped_column(Text)
    # 生成报告使用的 LLM 模型
    llm_model: Mapped[Optional[str]] = mapped_column(String(100))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        CheckConstraint(
            "report_type IN ('antibody_analysis','vaccination_strategy','immune_barrier_assessment')",
            name="report_type_check",
        ),
    )

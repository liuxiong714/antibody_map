import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Report(Base):
    __tablename__ = "report"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    report_type: Mapped[str] = mapped_column(String(30), default="antibody_analysis")
    disease: Mapped[str | None] = mapped_column(String(50))
    province: Mapped[str | None] = mapped_column(String(100))
    data_type: Mapped[str | None] = mapped_column(String(50))
    language: Mapped[str] = mapped_column(String(10), default="zh")
    literature_count: Mapped[int] = mapped_column(Integer, default=0)
    data_point_count: Mapped[int] = mapped_column(Integer, default=0)
    # 疫苗接种策略报告专用字段
    task_type: Mapped[str | None] = mapped_column(String(100))
    task_time: Mapped[str | None] = mapped_column(String(200))
    task_location: Mapped[str | None] = mapped_column(String(200))
    personnel_count: Mapped[int | None] = mapped_column(Integer)
    personnel_gender: Mapped[str | None] = mapped_column(String(100))
    personnel_age: Mapped[str | None] = mapped_column(String(100))
    personnel_vaccination_history: Mapped[str | None] = mapped_column(Text)
    # 生成报告使用的 LLM 模型
    llm_model: Mapped[str | None] = mapped_column(String(100))
    # 生成报告所依据的数据快照指纹：对底层审核通过数据点做稳定 hash，
    # 用于校验历史报告的可复现性（底层数据变更后同一报告内容不再被误判为一致）
    data_snapshot_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        CheckConstraint(
            "report_type IN ('antibody_analysis','vaccination_strategy','immune_barrier_assessment')",
            name="report_type_check",
        ),
    )

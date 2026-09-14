"""合成/真实文献多模型提取结果。

AI 提取准确度自测中，多模型对比时每个「模型 × 文献」的提取结果独立存储在这里，
不写入 literature.data_point，避免污染真实文献数据、避免多模型互相覆盖。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyntheticExtraction(Base):
    __tablename__ = "synthetic_extraction"
    __table_args__ = (
        UniqueConstraint("task_id", "literature_id", "model", name="uq_syn_extr_task_lit_model"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), index=True, nullable=False
    )
    literature_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    # 提取模型（如 ollama:qwen3:8b）
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # 提取状态: pending / running / done / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # 该模型该篇提取出的数据点数组（结构同 assess_task 的 ex 点）
    points_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
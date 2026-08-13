import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, CheckConstraint, Numeric
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExtractionHistory(Base):
    """AI 提取历史记录——每次提取操作写入一条记录"""

    __tablename__ = "extraction_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    literature_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("literature.id", ondelete="CASCADE"), index=True, nullable=False
    )
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # 本次提取使用的模型
    model: Mapped[Optional[str]] = mapped_column(String(100))
    # 状态: success=提取到数据点, no_data=成功但无数据, failed=提取失败
    status: Mapped[str] = mapped_column(String(20), default="failed", index=True)
    data_point_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    # Token 用量
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_usd: Mapped[Any] = mapped_column(Numeric(10, 6), default=0)
    llm_call_count: Mapped[int] = mapped_column(Integer, default=0)
    # 详细的模型用量信息（JSON）
    llm_usage_detail: Mapped[Optional[dict]] = mapped_column(JSON)

    __table_args__ = (
        CheckConstraint(
            "status IN ('success','no_data','failed')",
            name="extraction_history_status_check",
        ),
    )
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GoalThresholdConfig(Base):
    """每病保护目标阈值配置表（阳性率 %）。

    迁移时以 app.core.goal_thresholds.GOAL_THRESHOLDS 默认值种子化，
    之后可由管理员通过系统设置 API 覆盖/重置。
    """

    __tablename__ = "goal_threshold_config"

    disease: Mapped[str] = mapped_column(String(64), primary_key=True)
    threshold_percent: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

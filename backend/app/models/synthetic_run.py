"""自测任务的一次「单模型批量运行」记录。

多模型批量评测时，每个模型跑一遍全部文献即产生一条 synthetic_run：
以 run_index（任务内递增）与起止时间区分同一模型的多次运行，
从而保留全部历史运行结果，不互相覆盖。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyntheticRun(Base):
    __tablename__ = "synthetic_run"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), index=True, nullable=False
    )
    # 本次运行使用的提取模型（如 ollama:qwen3:8b）
    model: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # 任务内递增序号（与起止时间共同区分同一模型的多次运行）
    run_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 运行状态: pending / running / done / partial / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    literatures_total: Mapped[int] = mapped_column(Integer, default=0)
    literatures_done: Mapped[int] = mapped_column(Integer, default=0)
    literatures_failed: Mapped[int] = mapped_column(Integer, default=0)
    # 提取过程中的峰值显存（MB，来自 Ollama /api/ps 采样；不可达时为 NULL）
    peak_vram_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 本次运行的效率指标汇总（成功率/单篇耗时/首token延迟/生成速度/数据点等）
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
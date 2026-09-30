"""合成/真实文献多模型提取结果。

AI 提取准确度自测中，多模型对比时每个「模型 × 文献」的提取结果独立存储在这里，
不写入 literature.data_point，避免污染真实文献数据、避免多模型互相覆盖。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyntheticExtraction(Base):
    __tablename__ = "synthetic_extraction"
    __table_args__ = (
        # 按「运行 × 文献」唯一：同一模型多次运行（不同 run_id）各自保留结果，互不覆盖。
        # 历史行的 run_id 为 NULL，Postgres 中 NULL 互不冲突，兼容旧数据。
        UniqueConstraint("run_id", "literature_id", name="uq_syn_extr_run_lit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), index=True, nullable=False
    )
    literature_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    # 所属运行（synthetic_run.id）。旧数据为 NULL
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), index=True, nullable=True
    )
    # 提取模型（如 ollama:qwen3:8b）
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # 提取状态: pending / running / done / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # 该模型该篇提取出的数据点数组（结构同 assess_task 的 ex 点）
    points_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # ===== 效率指标（单篇 × 单模型） =====
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 单篇墙钟耗时（ms），含分块/重试
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 首 token 延迟（ms，取本次全部 LLM 调用的均值）
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 生成 token 总数与 decode 速度（tokens/s）
    gen_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_per_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 输出 JSON 是否可解析（None=未判定，如连接类失败）
    json_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 数据点: 总数 / 原文可溯源数（幻觉率代理：1 - 溯源率）
    points_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grounded_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
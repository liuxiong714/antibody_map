import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DataPoint(Base):
    __tablename__ = "data_point"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    literature_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("literature.id", ondelete="CASCADE"),
        index=True,
    )
    disease: Mapped[str | None] = mapped_column(String(100), index=True)
    region: Mapped[str | None] = mapped_column(String(100))
    province: Mapped[str | None] = mapped_column(String(100), index=True)
    city: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    age_group: Mapped[str | None] = mapped_column(String(50))
    age_min: Mapped[int | None]
    age_max: Mapped[int | None]
    sample_size: Mapped[int | None]
    data_type: Mapped[str | None] = mapped_column(String(20), index=True)
    value: Mapped[float | None] = mapped_column(Numeric(10, 4))
    unit: Mapped[str | None] = mapped_column(String(50))
    ci_lower: Mapped[float | None] = mapped_column(Numeric(10, 4))
    ci_upper: Mapped[float | None] = mapped_column(Numeric(10, 4))
    method: Mapped[str | None] = mapped_column(String(200))
    assay: Mapped[str | None] = mapped_column(String(200))
    population: Mapped[str | None] = mapped_column(String(200))
    collection_year: Mapped[int | None] = mapped_column(index=True)
    # 数据来源追踪（引用溯源）
    source_page: Mapped[int | None]  # 来源页码
    source_context: Mapped[str | None] = mapped_column(Text)  # 原文片段
    # 精确字符级溯源（P0 新增）
    source_char_start: Mapped[int | None] = mapped_column(Integer)  # 在全文中的起始字符位置（0-based，含）
    source_char_end: Mapped[int | None] = mapped_column(Integer)    # 在全文中的结束字符位置（0-based，不含）
    is_grounded: Mapped[bool] = mapped_column(Boolean, default=False)   # 是否在原文中成功找到对应片段
    # P1-1：主估计/子估计层级（参考 SeroTracker）
    # estimate_type: primary=主估计（如全省汇总），subgroup=子估计（如按年龄/地区/免疫史分组）
    # parent_id: 子估计指向其主估计的 id；主估计该字段为 None
    estimate_type: Mapped[str] = mapped_column(String(20), default="primary", index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("data_point.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[str] = mapped_column(String(10), default="medium")
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # 审核意见（可空）
    review_comment: Mapped[str | None] = mapped_column(Text)
    # 审核人（可空，外键到 user.id；用户被删除时置空而非级联删除数据点）
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 审核时间（可空）
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # 质量分级（0-100 分 + A/B/C 三级 + 调查级别），由提取期即时写入、审核通过后异步重算
    quality_score: Mapped[int | None] = mapped_column(Integer, index=True)
    quality_grade: Mapped[str | None] = mapped_column(String(1), index=True)
    estimate_grade: Mapped[str | None] = mapped_column(String(20))
    # F17：LLM 原始输出快照（JSON），用于展示 "LLM 原始 vs 人工修改" 的 diff
    llm_raw_snapshot: Mapped[dict | None] = mapped_column(JSON)
    # F19：截断标记（"<"=低于检出限 / ">"=高于检出限；无则 None），避免把截断值当精确值参与统计
    truncation: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        # 复合索引：地图/分析最常用的组合过滤条件 (review_status, disease, data_type)
        Index(
            "ix_dp_review_disease_type",
            "review_status",
            "disease",
            "data_type",
        ),
        # 复合索引：按文献提取/删除数据点时加速
        Index(
            "ix_dp_lit_review",
            "literature_id",
            "review_status",
        ),
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
        CheckConstraint(
            "estimate_type IN ('primary','subgroup')",
            name="dp_estimate_type_check",
        ),
    )

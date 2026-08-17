import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import ForeignKey, Integer, String, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TiterTable(Base):
    """滴度矩阵表——存储文献中的 HI/VNT/ELISA 滴度矩阵数据"""

    __tablename__ = "titer_table"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    literature_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("literature.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # 检测类型：hi=血凝抑制, vnt=病毒中和, elisa=酶联免疫吸附
    assay_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 参考抗血清名称列表（JSON 数组）
    ref_antisera: Mapped[Optional[list[Any]]] = mapped_column(JSON, comment="抗血清名称列表")
    # 抗原名称列表（JSON 数组）
    antigens: Mapped[Optional[list[Any]]] = mapped_column(JSON, comment="抗原名称列表")
    # 滴度矩阵：二维数组，行为抗原、列为抗血清（JSON）
    titers: Mapped[Optional[list[Any]]] = mapped_column(JSON, comment="滴度矩阵（行=抗原，列=抗血清）")
    # 滴度单位（如 1:10, 1:100, IU/ml）
    unit: Mapped[Optional[str]] = mapped_column(String(50))
    # 质量评分（0-100），由 LLM 提取置信度或人工审核后赋值
    quality_score: Mapped[Optional[int]] = mapped_column(Integer)
    # 来源页码
    source_page: Mapped[Optional[int]]
    # 原文片段
    source_context: Mapped[Optional[str]] = mapped_column(String(500))
    # LLM 提取置信度
    confidence: Mapped[str] = mapped_column(String(10), default="medium")
    # 人工审核状态：pending / approved / rejected
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint(
            "assay_type IN ('hi', 'vnt', 'elisa')",
            name="titer_table_assay_type_check",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name="titer_table_review_status_check",
        ),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name="titer_table_quality_score_check",
        ),
    )
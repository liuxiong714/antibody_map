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
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.term_normalizer import normalize_province
from app.models.base import Base


class DataPoint(Base):
    __tablename__ = "data_point"

    # ---- 字段级归一化（覆盖所有 ORM 入库入口，兜住 import/synthetic 等漏处理的路径）----
    @validates("province")
    def _normalize_province(self, key: str, value: str | None) -> str | None:
        return normalize_province(value) if value else value

    @validates("disease")
    def _normalize_disease(self, key: str, value: str | None) -> str | None:
        from app.core.term_normalizer import normalize_disease
        return normalize_disease(value) if value else value

    @validates("method")
    def _normalize_method(self, key: str, value: str | None) -> str | None:
        from app.core.term_normalizer import normalize_method
        return normalize_method(value) if value else value

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
    value: Mapped[float | None] = mapped_column(Numeric(14, 4))
    unit: Mapped[str | None] = mapped_column(String(50))
    ci_lower: Mapped[float | None] = mapped_column(Numeric(14, 4))
    ci_upper: Mapped[float | None] = mapped_column(Numeric(14, 4))
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

    # F21：提取批次溯源（2026-09-20 新增）
    # model_used：该数据点由哪个模型提取，例 "qwen3.8:27b"（冗余直存，展示零 JOIN 开销）
    model_used: Mapped[str | None] = mapped_column(String(100), index=True)
    # extraction_history_id：外键到 extraction_history.id，用于追溯完整批次
    # 允许 NULL（import/synthetic/手动录入路径无 ExtractionHistory）
    extraction_history_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_history.id", ondelete="SET NULL"),
        index=True,
    )

    # —— Phase 0: 多域数据扩展字段 ——
    # data_domain: 数据域顶层分类，默认 immunology 保证旧数据零迁移
    data_domain: Mapped[str] = mapped_column(
        String(20), default="immunology", index=True,
        comment="数据域：immunology(免疫)/epidemiology(流行)/pathogen(病原)",
    )
    # indicator: 具体指标名（data_type 的别名 + 扩展，支持更丰富的指标）
    indicator: Mapped[str | None] = mapped_column(String(50), index=True)
    # numerator/denominator: 分子分母（epi/pathogen 常用）
    numerator: Mapped[float | None] = mapped_column(Numeric(14, 4))
    denominator: Mapped[float | None] = mapped_column(Numeric(14, 4))
    # period_type/period_month: 时间粒度（epi 周/月/季数据）
    period_type: Mapped[str] = mapped_column(
        String(20), default="year",
        comment="时间粒度：year/quarter/month/week",
    )
    period_month: Mapped[int | None]  # 1-12
    # —— 病原学字段（与 disease 解耦，支持 pathogen_monitoring 合并查询）——
    pathogen: Mapped[str | None] = mapped_column(String(200), index=True)       # 病原体名
    serotype: Mapped[str | None] = mapped_column(String(50))                    # 血清型
    genotype: Mapped[str | None] = mapped_column(String(50), index=True)       # 基因型
    lineage: Mapped[str | None] = mapped_column(String(50))                    # 谱系/变异株/clade
    typing_method: Mapped[str | None] = mapped_column(String(100))             # 分型方法
    specimen_type: Mapped[str | None] = mapped_column(String(100))             # 标本类型
    # extra: 非常规维度兜底，避免字段爆炸
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # —— Phase 0 结束 ——

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
        # 流行病学/病原学监测指标(阶段1):
        #   incidence=发病率 / case_count=发病人数 / mortality=死亡率/病死率 / death_count=死亡数
        # Phase 0 扩展: proportion(构成比)/resistance_rate(耐药率)/positive_rate(检出阳性率)
        #              /attack_rate(罹患率)/secondary_attack_rate(续发率)
        # 均为"加法",不触碰既有 seroprevalence/gmc 数据与逻辑
        CheckConstraint(
            "data_type IN ('seroprevalence','gmc','incidence','case_count','mortality','death_count',"
            "'proportion','resistance_rate','positive_rate','attack_rate','secondary_attack_rate')",
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

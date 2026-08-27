import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean, Integer, String, Text, ARRAY, DateTime, CheckConstraint, Numeric,
    Computed, Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.literature_tag import literature_tag


class Literature(Base):
    __tablename__ = "literature"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500))
    # 归一化标题生成列（与 _common.normalize_title 逐步骤对齐），查重精确匹配走索引
    title_norm: Mapped[Optional[str]] = mapped_column(
        String(500),
        Computed(
            "regexp_replace(regexp_replace(regexp_replace(btrim(lower(title)), "
            "'[-–—]', ' ', 'g'), '[^\\w\\s]', '', 'g'), '\\s+', ' ', 'g')",
            persisted=True,
        ),
        nullable=True,
    )
    title_en: Mapped[Optional[str]] = mapped_column(String(500))
    authors: Mapped[Optional[str]] = mapped_column(Text)
    # P1-1：作者单位（LLM 从文献中提取，AI 提取后回填；此前因无字段被丢弃）
    author_affiliations: Mapped[Optional[str]] = mapped_column(Text)
    journal: Mapped[Optional[str]] = mapped_column(String(300))
    pub_year: Mapped[Optional[int]]
    doi: Mapped[Optional[str]] = mapped_column(String(200))
    pmid: Mapped[Optional[str]] = mapped_column(String(20))
    abstract: Mapped[Optional[str]] = mapped_column(Text)
    keywords: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    region: Mapped[Optional[str]] = mapped_column(String(100))
    province: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    publication_types: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    source_db: Mapped[Optional[str]] = mapped_column(String(50))
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    pdf_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    has_fulltext: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    extracted_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    # LLM 提取的 token 用量与费用统计（AI 提取完成时写入）
    llm_model_used: Mapped[Optional[str]] = mapped_column(String(100))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_usd: Mapped[Any] = mapped_column(Numeric(10, 6), default=0)
    llm_call_count: Mapped[int] = mapped_column(Integer, default=0)
    llm_usage_detail: Mapped[Optional[dict]] = mapped_column(JSON)
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=literature_tag, back_populates="literatures", lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # 软删除：deleted_at 非空时表示已移入回收站
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True, default=None
    )
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID,  # 仅记录删除者，不设外键约束
        nullable=True
    )
    # 文献归属人（上传/创建文献的用户）。用于「按归属终止 AI 提取」：
    # 普通用户只能终止自己归属(owner_id)文献的提取；管理员可终止全部。
    # 存量/后台导入文献 owner_id 为空，视为共享文献（普通用户不可终止，管理员可）。
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID,  # 仅记录归属人，不设外键约束（与 deleted_by 一致）
        nullable=True, index=True
    )
    # 提取任务开始时间戳（用于检测卡死：processing 超过 30 分钟自动重置为 failed）
    extraction_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # F13：提取代数。每次触发提取 +1，任务写库时用 WHERE extraction_generation=本次值 做 CAS，
    # 防止超时回收后重新触发的任务与仍在运行的旧任务互相覆盖写库。
    extraction_generation: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # F14：worker 心跳时间戳。提取进行中周期性刷新，超时回收据此区分"长任务"与"真卡死"
    # （worker 崩溃后心跳停止，超过阈值即回收；正常长任务心跳持续刷新不被误判）。
    worker_heartbeat: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "extraction_status IN ('pending','queued','processing','done','done_no_data','failed')",
            name="lit_extraction_status_check",
        ),
        # F21：title_norm 精确匹配索引（查重走索引）
        Index("idx_lit_title_norm", "title_norm"),
        # F22：pg_trgm GIN 索引，支撑 ilike('%kw%') 子串检索
        Index(
            "idx_lit_title_trgm", "title",
            postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "idx_lit_authors_trgm", "authors",
            postgresql_using="gin", postgresql_ops={"authors": "gin_trgm_ops"},
        ),
        Index(
            "idx_lit_journal_trgm", "journal",
            postgresql_using="gin", postgresql_ops={"journal": "gin_trgm_ops"},
        ),
    )

"""病原学监测数据表。

存储从文献全文中由 LLM 提取的病原学监测数据，用于更全面掌握疾病流行特征。
与血清抗体 data_point 互补：抗体反映人群免疫水平，病原学反映流行株/基因型/变异等病原特征。

阶段2：独立表，不触碰 data_point 表与既有逻辑。单次 LLM 提取调用中同步输出
pathogen_monitoring 数组，主流程构建后写入本表。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.term_normalizer import normalize_province
from app.models.base import Base


class PathogenMonitoring(Base):
    __tablename__ = "pathogen_monitoring"

    # 字段级归一化（覆盖所有 ORM 入库入口）
    @validates("province")
    def _normalize_province(self, key: str, value: str | None) -> str | None:
        return normalize_province(value) if value else value

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    literature_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("literature.id", ondelete="CASCADE"),
        index=True,
    )
    disease: Mapped[str | None] = mapped_column(String(100), index=True)
    # 病原学特征
    pathogen_type: Mapped[str | None] = mapped_column(String(50))       # 病原体类型：病毒/细菌/寄生虫等
    pathogen_name: Mapped[str | None] = mapped_column(String(100), index=True)  # 病原体名称：如 麻疹病毒、风疹病毒
    serotype: Mapped[str | None] = mapped_column(String(50))            # 血清型：如 D8、B3
    genotype: Mapped[str | None] = mapped_column(String(50), index=True)  # 基因型：如 H1、H3
    subtype: Mapped[str | None] = mapped_column(String(50))             # 亚型：如 A(H1N1)、B/Victoria
    lineage: Mapped[str | None] = mapped_column(String(50))             # 谱系/流行株：如 clade 3C.2a、优势株
    variant_sites: Mapped[str | None] = mapped_column(Text)             # 变异位点：如 N450D、V470M
    # 监测指标
    detection_rate: Mapped[float | None] = mapped_column(Numeric(10, 4))  # 检出率(%)
    isolation_count: Mapped[int | None] = mapped_column(Integer)          # 分离株数
    sample_size: Mapped[int | None] = mapped_column(Integer)              # 检测样本量
    detection_method: Mapped[str | None] = mapped_column(String(200))     # 检测方法：PCR/病毒分离/测序等
    population: Mapped[str | None] = mapped_column(String(200))           # 人群/标本来源：如临床标本、健康人群
    specimen: Mapped[str | None] = mapped_column(String(100))             # 标本类型：血清/咽拭子/鼻拭子等
    # 时空溯源
    region: Mapped[str | None] = mapped_column(String(100))
    province: Mapped[str | None] = mapped_column(String(100), index=True)
    city: Mapped[str | None] = mapped_column(String(100))
    collection_year: Mapped[int | None] = mapped_column(index=True)
    # 来源追踪（引用溯源）
    source_page: Mapped[int | None]
    source_context: Mapped[str | None] = mapped_column(Text)
    # 审核
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_pm_review_disease", "review_status", "disease"),
    )
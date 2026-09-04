import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReportTemplate(Base):
    """报告模板：自定义报告章节结构与图表嵌入。

    sections 为 JSON 数组，每个元素含：
      - title: 章节标题
      - type: text（纯文本，LLM 生成）/ chart（图表，调用分析逻辑生成描述+数据摘要）/ table（数据表格）/ kpi（关键指标卡片）
      - content_template: 该章节的内容指引（text 用作 LLM 提示词）
      - order: 章节排序
      - analysis: （chart 类型可选）对应的分析维度：trend / region / age_curve / disease
      - data: （table 类型可选）要渲染的数据表：province / year / age / disease
      - kpi: （kpi 类型可选）关键指标键列表，如 ["point_count","province_count","total_samples","weighted_rate"]
    """

    __tablename__ = "report_template"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    report_type: Mapped[str] = mapped_column(
        String(30), default="antibody_analysis"
    )
    sections: Mapped[list] = mapped_column(JSON, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    desc: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint(
            "report_type IN ('antibody_analysis','vaccination_strategy','immune_barrier_assessment')",
            name="report_template_type_check",
        ),
    )
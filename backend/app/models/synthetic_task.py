"""合成文献自测任务（AI 提取准确度自测）。

记录一次「用生成模型 A 量产已知答案合成文献 → 用提取模型 B 走现有提取链路 →
比对提取值 vs 真实值评估准确度」的完整任务及其评估报告。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyntheticTask(Base):
    __tablename__ = "synthetic_task"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 疾病（如 麻疹）
    disease: Mapped[str] = mapped_column(String(100))
    # 生成文献篇数
    n_literatures: Mapped[int] = mapped_column(Integer, default=20)
    # 每篇文献数据点数
    points_per_literature: Mapped[int] = mapped_column(Integer, default=20)
    # 测试文献来源：generated=生成模型A模拟生成 / existing=从数据库已有文献中选择
    literature_source: Mapped[str] = mapped_column(String(10), default="generated")
    # 生成模型 A（如 ollama:qwen3:8b）
    generator_model: Mapped[str] = mapped_column(String(100))
    # 提取模型 B（触发提取时指定）
    extractor_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 参考模型：existing 来源时用于产出基准(GT)的参考模型
    reference_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 本次选定的多个提取模型列表（多模型对比）
    models: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 测试文献来源编组（existing 来源时记录所选编组 tag.id，便于追溯）
    tag_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # 每篇中混入噪声的数据点比例（0~1）
    noise_ratio: Mapped[float] = mapped_column(Float, default=0.2)
    # 随机种子（保证 ground truth 可复现）
    seed: Mapped[int] = mapped_column(Integer, default=42)
    # 文献载体：text=纯文本全文 / pdf=生成 PDF 文件，用于验证 PDF 解析链路的准确度与效率
    output_format: Mapped[str] = mapped_column(String(10), default="text")
    # 是否在结果部分包含表格（text 模式=Markdown 表格，pdf 模式=PDF 表格），用于验证从表格抽取的能力
    include_table: Mapped[bool] = mapped_column(Boolean, default=True)
    # 任务状态: queued / generating / ready / extracting / assessed / failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ground truth（程序确定性生成，含每点的正确值 + 噪声标记）
    gt_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 评估报告（精确/容差/噪声感知 指标汇总 + 逐文献明细 + 逐字段/逐噪声类型维度）
    report_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 本任务生成的合成文献 id 列表（uuid 字符串）
    literature_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # 阶段计时（耗时展示）UTC
    generation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
"""合成文献自测模块的请求/响应 Schemas。"""
from pydantic import BaseModel, Field


class SyntheticCreate(BaseModel):
    """创建一次 AI 提取准确度自测任务。"""
    disease: str = Field(..., description="疾病，如 麻疹")
    n_literatures: int = Field(20, ge=1, le=100, description="生成文献篇数（existing 来源时为 0，忽略）")
    points_per_literature: int = Field(20, ge=1, le=50, description="每篇文献数据点数")
    generator_model: str = Field(..., description="生成模型 A，如 ollama:qwen3:8b")
    noise_ratio: float = Field(0.2, ge=0.0, le=1.0, description="噪声比例")
    seed: int = Field(42, description="随机种子（可复现）")
    output_format: str = Field("text", pattern="^(text|pdf)$", description="文献载体：text=纯文本全文 / pdf=生成 PDF 文件")
    include_table: bool = Field(True, description="是否在结果部分包含表格（text=Markdown 表格 / pdf=PDF 表格）")
    # 测试文献来源：generated=生成模型A模拟生成 / existing=数据库已有文献
    literature_source: str = Field("generated", pattern="^(generated|existing)$", description="测试文献来源")
    # existing 来源时：所选真实文献 id 列表
    literature_ids: list[str] | None = Field(None, description="existing 来源时选择的数据库已有文献 id")
    # existing 来源时：产出基准(GT)的参考模型
    reference_model: str | None = Field(None, description="existing 来源时产出 GT 的参考模型")


class SyntheticExtract(BaseModel):
    """对任务内文献触发提取（单模型 B 或多模型 models）。"""
    model: str | None = Field(None, description="提取模型 B，如 ollama:qwen2.5:14b（单模型时）")
    models: list[str] | None = Field(None, description="多模型对比时的一次选择多个提取模型")
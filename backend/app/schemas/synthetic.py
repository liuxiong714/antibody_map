"""合成文献自测模块的请求/响应 Schemas。"""
from pydantic import BaseModel, Field


class SyntheticCreate(BaseModel):
    """创建一次 AI 提取准确度自测任务。"""
    disease: str = Field(..., description="疾病，如 麻疹")
    n_literatures: int = Field(20, ge=1, le=100, description="生成文献篇数")
    points_per_literature: int = Field(20, ge=1, le=50, description="每篇文献数据点数")
    generator_model: str = Field(..., description="生成模型 A，如 ollama:qwen3:8b")
    noise_ratio: float = Field(0.2, ge=0.0, le=1.0, description="噪声比例")
    seed: int = Field(42, description="随机种子（可复现）")


class SyntheticExtract(BaseModel):
    """对任务内合成文献触发提取（提取模型 B）。"""
    model: str = Field(..., description="提取模型 B，如 ollama:qwen2.5:14b")
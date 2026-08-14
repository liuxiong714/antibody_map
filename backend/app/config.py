import os
import warnings
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 文件位于项目根目录（backend/ 的父目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM — 默认配置（向后兼容）
    LLM_API_KEY: str = ""  # 必须通过环境变量或 .env 文件配置
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "qwen3:32b"

    # LLM — 按模型厂商独立配置（可选，未配置时回退到 LLM_API_KEY / LLM_BASE_URL）
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # P1-3：本地 LLM（Ollama）配置
    # Ollama 暴露 OpenAI 兼容 API（/v1/chat/completions），无需 API Key
    # 常用本地模型：llama3, qwen2.5, glm4, mistral 等
    OLLAMA_API_KEY: str = "ollama"  # 占位 key（Ollama 不校验）
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"

    # P0-2：多趟提取趟数（1=单趟，2=双趟查漏补缺，3=三趟）
    # 趟数越多召回率越高但 API 调用成本线性增加，推荐 2
    LLM_EXTRACTION_PASSES: int = 2

    # 本地大模型（如 32B/70B）推理慢，请求超时需放宽，单位：秒
    LLM_REQUEST_TIMEOUT: int = 600

    # P2-B1：LLM 并发提取配置
    # 并发请求数上限，需与 Ollama 的 OLLAMA_NUM_PARALLEL 环境变量对齐
    # RTX 4090/5090 实测 4 并发为吞吐与延迟最优拐点（参考 2026 基准测试）
    LLM_CONCURRENCY: int = 4

    # P2：长文档分块阈值（字符数），超过此值触发分块并发提取
    LLM_CHUNK_THRESHOLD: int = 20000
    # P2：单块最大字符数
    LLM_CHUNK_SIZE: int = 15000
    # P2：分块重叠字符数（保持上下文连贯）
    LLM_CHUNK_OVERLAP: int = 500

    # 文本预处理最大保留字符数（须 > LLM_CHUNK_THRESHOLD，否则分块逻辑永不触发）
    TEXT_PREPROCESS_MAX_CHARS: int = 60000

    # MinerU 增强 PDF 解析（需安装 PyTorch + mineru 包，首次使用会自动下载模型约 2-3GB）
    ENABLE_MINERU_PDF_PARSER: bool = False

    # ===== 提取准确度 & 性价比优化配置 =====
    # A3：grounding 模糊匹配阈值（0-1，越高越严格）
    GROUNDING_FUZZY_THRESHOLD: float = 0.72
    # A3：grounding 失败时是否用 LLM 重新提取 source_context
    GROUNDING_LLM_REGROUND: bool = True

    # B5：分级模型策略（留空则不启用，统一用 LLM_MODEL）
    LLM_MODEL_LIGHT: str = ""   # 简单文献用（短文本+无表格），如 "deepseek-chat"
    LLM_MODEL_STRONG: str = ""  # 复杂文献用（长文本+复杂表格），如 "deepseek-reasoner"

    # A1：结构化表格优先提取（有表格时先单独从表格提取一轮）
    LLM_TABLE_FIRST_EXTRACTION: bool = True

    # A2：两阶段提取（先抽骨架再填数值，默认关闭，适合对准确度要求极高的场景）
    LLM_TWO_PHASE_EXTRACTION: bool = False

    # B8：多趟提取智能调度（第1趟覆盖率>90%则跳过后续趟）
    LLM_ADAPTIVE_PASSES: bool = True

    # B9：审核反馈闭环（将 rejected 数据点作为 few-shot 注入 prompt）
    LLM_FEEDBACK_FEW_SHOT: bool = True
    LLM_FEEDBACK_FEW_SHOT_COUNT: int = 5

    # Database (默认值适用于 Docker Compose 本地开发环境)
    DATABASE_URL: str = "postgresql+asyncpg://antibody:antibody123@localhost:5432/antibody_map"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO (默认值适用于 Docker Compose 本地开发环境)
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "antibody"
    MINIO_SECRET_KEY: str = "antibody123"
    MINIO_BUCKET_LITERATURE: str = "antibody-literature"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # OCR
    BAIDU_OCR_API_KEY: str = ""
    BAIDU_OCR_SECRET_KEY: str = ""
    OCR_FALLBACK_TO_BAIDU: bool = False
    # Tesseract 可执行文件路径（默认自动探测：PATH 或 Windows 常见安装位置）
    TESSERACT_CMD: str = ""
    # Tesseract 语言数据目录（tessdata），默认取可执行文件同目录下的 tessdata
    TESSERACT_DATA_DIR: str = ""

    # App
    SECRET_KEY: str = ""  # 必须通过环境变量或 .env 文件配置
    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    # 应用版本号（单一版本源，main.py 与 /health 端点均引用此值）
    APP_VERSION: str = "1.7.5"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    MAX_UPLOAD_SIZE: int = 52428800

    @model_validator(mode="after")
    def _validate_constraints(self) -> "Settings":
        """交叉校验配置项之间的约束关系，在启动时即发现配置错误。"""
        # 核心结构性约束：预处理截断必须大于分块阈值，否则分块并发逻辑永不触发
        if self.TEXT_PREPROCESS_MAX_CHARS <= self.LLM_CHUNK_THRESHOLD:
            raise ValueError(
                "TEXT_PREPROCESS_MAX_CHARS 必须大于 LLM_CHUNK_THRESHOLD，"
                f"当前 {self.TEXT_PREPROCESS_MAX_CHARS} <= {self.LLM_CHUNK_THRESHOLD}，"
                "否则长文档分块并发逻辑将永不触发"
            )

        # 单块大小必须大于重叠区，否则分块无意义
        if self.LLM_CHUNK_SIZE <= self.LLM_CHUNK_OVERLAP:
            raise ValueError(
                "LLM_CHUNK_SIZE 必须大于 LLM_CHUNK_OVERLAP，"
                f"当前 {self.LLM_CHUNK_SIZE} <= {self.LLM_CHUNK_OVERLAP}"
            )

        # 分块阈值应不小于单块大小（否则首块即超过阈值，逻辑退化）
        if self.LLM_CHUNK_THRESHOLD < self.LLM_CHUNK_SIZE:
            warnings.warn(
                f"LLM_CHUNK_THRESHOLD ({self.LLM_CHUNK_THRESHOLD}) 小于 "
                f"LLM_CHUNK_SIZE ({self.LLM_CHUNK_SIZE})，分块逻辑可能退化",
                stacklevel=2,
            )

        if self.LLM_CONCURRENCY < 1:
            raise ValueError(f"LLM_CONCURRENCY 必须 >= 1，当前 {self.LLM_CONCURRENCY}")

        if self.LLM_FEEDBACK_FEW_SHOT_COUNT < 1:
            raise ValueError(
                f"LLM_FEEDBACK_FEW_SHOT_COUNT 必须 >= 1，当前 {self.LLM_FEEDBACK_FEW_SHOT_COUNT}"
            )

        # 生产环境必须配置强密钥（>=32 字符）
        if self.APP_ENV != "development" and len(self.SECRET_KEY) < 32:
            raise ValueError(
                f"生产环境 SECRET_KEY 必须 >= 32 字符，当前长度 {len(self.SECRET_KEY)}"
            )

        # 本地 Ollama 并发一致性：若设置了 OLLAMA_NUM_PARALLEL，应与 LLM_CONCURRENCY 对齐
        ollama_parallel = os.getenv("OLLAMA_NUM_PARALLEL")
        if ollama_parallel and int(ollama_parallel) != self.LLM_CONCURRENCY:
            warnings.warn(
                f"OLLAMA_NUM_PARALLEL ({ollama_parallel}) 与 LLM_CONCURRENCY "
                f"({self.LLM_CONCURRENCY}) 不一致，可能导致本地模型并发异常",
                stacklevel=2,
            )

        return self


settings = Settings()

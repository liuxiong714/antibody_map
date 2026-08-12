from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM — 默认配置（向后兼容）
    LLM_API_KEY: str = ""  # 必须通过环境变量或 .env 文件配置
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-chat"

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
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    MAX_UPLOAD_SIZE: int = 52428800


settings = Settings()

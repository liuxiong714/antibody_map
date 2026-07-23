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

    # App
    SECRET_KEY: str = ""  # 必须通过环境变量或 .env 文件配置
    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    MAX_UPLOAD_SIZE: int = 52428800


settings = Settings()

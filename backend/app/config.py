from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    LLM_API_KEY: str = "sk-your-api-key-here"
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-chat"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://antibody:antibody123@postgres:5432/antibody_map"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # MinIO
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "antibody"
    MINIO_SECRET_KEY: str = "antibody123"
    MINIO_BUCKET_LITERATURE: str = "antibody-literature"

    # Celery
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    # App
    SECRET_KEY: str = "change-this-in-production"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    MAX_UPLOAD_SIZE: int = 52428800


settings = Settings()

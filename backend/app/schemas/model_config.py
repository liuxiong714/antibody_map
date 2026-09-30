from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class ApiModelConfigCreate(BaseModel):
    name: str
    model_name: str
    api_key: str
    base_url: str
    description: str | None = None
    expires_at: datetime | None = None


class ApiModelConfigUpdate(BaseModel):
    name: str | None = None
    model_name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    description: str | None = None
    is_active: bool | None = None
    expires_at: datetime | None = None


class ApiModelConfigResponse(BaseModel):
    id: str
    name: str
    model_name: str
    api_key: str
    base_url: str
    description: str | None = None
    is_active: bool
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModelOption(BaseModel):
    """单个模型选项（本地或远程）"""
    value: str
    label: str
    group: str  # "local" | "remote"
    is_default: bool = False


class ModelsListResponse(BaseModel):
    local: list[ModelOption]
    remote: list[ModelOption]


class LocalModelConfigCreate(BaseModel):
    name: str
    model_name: str
    description: str | None = None


class LocalModelConfigUpdate(BaseModel):
    name: str | None = None
    model_name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class LocalModelConfigResponse(BaseModel):
    id: str
    name: str
    model_name: str
    description: str | None = None
    is_active: bool
    # 模型是否已在本地 Ollama 下载；None 表示无法确认（Ollama 未启动/不可达）
    installed: bool | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v):
        return str(v) if isinstance(v, UUID) else v
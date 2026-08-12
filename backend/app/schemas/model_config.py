from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ApiModelConfigCreate(BaseModel):
    name: str
    model_name: str
    api_key: str
    base_url: str
    description: Optional[str] = None


class ApiModelConfigUpdate(BaseModel):
    name: Optional[str] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ApiModelConfigResponse(BaseModel):
    id: str
    name: str
    model_name: str
    api_key: str
    base_url: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ModelOption(BaseModel):
    """单个模型选项（本地或远程）"""
    value: str
    label: str
    group: str  # "local" | "remote"
    is_default: bool = False


class ModelsListResponse(BaseModel):
    local: list[ModelOption]
    remote: list[ModelOption]
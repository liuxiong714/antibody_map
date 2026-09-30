"""文件夹监控相关的 Pydantic 模型。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.crypto import mask


class MonitoredFolderBase(BaseModel):
    name: str = Field(..., max_length=200, description="用户友好名称")
    folder_path: str = Field(..., max_length=500, description="本地文件夹绝对路径")
    enabled: bool = True
    scan_interval_seconds: int = Field(300, ge=30, le=86400, description="扫描间隔（秒）")
    file_extensions: str | None = Field(None, description="逗号分隔扩展名，如 .pdf,.caj")
    auto_extract: bool = True
    extraction_model: str | None = None
    extraction_api_key: str | None = None
    extraction_base_url: str | None = None


class MonitoredFolderCreate(MonitoredFolderBase):
    pass


class MonitoredFolderUpdate(BaseModel):
    name: str | None = None
    folder_path: str | None = None
    enabled: bool | None = None
    scan_interval_seconds: int | None = Field(None, ge=30, le=86400)
    file_extensions: str | None = None
    auto_extract: bool | None = None
    extraction_model: str | None = None
    extraction_api_key: str | None = None
    extraction_base_url: str | None = None


class MonitoredFolderResponse(MonitoredFolderBase):
    id: uuid.UUID
    last_scan_at: datetime | None = None
    last_scan_new_count: int = 0
    total_imported_count: int = 0
    status: str = "idle"
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    # S4：响应不回传明文 API Key，仅返回掩码（避免任意登录用户窃取他人密钥）
    @field_validator("extraction_api_key")
    @classmethod
    def _mask_api_key(cls, v: str | None) -> str | None:
        return mask(v) if v else v


class MonitoredFileResponse(BaseModel):
    id: uuid.UUID
    folder_id: uuid.UUID
    file_path: str
    file_name: str
    file_hash: str | None = None
    file_size: int | None = None
    file_mtime: datetime | None = None
    status: str
    literature_id: uuid.UUID | None = None
    error_message: str | None = None
    imported_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

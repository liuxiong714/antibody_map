"""文件夹监控相关的 Pydantic 模型。"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.core.crypto import mask


class MonitoredFolderBase(BaseModel):
    name: str = Field(..., max_length=200, description="用户友好名称")
    folder_path: str = Field(..., max_length=500, description="本地文件夹绝对路径")
    enabled: bool = True
    scan_interval_seconds: int = Field(300, ge=30, le=86400, description="扫描间隔（秒）")
    file_extensions: Optional[str] = Field(None, description="逗号分隔扩展名，如 .pdf,.caj")
    auto_extract: bool = True
    extraction_model: Optional[str] = None
    extraction_api_key: Optional[str] = None
    extraction_base_url: Optional[str] = None


class MonitoredFolderCreate(MonitoredFolderBase):
    pass


class MonitoredFolderUpdate(BaseModel):
    name: Optional[str] = None
    folder_path: Optional[str] = None
    enabled: Optional[bool] = None
    scan_interval_seconds: Optional[int] = Field(None, ge=30, le=86400)
    file_extensions: Optional[str] = None
    auto_extract: Optional[bool] = None
    extraction_model: Optional[str] = None
    extraction_api_key: Optional[str] = None
    extraction_base_url: Optional[str] = None


class MonitoredFolderResponse(MonitoredFolderBase):
    id: uuid.UUID
    last_scan_at: Optional[datetime] = None
    last_scan_new_count: int = 0
    total_imported_count: int = 0
    status: str = "idle"
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    # S4：响应不回传明文 API Key，仅返回掩码（避免任意登录用户窃取他人密钥）
    @field_validator("extraction_api_key")
    @classmethod
    def _mask_api_key(cls, v: Optional[str]) -> Optional[str]:
        return mask(v) if v else v


class MonitoredFileResponse(BaseModel):
    id: uuid.UUID
    folder_id: uuid.UUID
    file_path: str
    file_name: str
    file_hash: Optional[str] = None
    file_size: Optional[int] = None
    file_mtime: Optional[datetime] = None
    status: str
    literature_id: Optional[uuid.UUID] = None
    error_message: Optional[str] = None
    imported_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

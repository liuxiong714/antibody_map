from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DataPointCreate(BaseModel):
    literature_id: Optional[UUID] = None
    disease: Optional[str] = None
    region: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    age_group: Optional[str] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    sample_size: Optional[int] = None
    data_type: Optional[str] = Field(None, pattern=r"^(seroprevalence|gmc)$")
    value: Optional[float] = None
    unit: Optional[str] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    method: Optional[str] = None
    assay: Optional[str] = None
    population: Optional[str] = None
    collection_year: Optional[int] = None
    # 溯源字段（P0 新增）
    source_page: Optional[int] = None
    source_context: Optional[str] = None
    source_char_start: Optional[int] = None
    source_char_end: Optional[int] = None
    is_grounded: bool = False
    confidence: str = Field("medium", pattern=r"^(high|medium|low)$")
    review_status: str = Field("pending", pattern=r"^(pending|approved|rejected)$")


class DataPointUpdate(BaseModel):
    disease: Optional[str] = None
    region: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    age_group: Optional[str] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    sample_size: Optional[int] = None
    data_type: Optional[str] = Field(None, pattern=r"^(seroprevalence|gmc)$")
    value: Optional[float] = None
    unit: Optional[str] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    method: Optional[str] = None
    assay: Optional[str] = None
    population: Optional[str] = None
    collection_year: Optional[int] = None
    # 溯源字段（P0 新增，允许手动修正）
    source_page: Optional[int] = None
    source_context: Optional[str] = None
    source_char_start: Optional[int] = None
    source_char_end: Optional[int] = None
    is_grounded: Optional[bool] = None
    confidence: Optional[str] = Field(None, pattern=r"^(high|medium|low)$")
    review_status: Optional[str] = Field(None, pattern=r"^(pending|approved|rejected)$")


class DataPointResponse(BaseModel):
    id: UUID
    literature_id: Optional[UUID] = None
    disease: Optional[str] = None
    region: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    age_group: Optional[str] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    sample_size: Optional[int] = None
    data_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    method: Optional[str] = None
    assay: Optional[str] = None
    population: Optional[str] = None
    collection_year: Optional[int] = None
    # 溯源字段（P0 新增）
    source_page: Optional[int] = None
    source_context: Optional[str] = None
    source_char_start: Optional[int] = None
    source_char_end: Optional[int] = None
    is_grounded: bool
    confidence: str
    review_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

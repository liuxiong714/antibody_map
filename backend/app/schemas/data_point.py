from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DataPointCreate(BaseModel):
    literature_id: UUID | None = None
    disease: str | None = None
    region: str | None = None
    province: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    age_group: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    sample_size: int | None = None
    data_type: str | None = Field(None, pattern=r"^(seroprevalence|gmc)$")
    value: float | None = None
    unit: str | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    method: str | None = None
    assay: str | None = None
    population: str | None = None
    collection_year: int | None = None
    # 溯源字段（P0 新增）
    source_page: int | None = None
    source_context: str | None = None
    source_char_start: int | None = None
    source_char_end: int | None = None
    is_grounded: bool = False
    confidence: str = Field("medium", pattern=r"^(high|medium|low)$")
    review_status: str = Field("pending", pattern=r"^(pending|approved|rejected)$")


class DataPointUpdate(BaseModel):
    disease: str | None = None
    region: str | None = None
    province: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    age_group: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    sample_size: int | None = None
    data_type: str | None = Field(None, pattern=r"^(seroprevalence|gmc)$")
    value: float | None = None
    unit: str | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    method: str | None = None
    assay: str | None = None
    population: str | None = None
    collection_year: int | None = None
    # 溯源字段（P0 新增，允许手动修正）
    source_page: int | None = None
    source_context: str | None = None
    source_char_start: int | None = None
    source_char_end: int | None = None
    is_grounded: bool | None = None
    confidence: str | None = Field(None, pattern=r"^(high|medium|low)$")
    review_status: str | None = Field(None, pattern=r"^(pending|approved|rejected)$")


class DataPointResponse(BaseModel):
    id: UUID
    literature_id: UUID | None = None
    disease: str | None = None
    region: str | None = None
    province: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    age_group: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    sample_size: int | None = None
    data_type: str | None = None
    value: float | None = None
    unit: str | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    method: str | None = None
    assay: str | None = None
    population: str | None = None
    collection_year: int | None = None
    # 溯源字段（P0 新增）
    source_page: int | None = None
    source_context: str | None = None
    source_char_start: int | None = None
    source_char_end: int | None = None
    is_grounded: bool
    confidence: str
    review_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

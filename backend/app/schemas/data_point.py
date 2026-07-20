from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


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
    data_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    method: Optional[str] = None
    assay: Optional[str] = None
    population: Optional[str] = None
    collection_year: Optional[int] = None
    confidence: str = "medium"
    review_status: str = "pending"


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
    data_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    method: Optional[str] = None
    assay: Optional[str] = None
    population: Optional[str] = None
    collection_year: Optional[int] = None
    confidence: Optional[str] = None
    review_status: Optional[str] = None


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
    confidence: str
    review_status: str
    created_at: datetime

    model_config = {"from_attributes": True}

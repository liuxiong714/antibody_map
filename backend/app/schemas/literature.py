from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class LiteratureCreate(BaseModel):
    title: str
    title_en: Optional[str] = None
    authors: Optional[str] = None
    journal: Optional[str] = None
    pub_year: Optional[int] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    abstract: Optional[str] = None
    keywords: Optional[list[str]] = None
    region: Optional[str] = None
    province: Optional[str] = None
    publication_types: Optional[list[str]] = None
    source_db: Optional[str] = None
    file_path: Optional[str] = None
    has_fulltext: bool = False


class LiteratureUpdate(BaseModel):
    title: Optional[str] = None
    title_en: Optional[str] = None
    authors: Optional[str] = None
    journal: Optional[str] = None
    pub_year: Optional[int] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    abstract: Optional[str] = None
    keywords: Optional[list[str]] = None
    region: Optional[str] = None
    province: Optional[str] = None
    publication_types: Optional[list[str]] = None
    source_db: Optional[str] = None
    file_path: Optional[str] = None
    has_fulltext: Optional[bool] = None
    extraction_status: Optional[str] = None
    extracted_count: Optional[int] = None
    approved_count: Optional[int] = None


class LiteratureResponse(BaseModel):
    id: UUID
    title: str
    title_en: Optional[str] = None
    authors: Optional[str] = None
    journal: Optional[str] = None
    pub_year: Optional[int] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    abstract: Optional[str] = None
    keywords: Optional[list[str]] = None
    region: Optional[str] = None
    province: Optional[str] = None
    publication_types: Optional[list[str]] = None
    source_db: Optional[str] = None
    file_path: Optional[str] = None
    pdf_hash: Optional[str] = None
    has_fulltext: bool = False
    file_format: Optional[str] = None
    extraction_status: str
    extracted_count: int
    approved_count: int
    # LLM 提取的 token 用量与费用统计
    llm_model_used: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_cost_usd: Optional[float] = None
    llm_call_count: int = 0
    llm_usage_detail: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ===== 查重与合并相关 Schema =====

class CheckDuplicateRequest(BaseModel):
    literature_id: Optional[UUID] = None
    title: Optional[str] = None
    doi: Optional[str] = None
    authors: Optional[str] = None
    pdf_hash: Optional[str] = None


class DuplicateMatchItem(BaseModel):
    literature: LiteratureResponse
    match_reasons: list[str]
    match_values: dict[str, str]


class CheckDuplicateResponse(BaseModel):
    literature_id: Optional[str] = None
    duplicates: list[DuplicateMatchItem]
    total: int


class DuplicateGroup(BaseModel):
    literature_ids: list[UUID]
    match_reasons: list[str]
    representative_id: UUID


class ScanDuplicatesResponse(BaseModel):
    groups: list[DuplicateGroup]
    total_groups: int
    total_duplicates: int


class MergePreviewRequest(BaseModel):
    source_id: UUID
    target_id: UUID


class FieldComparison(BaseModel):
    field: str
    source_value: Any = None
    target_value: Any = None
    differs: bool


class DataPointConflictItem(BaseModel):
    source_dp: dict
    target_dp: dict
    key: str


class MergePreviewResponse(BaseModel):
    field_comparison: list[FieldComparison]
    source_data_point_count: int
    target_data_point_count: int
    conflicts: list[DataPointConflictItem]


class MergeRequest(BaseModel):
    source_id: UUID
    target_id: UUID
    field_choices: dict[str, str]
    dp_conflict_strategy: str = "keep_both"


class MergeResultResponse(BaseModel):
    merged_literature: LiteratureResponse
    moved_data_points: int
    deleted_conflict_data_points: int
    deleted_source_id: str

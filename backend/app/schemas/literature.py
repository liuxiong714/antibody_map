from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class LiteratureCreate(BaseModel):
    title: str
    title_en: str | None = None
    authors: str | None = None
    author_affiliations: str | None = None
    journal: str | None = None
    pub_year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    abstract: str | None = None
    keywords: list[str] | None = None
    region: str | None = None
    province: str | None = None
    publication_types: list[str] | None = None
    source_db: str | None = None
    file_path: str | None = None
    has_fulltext: bool = False


class LiteratureUpdate(BaseModel):
    title: str | None = None
    title_en: str | None = None
    authors: str | None = None
    author_affiliations: str | None = None
    journal: str | None = None
    pub_year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    abstract: str | None = None
    keywords: list[str] | None = None
    region: str | None = None
    province: str | None = None
    publication_types: list[str] | None = None
    source_db: str | None = None
    has_fulltext: bool | None = None
    extraction_status: str | None = None
    extracted_count: int | None = None
    approved_count: int | None = None


class LiteratureResponse(BaseModel):
    id: UUID
    title: str
    title_en: str | None = None
    authors: str | None = None
    author_affiliations: str | None = None
    journal: str | None = None
    pub_year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    abstract: str | None = None
    keywords: list[str] | None = None
    region: str | None = None
    province: str | None = None
    publication_types: list[str] | None = None
    source_db: str | None = None
    file_path: str | None = None
    pdf_hash: str | None = None
    has_fulltext: bool = False
    file_format: str | None = None
    extraction_status: str
    extracted_count: int
    approved_count: int
    # LLM 提取的 token 用量与费用统计
    llm_model_used: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_cost_usd: float | None = None
    llm_call_count: int = 0
    llm_usage_detail: dict | None = None
    tags: list[dict] | None = None
    # 知识库(KG)三元组抽取状态：kg_extracted=true 表示该文献已在知识库中抽取过
    kg_extracted: bool | None = None
    kg_triple_count: int = 0
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None

    model_config = {"from_attributes": True}


# ===== 查重与合并相关 Schema =====

class CheckDuplicateRequest(BaseModel):
    literature_id: UUID | None = None
    title: str | None = None
    doi: str | None = None
    authors: str | None = None
    pdf_hash: str | None = None


class DuplicateMatchItem(BaseModel):
    literature: LiteratureResponse
    match_reasons: list[str]
    match_values: dict[str, str]


class CheckDuplicateResponse(BaseModel):
    literature_id: str | None = None
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

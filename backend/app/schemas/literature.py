from datetime import datetime
from typing import Optional
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
    has_fulltext: bool = False
    extraction_status: str
    extracted_count: int
    approved_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

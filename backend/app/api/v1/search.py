from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import PagedResponse
from app.schemas.literature import LiteratureResponse
from app.schemas.data_point import DataPointResponse
from app.services import search_service

router = APIRouter()


@router.post("/search/literatures", response_model=PagedResponse, summary="高级检索文献", description="按关键词、疾病、省份、年份范围、提取状态等条件高级检索文献，支持分页")
async def search_literatures(
    keyword: Optional[str] = Query(None, description="关键词（标题/作者/期刊）"),
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始发表年份"),
    year_end: Optional[int] = Query(None, description="结束发表年份"),
    extraction_status: Optional[str] = Query(None, description="提取状态"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """高级检索文献"""
    items, total = await search_service.search_literatures(
        db=db,
        keyword=keyword,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        extraction_status=extraction_status,
        page=page,
        page_size=page_size,
    )
    return PagedResponse(
        items=[LiteratureResponse.model_validate(item).model_dump() for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/search/data-points", response_model=PagedResponse, summary="高级检索数据点", description="按疾病、省份、年份范围、年龄、人群类型、数据类型、审核状态等条件高级检索数据点，支持分页")
async def search_data_points(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始采样年份"),
    year_end: Optional[int] = Query(None, description="结束采样年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    population_type: Optional[str] = Query(None, description="人群类型"),
    data_type: Optional[str] = Query(None, description="数据类型：seroprevalence | gmc"),
    review_status: Optional[str] = Query("approved", description="审核状态"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """高级检索数据点"""
    items, total = await search_service.search_data_points(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
        population_type=population_type,
        data_type=data_type,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )
    return PagedResponse(
        items=[DataPointResponse.model_validate(item).model_dump() for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )

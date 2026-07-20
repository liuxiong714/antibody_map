from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiResponse
from app.services import map_service

router = APIRouter()


@router.get("/map/province-data", response_model=ApiResponse)
async def province_data(
    disease: Optional[str] = Query(None, description="疾病 key，如 measles"),
    data_type: Optional[str] = Query(None, description="数据类型：seroprevalence | gmc"),
    province: Optional[str] = Query(None, description="省份筛选"),
    age_group: Optional[str] = Query(None, description="年龄组筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    db: AsyncSession = Depends(get_db),
):
    """获取省份级聚合地图数据"""
    data = await map_service.get_province_data(
        db=db,
        disease=disease,
        data_type=data_type,
        province=province,
        age_group=age_group,
        year_start=year_start,
        year_end=year_end,
    )
    return ApiResponse(data=data)


@router.get("/map/city-data", response_model=ApiResponse)
async def city_data(
    province: str = Query(..., description="省份名称，必填"),
    disease: Optional[str] = Query(None, description="疾病 key"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    db: AsyncSession = Depends(get_db),
):
    """获取城市级聚合地图数据"""
    data = await map_service.get_city_data(
        db=db,
        province=province,
        disease=disease,
        data_type=data_type,
    )
    return ApiResponse(data=data)


@router.get("/map/summary", response_model=ApiResponse)
async def summary(
    disease: Optional[str] = Query(None, description="疾病 key"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    db: AsyncSession = Depends(get_db),
):
    """获取全国汇总统计"""
    data = await map_service.get_summary(
        db=db,
        disease=disease,
        data_type=data_type,
    )
    return ApiResponse(data=data)

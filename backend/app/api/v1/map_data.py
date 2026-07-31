from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiResponse
from app.services import map_service

router = APIRouter()


@router.get("/map/province-data", response_model=ApiResponse)
async def province_data(
    disease: Optional[str] = Query(None, description="disease key"),
    data_type: Optional[str] = Query(None, description="data type: seroprevalence | gmc"),
    province: Optional[str] = Query(None, description="province filter"),
    age_min: Optional[int] = Query(None, description="minimum age"),
    age_max: Optional[int] = Query(None, description="maximum age"),
    year_start: Optional[int] = Query(None, description="start year"),
    year_end: Optional[int] = Query(None, description="end year"),
    gender: Optional[str] = Query(None, description="gender"),
    occupation: Optional[str] = Query(None, description="occupation"),
    db: AsyncSession = Depends(get_db),
):
    """get province-level map data"""
    data = await map_service.get_province_data(
        db=db,
        disease=disease,
        data_type=data_type,
        province=province,
        age_min=age_min,
        age_max=age_max,
        year_start=year_start,
        year_end=year_end,
        gender=gender,
        occupation=occupation,
    )
    return ApiResponse(data=data)


@router.get("/map/city-data", response_model=ApiResponse)
async def city_data(
    province: str = Query(..., description="province name, required"),
    disease: Optional[str] = Query(None, description="disease key"),
    data_type: Optional[str] = Query(None, description="data type"),
    db: AsyncSession = Depends(get_db),
):
    """get city-level map data"""
    data = await map_service.get_city_data(
        db=db,
        province=province,
        disease=disease,
        data_type=data_type,
    )
    return ApiResponse(data=data)


@router.get("/map/summary", response_model=ApiResponse)
async def summary(
    disease: Optional[str] = Query(None, description="disease key"),
    data_type: Optional[str] = Query(None, description="data type"),
    db: AsyncSession = Depends(get_db),
):
    """get national summary"""
    data = await map_service.get_summary(
        db=db,
        disease=disease,
        data_type=data_type,
    )
    return ApiResponse(data=data)
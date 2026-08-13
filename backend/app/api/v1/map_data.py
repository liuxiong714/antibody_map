import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint

from app.api.deps import get_db
from app.schemas.common import ApiResponse
from app.services import map_service

router = APIRouter()


@router.get("/map/province-data", response_model=ApiResponse, summary="获取省级地图数据", description="获取省级抗体水平地图数据，支持按疾病、数据类型、省份、年龄、年份、性别、职业筛选")
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


@router.get("/map/city-data", response_model=ApiResponse, summary="获取市级地图数据", description="获取指定省份下各城市的抗体水平地图数据，支持按疾病和数据类型筛选")
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


@router.get("/map/summary", response_model=ApiResponse, summary="获取全国汇总", description="获取全国范围的抗体水平汇总数据，包括覆盖省份、数据点数、均值等统计信息")
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


@router.get("/map/yearly-data", response_model=ApiResponse, summary="获取年度数据", description="按年份分组返回各省抗体水平数据，用于时间序列动态展示，支持多维度筛选")
async def yearly_province_data(
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
    """按年份分组返回各省抗体水平数据，用于时间序列动态展示"""
    data = await map_service.get_province_yearly_data(
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


@router.get("/map/available-years", response_model=ApiResponse, summary="获取可用年份列表", description="获取数据中包含的所有可用年份，用于前端时间滑块配置，支持按疾病筛选")
async def available_years(
    disease: Optional[str] = Query(None, description="disease key"),
    db: AsyncSession = Depends(get_db),
):
    """获取可用年份列表，用于时间滑块"""
    years = await map_service.get_available_years(db=db, disease=disease)
    return ApiResponse(data=years)


@router.get("/map/population-options", response_model=ApiResponse, summary="获取人群分类选项", description="获取所有已审核数据点中出现的人群分类列表，用于前端的职业下拉框动态选项，支持按疾病筛选")
async def population_options(
    disease: Optional[str] = Query(None, description="disease key, optional filter"),
    db: AsyncSession = Depends(get_db),
):
    """获取所有已审核数据点中出现的人群分类列表。

    用于前端"全部职业"下拉框的动态选项——根据文献中实际定义的研究对象
    自动更新，而非硬编码列表。支持按疾病筛选。
    """
    options = await map_service.get_population_options(db=db, disease=disease)
    return ApiResponse(data=options)


@router.get("/map/export-data-points", summary="导出地图数据点CSV", description="导出已审核数据点为CSV文件，应用地图页面的筛选条件，便于下载分析")
async def export_map_data_points(
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
    """导出已审核数据点为 CSV（地图页筛选条件）"""
    base = select(DataPoint).where(DataPoint.review_status == "approved")
    if disease:
        base = base.where(DataPoint.disease == disease)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)
    if province:
        base = base.where(DataPoint.province.ilike(f"%{province}%"))
    if age_min is not None:
        base = base.where(DataPoint.age_min >= age_min)
    if age_max is not None:
        base = base.where(DataPoint.age_max <= age_max)
    if year_start:
        base = base.where(DataPoint.collection_year >= year_start)
    if year_end:
        base = base.where(DataPoint.collection_year <= year_end)
    if gender:
        base = base.where(DataPoint.population.ilike(f"%{gender}%"))
    if occupation:
        base = base.where(DataPoint.population.ilike(f"%{occupation}%"))

    result = await db.execute(base)
    rows = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "疾病", "省份", "城市", "数据类型", "数值", "单位", "样本量",
        "年龄下限", "年龄上限", "采集年份", "置信度", "人群",
        "检测方法", "assay", "CI下限", "CI上限", "审核状态",
    ])
    for dp in rows:
        writer.writerow([
            dp.disease, dp.province, dp.city, dp.data_type,
            float(dp.value) if dp.value is not None else None, dp.unit, dp.sample_size,
            dp.age_min, dp.age_max, dp.collection_year, dp.confidence,
            dp.population, dp.method, dp.assay,
            float(dp.ci_lower) if dp.ci_lower is not None else None,
            float(dp.ci_upper) if dp.ci_upper is not None else None,
            dp.review_status,
        ])

    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''map_data_points.csv"},
    )
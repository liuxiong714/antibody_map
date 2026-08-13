from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, HTTPException, Body
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiResponse
from app.services import report_service

router = APIRouter()


class VaccinationStrategyRequest(BaseModel):
    task_type: str
    task_time: str
    task_location: str
    personnel_count: int
    personnel_gender: str = ""
    personnel_age: str = ""
    personnel_vaccination_history: str = ""
    title: Optional[str] = None


class UpdateReportRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


@router.post("/reports/generate", response_model=ApiResponse, summary="生成免疫学报告", description="生成免疫学参考意见报告，支持按疾病、省份、数据类型筛选，可选择语言（中文/英文）和自定义标题")
async def generate_report(
    disease: Optional[str] = Query(None, description="疾病 key"),
    province: Optional[str] = Query(None, description="省份筛选"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    language: str = Query("zh", description="报告语言：zh | en"),
    title: Optional[str] = Query(None, description="自定义报告标题"),
    model: Optional[str] = Query(None, description="LLM 模型名，默认使用 .env 配置"),
    db: AsyncSession = Depends(get_db),
):
    """生成免疫学参考意见报告"""
    try:
        data = await report_service.generate_report(
            db=db,
            disease=disease,
            province=province,
            data_type=data_type,
            language=language,
            title=title,
            model=model,
        )
        return ApiResponse(message="报告生成成功", data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reports/generate-vaccination-strategy", response_model=ApiResponse, summary="生成疫苗接种策略报告", description="生成疫苗接种任务的策略研判报告，根据任务类型、时间、地点、人员信息生成专业建议")
async def generate_vaccination_strategy(
    req: VaccinationStrategyRequest,
    db: AsyncSession = Depends(get_db),
):
    """生成疫苗接种策略研判报告"""
    try:
        data = await report_service.generate_vaccination_strategy_report(
            db=db,
            task_type=req.task_type,
            task_time=req.task_time,
            task_location=req.task_location,
            personnel_count=req.personnel_count,
            personnel_gender=req.personnel_gender,
            personnel_age=req.personnel_age,
            personnel_vaccination_history=req.personnel_vaccination_history,
            title=req.title,
        )
        return ApiResponse(message="疫苗接种策略报告生成成功", data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports", response_model=ApiResponse, summary="获取报告列表", description="分页获取所有已生成的报告列表")
async def list_reports(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
):
    """获取报告列表"""
    data = await report_service.get_reports(db=db, page=page, page_size=page_size)
    return ApiResponse(message="操作成功", data=data)


@router.get("/reports/{report_id}", response_model=ApiResponse, summary="获取报告详情", description="根据报告ID获取单个报告的详细信息，包括标题、内容、生成时间等")
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单个报告详情"""
    data = await report_service.get_report_by_id(db=db, report_id=report_id)
    if not data:
        raise HTTPException(status_code=404, detail="报告不存在")
    return ApiResponse(message="操作成功", data=data)


@router.get("/reports/{report_id}/download", summary="下载报告文件", description="将报告内容下载为Markdown文件，方便离线查看和分享")
async def download_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    """下载报告为 Markdown 文件"""
    data = await report_service.get_report_by_id(db=db, report_id=report_id)
    if not data:
        raise HTTPException(status_code=404, detail="报告不存在")
    encoded_filename = quote(data["title"] + ".md")
    return Response(
        content=data["content"].encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
    )


@router.put("/reports/{report_id}", response_model=ApiResponse, summary="更新报告", description="更新报告的标题或内容，允许用户编辑已生成的报告")
async def update_report(
    report_id: str,
    req: UpdateReportRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新报告（标题或内容）"""
    data = await report_service.update_report(
        db=db,
        report_id=report_id,
        title=req.title,
        content=req.content,
    )
    if not data:
        raise HTTPException(status_code=404, detail="报告不存在")
    return ApiResponse(message="报告已更新", data=data)


@router.delete("/reports/{report_id}", response_model=ApiResponse, summary="删除报告", description="根据报告ID删除指定的报告")
async def delete_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除报告"""
    deleted = await report_service.delete_report(db=db, report_id=report_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="报告不存在")
    return ApiResponse(message="报告已删除")

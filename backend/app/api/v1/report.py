from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
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
    title: str | None = None
    template_id: str | None = None
    model: str | None = Field(None, description="指定 LLM 模型（模型名或远程配置 UUID），不传则使用系统默认")


class UpdateReportRequest(BaseModel):
    title: str | None = None
    content: str | None = None


class ReportSection(BaseModel):
    title: str = Field(..., description="章节标题")
    type: str = Field(..., description="章节类型：text/chart/table/kpi")
    content_template: str | None = Field("", description="章节内容指引（text 用作文本生成提示词）")
    order: int | None = Field(0, description="章节排序")
    analysis: str | None = Field(None, description="chart 类型的分析维度：trend/region/age_curve/disease")
    data: str | None = Field(None, description="table 类型的数据表：province/year/age/disease")
    kpi: list[str] | None = Field(None, description="kpi 类型的关键指标键列表")


class ReportTemplateRequest(BaseModel):
    name: str = Field(..., description="模板名称")
    report_type: str = Field("antibody_analysis", description="模板类型：antibody_analysis/vaccination_strategy")
    sections: list[ReportSection] = Field(default_factory=list, description="章节定义数组")
    is_default: bool = Field(False, description="是否默认模板")
    desc: str | None = Field(None, description="模板描述")


@router.post("/reports/generate", response_model=ApiResponse, summary="生成免疫学报告", description="生成免疫学参考意见报告，支持按疾病、省份、数据类型筛选，可选择语言（中文/英文）和自定义标题")
async def generate_report(
    disease: str | None = Query(None, description="疾病 key"),
    province: str | None = Query(None, description="省份筛选"),
    data_type: str | None = Query(None, description="数据类型"),
    language: str = Query("zh", description="报告语言：zh | en"),
    title: str | None = Query(None, description="自定义报告标题"),
    model: str | None = Query(None, description="LLM 模型名，默认使用 .env 配置"),
    template_id: str | None = Query(None, description="报告模板ID，缺省使用抗体分析默认模板"),
):
    """生成免疫学参考意见报告（后台异步：提交即返回，前端轮询 /system/active-tasks 查看进度）"""
    return await _submit_report_task(
        result_task_kind="antibody",
        language=language, disease=disease, province=province, data_type=data_type,
        title=title, model=model, template_id=template_id,
    )


def _submit_report_task(*, result_task_kind: str, language, disease, province, data_type, title, model, template_id):
    """提交报告生成 Celery 任务并立即返回任务 id（kind∈{antibody,barrier}）。"""
    from app.tasks.background_task import run_report_generation

    task = run_report_generation.delay(
        language=language,
        disease=disease,
        province=province,
        data_type=data_type,
        title=title,
        model=model,
        template_id=template_id,
        kind=result_task_kind,
    )
    return ApiResponse(message="报告生成任务已提交", data={"task_id": str(task.id), "status": "queued"})


@router.post("/reports/generate-vaccination-strategy", response_model=ApiResponse, summary="生成疫苗接种策略报告", description="生成疫苗接种任务的策略研判报告，根据任务类型、时间、地点、人员信息生成专业建议")
async def generate_vaccination_strategy(
    req: VaccinationStrategyRequest,
):
    """生成疫苗接种策略研判报告（后台异步：提交即返回）"""
    from app.tasks.background_task import run_vaccination_strategy

    task = run_vaccination_strategy.delay(
        task_type=req.task_type,
        task_time=req.task_time,
        task_location=req.task_location,
        personnel_count=req.personnel_count,
        personnel_gender=req.personnel_gender,
        personnel_age=req.personnel_age,
        personnel_vaccination_history=req.personnel_vaccination_history,
        title=req.title,
        template_id=req.template_id,
        model=req.model,
    )
    return ApiResponse(message="疫苗接种策略报告生成任务已提交", data={"task_id": str(task.id), "status": "queued"})


@router.post("/reports/generate-immune-barrier", response_model=ApiResponse, summary="生成免疫屏障评估报告", description="生成人群免疫屏障评估报告，按疾病/省份/数据类型筛选，评估总体/地区/时间/年龄维度的免疫屏障水平与缺口")
async def generate_immune_barrier(
    disease: str | None = Query(None, description="疾病 key"),
    province: str | None = Query(None, description="省份筛选"),
    data_type: str | None = Query(None, description="数据类型"),
    language: str = Query("zh", description="报告语言：zh | en"),
    title: str | None = Query(None, description="自定义报告标题"),
    model: str | None = Query(None, description="LLM 模型名，默认使用 .env 配置"),
    template_id: str | None = Query(None, description="报告模板ID，缺省使用免疫屏障评估默认模板"),
):
    """生成免疫屏障评估报告（后台异步：提交即返回，前端轮询 /system/active-tasks 查看进度）"""
    return await _submit_report_task(
        result_task_kind="barrier",
        language=language, disease=disease, province=province, data_type=data_type,
        title=title, model=model, template_id=template_id,
    )


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


@router.get("/reports/{report_id}/download", summary="下载报告文件", description="将报告内容下载为 Markdown、Word（.docx）或 PDF 文件，方便离线查看和分享")
async def download_report(
    report_id: str,
    format: str = Query("md", description="导出格式：md（Markdown）| docx（Word）| pdf（PDF）"),
    db: AsyncSession = Depends(get_db),
):
    """下载报告为 Markdown、Word 或 PDF 文件"""
    data = await report_service.get_report_by_id(db=db, report_id=report_id)
    if not data:
        raise HTTPException(status_code=404, detail="报告不存在")

    if format == "pdf":
        content = report_service.report_markdown_to_pdf(data["content"])
        media_type = "application/pdf"
        ext = "pdf"
    elif format == "docx":
        content = report_service.report_markdown_to_docx(data["content"])
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"
    else:
        content = data["content"].encode("utf-8")
        media_type = "text/markdown; charset=utf-8"
        ext = "md"

    encoded_filename = quote(data["title"] + f".{ext}")
    return Response(
        content=content,
        media_type=media_type,
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


# ===================== 报告模板管理 =====================


@router.get("/report/templates", response_model=ApiResponse, summary="列出报告模板", description="列出报告模板，可按类型筛选")
async def list_templates(
    report_type: str | None = Query(None, description="模板类型：antibody_analysis/vaccination_strategy"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """列出报告模板"""
    data = await report_service.list_templates(db, report_type=report_type)
    return ApiResponse(message="操作成功", data=data)


@router.post("/report/templates", response_model=ApiResponse, summary="创建报告模板", description="创建自定义报告模板（管理员）")
async def create_template(
    req: ReportTemplateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """创建报告模板"""
    try:
        sections = [s.model_dump(exclude_none=True) for s in req.sections]
        data = await report_service.create_template(
            db,
            name=req.name,
            report_type=req.report_type,
            sections=sections,
            is_default=req.is_default,
            desc=req.desc,
        )
        return ApiResponse(message="模板创建成功", data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/report/templates/{template_id}", response_model=ApiResponse, summary="更新报告模板", description="更新报告模板的内容与章节（管理员）")
async def update_template(
    template_id: str,
    req: ReportTemplateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """更新报告模板"""
    try:
        sections = [s.model_dump(exclude_none=True) for s in req.sections]
        data = await report_service.update_template(
            db,
            template_id=template_id,
            name=req.name,
            sections=sections,
            is_default=req.is_default,
            desc=req.desc,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not data:
        raise HTTPException(status_code=404, detail="模板不存在")
    return ApiResponse(message="模板已更新", data=data)


@router.delete("/report/templates/{template_id}", response_model=ApiResponse, summary="删除报告模板", description="删除报告模板（管理员）")
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """删除报告模板"""
    deleted = await report_service.delete_template(db, template_id=template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="模板不存在")
    return ApiResponse(message="模板已删除")

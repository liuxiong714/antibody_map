import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiResponse
from app.schemas.analysis import EquityAnalysisResponse
from app.services import analysis_service

router = APIRouter()


@router.get("/analysis/trend", response_model=ApiResponse, summary="逐年趋势分析", description="获取抗体水平的逐年趋势分析数据，支持按疾病、省份、年份范围、年龄、数据类型筛选")
async def get_trend(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    db: AsyncSession = Depends(get_db),
):
    """逐年趋势分析"""
    data = await analysis_service.get_trend(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
        data_type=data_type,
    )
    return ApiResponse(data=data)


@router.get("/analysis/region-compare", response_model=ApiResponse, summary="区域对比分析", description="获取不同区域之间的抗体水平对比分析数据，支持按疾病、省份、年份范围、年龄、数据类型筛选")
async def get_region_compare(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    db: AsyncSession = Depends(get_db),
):
    """区域对比分析"""
    data = await analysis_service.get_region_compare(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
        data_type=data_type,
    )
    return ApiResponse(data=data)


@router.get("/analysis/equity", response_model=ApiResponse, summary="省间公平性分析", description="以省为粒度分析抗体水平公平性：省间基尼系数、变异系数、最佳/最差省、达标比例（对比 WHO 阈值）、Top/Bottom 排名")
async def get_equity(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    db: AsyncSession = Depends(get_db),
):
    """省间公平性分析（设计 B）"""
    data = await analysis_service.get_equity_analysis(
        db=db,
        disease=disease,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
    )
    # 用 Pydantic schema 校验并序列化，保持 ApiResponse 统一结构
    validated = EquityAnalysisResponse.model_validate(data).model_dump()
    return ApiResponse(data=validated)


@router.get("/analysis/quality", response_model=ApiResponse, summary="数据质量评估", description="评估已审核主估计的数据质量：高质量(A/B)占比、带CI比例、原文溯源(grounded)比例、单点估计省份预警（基于 reliability_grade 分级）")
async def get_quality(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    db: AsyncSession = Depends(get_db),
):
    """数据质量评估"""
    data = await analysis_service.get_quality_assessment(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
    )
    return ApiResponse(data=data)


@router.get("/analysis/goal-tracking", response_model=ApiResponse, summary="目标达成追踪", description="按年追踪全国抗体保护达标进度：达标省比例、全国加权阳性率、相对每病保护目标(GOAL_THRESHOLDS/HIT)的缺口百分点")
async def get_goal_tracking(
    disease: Optional[str] = Query(None, description="疾病筛选（用于匹配 GOAL_THRESHOLDS 保护目标阈值）"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    db: AsyncSession = Depends(get_db),
):
    """目标达成追踪"""
    data = await analysis_service.get_goal_tracking(
        db=db,
        disease=disease,
        year_start=year_start,
        year_end=year_end,
    )
    return ApiResponse(data=data)


@router.get("/analysis/age-curve", response_model=ApiResponse, summary="年龄-抗体曲线", description="以年龄组中点为 x 绘制 seroprevalence/gmc 随年龄变化曲线（LOWESS 平滑），并定位拐点")
async def get_age_curve(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    metric: str = Query("seroprevalence", pattern="^(seroprevalence|gmc)$", description="指标：seroprevalence=阳性率，gmc=几何均数"),
    db: AsyncSession = Depends(get_db),
):
    """年龄-抗体曲线（LOWESS 平滑 + 拐点）"""
    data = await analysis_service.get_age_curve(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        metric=metric,
    )
    return ApiResponse(data=data)


@router.get("/analysis/meta-merge", response_model=ApiResponse, summary="同省多研究 meta 合并", description="按省份对同病多研究做逆方差加权合并（固定/随机效应），输出 I² 异质性、Q 统计量、τ²")
async def get_meta_merge(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选（不传则按省分组）"),
    db: AsyncSession = Depends(get_db),
):
    """同省同病多研究 meta 合并 + I²"""
    data = await analysis_service.get_meta_merge(
        db=db,
        disease=disease,
        province=province,
    )
    return ApiResponse(data=data)


@router.get("/analysis/assay-heterogeneity", response_model=ApiResponse, summary="检测方法(assay)异质性", description="按 assay 分层对比各检测方法的加权阳性率与95%CI，并计算跨 assay 的 I² 异质性")
async def get_assay_heterogeneity(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    db: AsyncSession = Depends(get_db),
):
    """按 assay 分层的异质性对比"""
    data = await analysis_service.get_assay_heterogeneity(
        db=db,
        disease=disease,
        province=province,
    )
    return ApiResponse(data=data)


@router.get("/analysis/simulate", response_model=ApiResponse, summary="免疫屏障模拟", description="复用 FOI 催化模型反推 R0/HIT，结合假设接种覆盖与加强针比例模拟有效免疫比例，判定屏障状态并反推达标所需覆盖")
async def get_simulation(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    assumed_coverage: float = Query(90.0, ge=0, le=100, description="假设基础接种覆盖率(%)"),
    booster_rate: float = Query(0.0, ge=0, le=100, description="加强针比例(%)，作用于尚未免疫者"),
    db: AsyncSession = Depends(get_db),
):
    """免疫屏障模拟（FOI 反推 + 接种情景）"""
    data = await analysis_service.get_simulation(
        db=db,
        disease=disease,
        province=province,
        assumed_coverage=assumed_coverage,
        booster_rate=booster_rate,
    )
    return ApiResponse(data=data)


@router.get("/analysis/age-stratify", response_model=ApiResponse, summary="年龄分层分析", description="获取按年龄分层的抗体水平分析数据，支持按疾病、省份、年份范围、年龄范围、数据类型筛选")
async def get_age_stratify(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    db: AsyncSession = Depends(get_db),
):
    """年龄分层分析"""
    data = await analysis_service.get_age_stratify(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
        data_type=data_type,
    )
    return ApiResponse(data=data)


@router.get("/analysis/summary", response_model=ApiResponse, summary="汇总统计", description="获取抗体数据的汇总统计信息，包括总数据点数、覆盖省份数、发表文献数等")
async def get_summary(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    db: AsyncSession = Depends(get_db),
):
    """汇总统计"""
    data = await analysis_service.get_summary(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
        data_type=data_type,
    )
    return ApiResponse(data=data)


@router.get("/analysis/immune-barrier", response_model=ApiResponse, summary="免疫屏障评估", description="评估免疫屏障状态，分析各省份各年龄组的抗体保护水平，判断免疫缺口")
async def get_immune_barrier(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    db: AsyncSession = Depends(get_db),
):
    """免疫屏障评估"""
    data = await analysis_service.get_immune_barrier_assessment(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
    )
    return ApiResponse(data=data)


@router.get("/analysis/approved-data-points", response_model=ApiResponse, summary="获取审核通过的数据点", description="分页获取所有审核通过的数据点，用于数据分析模块，支持多维度筛选和排序")
async def get_approved_data_points(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(200, ge=1, le=1000, description="每页数量"),
    sort_by: Optional[str] = Query(None, description="排序字段"),
    sort_order: Optional[str] = Query("desc", description="排序方向 asc/desc"),
    db: AsyncSession = Depends(get_db),
):
    """获取所有审核通过的数据点（分页），用于数据分析模块"""
    items, total = await analysis_service.get_approved_data_points(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
        data_type=data_type,
        offset=offset,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return ApiResponse(data={"items": items, "total": total})


@router.get("/analysis/data-gaps", response_model=ApiResponse, summary="数据覆盖度分析", description="分析各省份各年份的数据点分布，识别需要审核和补充的数据缺口，支持按疾病筛选")
async def get_data_gaps(
    disease: Optional[str] = Query(None, description="疾病筛选（不传则分析全库）"),
    db: AsyncSession = Depends(get_db),
):
    """数据覆盖度分析：统计各省份各年份的数据点分布，识别需要审核和补充的数据缺口"""
    data = await analysis_service.get_data_gap_analysis(
        db=db,
        disease=disease,
    )
    return ApiResponse(data=data)


@router.get("/analysis/coverage-review", response_model=ApiResponse, summary="审核状态统计", description="按疾病维度统计数据点数、样本量、审核状态(approved/pending/rejected)与通过率，默认按待审核数降序排序")
async def get_coverage_review(
    disease: Optional[str] = Query(None, description="疾病筛选（不传则统计全部疾病）"),
    db: AsyncSession = Depends(get_db),
):
    """按疾病维度的审核状态统计（数据点/样本量/通过率）"""
    data = await analysis_service.get_coverage_review_stats(
        db=db,
        disease=disease,
    )
    return ApiResponse(data=data)


@router.get("/analysis/export", summary="导出分析数据Excel", description="将所有分析结果导出为Excel文件，包含多个sheet：汇总统计、年份趋势、区域对比、年龄分层、数据点明细、统计方法附录（加权率/GMC/95%CI/基尼/meta合并等算法公式）")
async def export_analysis(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    db: AsyncSession = Depends(get_db),
):
    """导出分析数据为 Excel 多 sheet"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    # 并行获取所有分析数据
    import asyncio
    trend_data, region_data, age_data, summary_data, approved_result = await asyncio.gather(
        analysis_service.get_trend(db=db, disease=disease, province=province,
                                    year_start=year_start, year_end=year_end,
                                    age_min=age_min, age_max=age_max, data_type=data_type),
        analysis_service.get_region_compare(db=db, disease=disease, province=province,
                                             year_start=year_start, year_end=year_end,
                                             age_min=age_min, age_max=age_max, data_type=data_type),
        analysis_service.get_age_stratify(db=db, disease=disease, province=province,
                                           year_start=year_start, year_end=year_end,
                                           age_min=age_min, age_max=age_max, data_type=data_type),
        analysis_service.get_summary(db=db, disease=disease, province=province,
                                      year_start=year_start, year_end=year_end,
                                      age_min=age_min, age_max=age_max, data_type=data_type),
        analysis_service.get_approved_data_points(db=db, disease=disease, province=province,
                                                   year_start=year_start, year_end=year_end,
                                                   age_min=age_min, age_max=age_max,
                                                   data_type=data_type, offset=0, limit=10000),
    )
    approved_items, _ = approved_result

    wb = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")

    def _write_header(ws, headers):
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

    def _write_rows(ws, rows, start_row=2):
        for r_idx, row in enumerate(rows, start_row):
            for c_idx, val in enumerate(row, 1):
                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                if isinstance(val, (int, float)):
                    cell.alignment = Alignment(horizontal="center")

    # Sheet 1: 汇总统计
    ws_summary = wb.active
    ws_summary.title = "汇总统计"
    _write_header(ws_summary, ["指标", "数值"])
    s = summary_data if isinstance(summary_data, dict) else {}
    _write_rows(ws_summary, [[k, v] for k, v in s.items()])
    for col in range(1, 3):
        ws_summary.column_dimensions[chr(64 + col)].width = 25

    # Sheet 2: 年份趋势（get_trend 返回 {"trend": [...], "trend_significance": {...}}）
    trend_rows = trend_data.get("trend", []) if isinstance(trend_data, dict) else (trend_data or [])
    if trend_rows:
        ws_trend = wb.create_sheet("年份趋势")
        trend_keys = list(trend_rows[0].keys()) if isinstance(trend_rows[0], dict) else []
        _write_header(ws_trend, trend_keys)
        for i, row in enumerate(trend_rows, 2):
            if isinstance(row, dict):
                for j, k in enumerate(trend_keys, 1):
                    ws_trend.cell(row=i, column=j, value=row.get(k))
        for col_idx in range(1, len(trend_keys) + 1):
            ws_trend.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = 18

    # Sheet 3: 区域对比
    if region_data:
        ws_region = wb.create_sheet("区域对比")
        region_keys = list(region_data[0].keys()) if isinstance(region_data[0], dict) else []
        _write_header(ws_region, region_keys)
        for i, row in enumerate(region_data, 2):
            if isinstance(row, dict):
                for j, k in enumerate(region_keys, 1):
                    ws_region.cell(row=i, column=j, value=row.get(k))
        for col_idx in range(1, len(region_keys) + 1):
            ws_region.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = 18

    # Sheet 4: 年龄分层
    if age_data:
        ws_age = wb.create_sheet("年龄分层")
        age_keys = list(age_data[0].keys()) if isinstance(age_data[0], dict) else []
        _write_header(ws_age, age_keys)
        for i, row in enumerate(age_data, 2):
            if isinstance(row, dict):
                for j, k in enumerate(age_keys, 1):
                    ws_age.cell(row=i, column=j, value=row.get(k))
        for col_idx in range(1, len(age_keys) + 1):
            ws_age.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = 18

    # Sheet 5: 数据点明细
    if approved_items:
        ws_dp = wb.create_sheet("数据点明细")
        dp_fields = [
            "literature_title", "disease", "province", "city", "age_group",
            "sample_size", "data_type", "value", "unit", "ci_lower", "ci_upper",
            "collection_year", "method", "population", "confidence",
        ]
        dp_headers = [
            "文献标题", "疾病", "省份", "城市", "年龄组", "样本量", "数据类型",
            "数值", "单位", "CI下限", "CI上限", "采集年份", "检测方法", "人群", "置信度",
        ]
        _write_header(ws_dp, dp_headers)
        for i, item in enumerate(approved_items, 2):
            if isinstance(item, dict):
                for j, field in enumerate(dp_fields, 1):
                    ws_dp.cell(row=i, column=j, value=item.get(field))
        for col_idx in range(1, len(dp_headers) + 1):
            ws_dp.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = 18

    # Sheet 6: 统计方法附录（算法与公式说明）
    ws_methods = wb.create_sheet("统计方法附录")
    _write_header(ws_methods, ["统计方法", "公式", "说明"])
    wrap_align = Alignment(vertical="top", wrap_text=True)
    appendix_rows = [
        (
            "加权阳性率（逆方差加权合并）",
            "w_i = n_i / (p_i·(1-p_i))\npooled = Σ(w_i·p_i) / Σw_i",
            "p_i = 研究阳性率（0-1，>1 视为百分数除以 100）；n_i = 样本量。"
            "p=0 或 1 的边界研究采用连续性校正（x'=x+0.5，n'=n+1）避免方差为 0 / 权重无穷大。"
            "输出为百分比（×100）。",
        ),
        (
            "95% 置信区间（Wilson score）",
            "center = (p + z²/2n) / (1 + z²/n)\n"
            "half = z·√(p(1-p)/n + z²/4n²) / (1 + z²/n)\n"
            "CI = [max(0, center-half), min(1, center+half)]",
            "z = 1.96（95% 置信水平）；n 取合并总样本量。用于合并阳性率的区间估计。",
        ),
        (
            "GMC 几何均数 + 对数域 t 分布 CI",
            "GMC = exp( mean(ln v_i) )\nSE = SD(ln v) / √n\n"
            "CI = exp( mean(ln v) ± t(n-1)·SE )",
            "仅对正数计算，缺失 / 非正值剔除。t 临界值查表（df>30 用 z=1.96 近似）。"
            "几何均数适用于抗体滴度等对数正态分布数据。",
        ),
        (
            "基尼系数（省间公平性）",
            "G = 2·Σ(i+1)·x_i / (n·Σx_i) - (n+1)/n",
            "对排序后的非负序列计算（i 从 0 起）。G=0 完全均等，G=1 完全不均等。"
            "用于评估各省加权阳性率的离散程度。",
        ),
        (
            "变异系数",
            "CV = 样本标准差 / |均值|",
            "无量纲比值，衡量省际阳性率相对离散程度。样本数 < 2 或均值为 0 时无法计算，返回 0。",
        ),
        (
            "Meta 合并（逆方差 固定/随机效应 + I²）",
            "var_i = ((CI_upper - CI_lower) / (2·1.96))²\n"
            "固定: pooled = Σ(w_i·p_i)/Σw_i，w_i = 1/var_i\n"
            "Q = Σ w_i·(p_i - pooled)²，df = k-1\n"
            "I² = max(0, (Q - df)/Q)·100%\n"
            "随机(D-L): τ² = max(0,(Q-df)/(Σw-Σw²/Σw))，w*_i = 1/(var_i+τ²)",
            "CI 缺失时退化为二项方差 p(1-p)/n（p=0/1 连续性校正）。"
            "异质性解读：I²<25% 低、25%-50% 中、>50% 高。",
        ),
        (
            "LOWESS 平滑（年龄曲线）",
            "k = max(2, ceil(frac·n))\nw = (1 - u³)³（tricube 核，u=距离/最大距离）",
            "对每个年龄点取最近 k 个邻居做局部加权线性拟合。"
            "用于生成年龄-阳性率 / 年龄-GMC 平滑曲线。",
        ),
        (
            "加权线性趋势（显著性）",
            "y = a + b·x；b = Sxy/Sxx\nR² = 1 - SS_res/SS_tot；p 值 = 斜率 t 检验",
            "权重取各年总样本量。趋势方向：斜率 >0 上升、<0 下降、≈0 平稳。",
        ),
        (
            "证据可靠性分级 A/B/C/D",
            "score = 样本量分 + CI分 + 置信度分 + 溯源分 + 研究数分",
            "样本量 ≥1000:+4 / ≥300:+3 / ≥100:+2 / ≥30:+1；带CI:+2；置信度 high:+2 / medium:+1；"
            "原文溯源:+2；研究数 ≥5:+2 / ≥2:+1。总分 ≥9→A、≥6→B、≥3→C、<3→D。",
        ),
        (
            "FOI 催化模型（免疫屏障模拟）",
            "λ = -ln(1-SP) / age\nR0 ≈ λ·L（L=期望寿命 75 年）\nHIT = (1 - 1/R0)·100%",
            "SP=观测血清阳性率（0-1），age=年龄组中点。模拟有效免疫比例 "
            "effective = 覆盖 + (1-覆盖)·加强针比例，与 HIT 对比判定屏障状态并反推达标所需覆盖。",
        ),
    ]
    for r_idx, (method, formula, note) in enumerate(appendix_rows, 2):
        ws_methods.cell(row=r_idx, column=1, value=method).alignment = wrap_align
        ws_methods.cell(row=r_idx, column=2, value=formula).alignment = wrap_align
        ws_methods.cell(row=r_idx, column=3, value=note).alignment = wrap_align
        ws_methods.row_dimensions[r_idx].height = 80
    ws_methods.column_dimensions["A"].width = 28
    ws_methods.column_dimensions["B"].width = 46
    ws_methods.column_dimensions["C"].width = 60

    # 输出到字节流
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''analysis_export.xlsx"},
    )


@router.get("/analysis/dataset-snapshot", summary="导出数据集快照ZIP", description="P2-1：导出公开数据集快照ZIP包，包含CSV数据文件、数据字典、README和LICENSE")
async def export_dataset_snapshot(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    db: AsyncSession = Depends(get_db),
):
    """P2-1：导出公开数据集快照 ZIP（CSV + 数据字典 + README + LICENSE）"""
    from urllib.parse import quote
    from app.core.dataset_snapshot import generate_dataset_snapshot_zip

    data_points = await analysis_service.get_approved_data_points_for_snapshot(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
        data_type=data_type,
    )

    filters = {
        "disease": disease,
        "province": province,
        "year_start": year_start,
        "year_end": year_end,
        "age_min": age_min,
        "age_max": age_max,
        "data_type": data_type,
    }

    zip_bytes = generate_dataset_snapshot_zip(data_points, filters=filters)

    filename = quote("antibody_dataset_snapshot.zip")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/analysis/foi-herd-immunity", response_model=ApiResponse, summary="FOI和群体免疫分析", description="P0：使用催化模型计算感染力（FOI）和群体免疫阈值，输出按省份×疾病的FOI热力矩阵与群体免疫状态")
async def get_foi_herd_immunity(
    disease: Optional[str] = Query(None, description="疾病筛选（不传则全库分析）"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    db: AsyncSession = Depends(get_db),
):
    """P0: FOI（感染力）+ 群体免疫阈值综合分析。

    纯分析逻辑（无 DB 变更）：
    - 用催化模型 λ = -ln(1-SP)/age 估算各年龄组 FOI
    - 反推 R0 ≈ λ·L（L 取默认 75 年）
    - 计算 HIT = 1 - 1/R0，并与 WHO 阈值对比
    - 按省份 × 疾病输出 FOI 热力矩阵与群体免疫状态
    """
    data = await analysis_service.get_foi_analysis(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
    )
    return ApiResponse(data=data)


@router.get("/analysis/vaccine-effectiveness-coverage", response_model=ApiResponse, summary="疫苗效果和接种率分析", description="P1：分析疫苗效果（VE）和接种覆盖率，计算VE，返回省×疾病覆盖率矩阵，判断接种进度是否达标")
async def get_vaccine_ve_coverage(
    disease: Optional[str] = Query(None, description="疾病筛选（不传则全库分析）"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    db: AsyncSession = Depends(get_db),
):
    """P1: 疫苗效果 (VE / Vaccine Effectiveness) + 接种率综合分析。

    - 尝试根据 DataPoint.population 中的「已接种/未接种」标签拆分亚组，
      计算 VE(against infection) = 1 - SP_vax / SP_unvax
    - 若未找到接种亚组，返回参考接种率（NIP 预设表）与从整体 SP 反推的隐含接种率
    - 返回省 × 疾病覆盖率矩阵（on_track / near / below）
    """
    data = await analysis_service.get_vaccine_analysis(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
    )
    return ApiResponse(data=data)
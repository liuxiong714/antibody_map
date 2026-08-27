import io
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiResponse
from app.schemas.analysis import EquityAnalysisResponse
from app.services import analysis_service
from app.services.analysis.export import build_excel_export
from app.core.methodology import build_methodology_note
from app.models.data_point import DataPoint
from app.tasks.quality_task import score_data_point_task
from app.services.snapshot_service import with_snapshot

router = APIRouter()

# build_methodology_note 需要的事实键（从响应 meta / 嵌套容器中提取）
_ANALYSIS_FACT_KEYS = (
    "n_estimates", "n_literatures", "quality_grades", "model", "I2", "ci_method",
    "test", "catalytic_model", "catalytic_mu", "standard_population",
    "assumptions", "snapshot_date",
)


def _collect_analysis_facts(data: dict) -> dict:
    """从分析响应中尽量收集事实性统计信息，供 build_methodology_note 使用。

    顶层 ``meta`` 优先；其次探测常见容器（groups/regions/per_disease_results 等）
    首项内的 ``meta`` 或其 ``pooled``（meta_proportion 输出）；再取顶层 ``assumptions``。
    """
    facts: dict = {}
    meta = data.get("meta")
    if isinstance(meta, dict):
        facts.update(meta)

    for key in ("groups", "items", "regions", "provinces", "series", "age_groups",
                "per_disease_results", "diseases"):
        container = data.get(key)
        if not isinstance(container, list) or not container:
            continue
        item = container[0]
        if not isinstance(item, dict):
            continue
        im = item.get("meta")
        if isinstance(im, dict):
            for fk in _ANALYSIS_FACT_KEYS:
                if fk not in facts and im.get(fk) is not None:
                    facts[fk] = im[fk]
            pooled = im.get("pooled")
            if isinstance(pooled, dict):
                for fk in ("model", "I2", "ci_method"):
                    if fk not in facts and pooled.get(fk) is not None:
                        facts[fk] = pooled[fk]
        s = item.get("summary")
        if isinstance(s, dict):
            for fk in ("n_estimates", "n_literatures", "catalytic_model"):
                if fk not in facts and s.get(fk) is not None:
                    facts[fk] = s[fk]
        break  # 只需首项

    assumptions = data.get("assumptions")
    if isinstance(assumptions, dict) and assumptions:
        facts["assumptions"] = assumptions
    return facts


def _attach_methodology_note(data, module: str, params: dict) -> dict:
    """把方法学脚注挂到分析响应的 meta.methodology_note（响应无 meta 则创建）。"""
    if not isinstance(data, dict):
        return data
    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta
    if "methodology_note" not in meta:
        facts = _collect_analysis_facts(data)
        meta["methodology_note"] = build_methodology_note(module, params, facts)
    return data


@router.get("/analysis/trend", response_model=ApiResponse, summary="逐年趋势分析", description="获取抗体水平的逐年趋势分析数据，支持按疾病、省份、年份范围、年龄、数据类型筛选")
@with_snapshot("trend")
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
    return ApiResponse(data=_attach_methodology_note(
        data, "trend",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end},
    ))


@router.get("/analysis/region-compare", response_model=ApiResponse, summary="区域对比分析", description="获取不同区域之间的抗体水平对比分析数据，支持按疾病、省份、年份范围、年龄、数据类型筛选")
@with_snapshot("region_compare")
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
    return ApiResponse(data=_attach_methodology_note(
        data, "region_compare",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end},
    ))


@router.get("/analysis/equity", response_model=ApiResponse, summary="省间公平性分析", description="以省为粒度分析抗体水平公平性：省间基尼系数、变异系数、最佳/最差省、达标比例（对比 WHO 阈值）、Top/Bottom 排名")
@with_snapshot("equity", filter_keys=("disease", "year_start", "year_end", "age_min", "age_max"),
               data_type_override="seroprevalence")
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
    validated = _attach_methodology_note(
        validated, "equity",
        {"disease": disease, "year_start": year_start, "year_end": year_end},
    )
    return ApiResponse(data=validated)


@router.get("/analysis/quality", response_model=ApiResponse, summary="数据质量评估", description="评估已审核主估计的数据质量：高质量(A/B)占比、带CI比例、原文溯源(grounded)比例、单点估计省份预警（基于 reliability_grade 分级）")
@with_snapshot("quality", filter_keys=("disease", "province", "year_start", "year_end"))
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
    return ApiResponse(data=_attach_methodology_note(
        data, "quality",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end},
    ))


# 全量质量重算的限流：两次重算间隔至少 RESCORE_MIN_INTERVAL 秒
_RESCORE_MIN_INTERVAL = 60.0
_last_rescore_at: float = 0.0


class RescoreRequest(BaseModel):
    limit: int = 200  # 小批量：单次最多提交的任务数（1-500）
    only_unscored: bool = True  # 默认只重算未打分的；False 则全量重算


@router.post("/analysis/quality/rescore", response_model=ApiResponse, summary="数据点质量全量重算", description="批量提交数据点质量打分任务（限速小批量，默认仅重算未打分数据点，可放开全量）")
async def rescore_quality(
    req: RescoreRequest,
    db: AsyncSession = Depends(get_db),
):
    """质量全量重算：分页取数据点并提交异步打分任务。"""
    global _last_rescore_at

    limit = max(1, min(req.limit, 500))
    now = time.monotonic()
    if now - _last_rescore_at < _RESCORE_MIN_INTERVAL:
        raise HTTPException(
            status_code=429,
            detail=f"重算过于频繁，请稍后再试（{int(_RESCORE_MIN_INTERVAL)} 秒内仅允许一次）",
        )

    query = select(DataPoint.id).where(DataPoint.review_status == "approved")
    if req.only_unscored:
        query = query.where(DataPoint.quality_score.is_(None))
    query = query.order_by(DataPoint.updated_at.asc()).limit(limit)
    result = await db.execute(query)
    ids = result.scalars().all()

    for dp_id in ids:
        score_data_point_task.delay(str(dp_id))

    _last_rescore_at = now
    return ApiResponse(
        message=f"已提交 {len(ids)} 个数据点质量重算任务",
        data={"submitted": len(ids), "limit": limit, "only_unscored": req.only_unscored},
    )


@router.get("/analysis/goal-tracking", response_model=ApiResponse, summary="目标达成追踪", description="按年追踪全国抗体保护达标进度：达标省比例、全国加权阳性率、相对每病保护目标(GOAL_THRESHOLDS/HIT)的缺口百分点")
@with_snapshot("goal_tracking", filter_keys=("disease", "year_start", "year_end"))
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
    return ApiResponse(data=_attach_methodology_note(
        data, "goal_tracking",
        {"disease": disease, "year_start": year_start, "year_end": year_end},
    ))


@router.get("/analysis/age-curve", response_model=ApiResponse, summary="血清阳性率-年龄曲线", description="惩罚样条平滑 P(a) 曲线 + 95% 置信带 + 年龄别 FOI 曲线。数据点 < 8 时返回 422。")
@with_snapshot("age_curve", filter_keys=("disease", "province", "year_start", "year_end"))
async def get_age_curve(
    disease: str = Query(..., description="疾病筛选（必填）"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    db: AsyncSession = Depends(get_db),
):
    """血清阳性率-年龄曲线（惩罚样条平滑 + 置信带 + FOI）"""
    data = await analysis_service.get_age_curve(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
    )
    if data["n_points"] < 8:
        raise HTTPException(
            status_code=422,
            detail=f"数据点不足以拟合年龄曲线（需≥8，当前{data['n_points']}个）",
        )
    return ApiResponse(data=_attach_methodology_note(
        data, "age_curve",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end},
    ))


@router.get("/analysis/birth-cohort", response_model=ApiResponse, summary="出生队列分析", description="birth_year = collection_year − age_mid，聚合 (出生十年段, 调查年) → 加权阳性率 + 95%CI，揭示代际免疫差异。麻疹/风疹附计划免疫史解读提示。")
@with_snapshot("birth_cohort", filter_keys=("disease", "province", "year_start", "year_end"))
async def get_birth_cohort(
    disease: str = Query(..., description="疾病筛选（必填）"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    db: AsyncSession = Depends(get_db),
):
    """出生队列分析（heatmap + 队列轨迹线）"""
    data = await analysis_service.get_birth_cohort(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "birth_cohort",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end},
    ))


@router.get("/analysis/meta-merge", response_model=ApiResponse, summary="同省多研究 meta 合并", description="按省份对同病多研究做逆方差加权合并（固定/随机效应），输出 I² 异质性、Q 统计量、τ²。默认仅纳入质量 A+B 级数据点")
@with_snapshot("meta_merge", filter_keys=("disease", "province"),
               data_type_override="seroprevalence", quality_filter_key="include_low_quality")
async def get_meta_merge(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选（不传则按省分组）"),
    include_low_quality: bool = Query(False, description="是否放开质量过滤（默认仅 A+B 级）"),
    db: AsyncSession = Depends(get_db),
):
    """同省同病多研究 meta 合并 + I²"""
    data = await analysis_service.get_meta_merge(
        db=db,
        disease=disease,
        province=province,
        include_low_quality=include_low_quality,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "meta_merge",
        {"disease": disease, "province": province, "include_low_quality": include_low_quality},
    ))


@router.get("/analysis/meta-analysis", response_model=ApiResponse, summary="多文献 Meta 分析", description="多文献血清阳性率随机效应 Meta 合并（Freeman-Tukey 双反正弦变换）。不指定 group_by 时把过滤集内每个文献主估计作为研究单元合并；指定 group_by（province/year/age_group 逗号分隔）时按组分别合并并附 Q_between 亚组异质性检验。默认仅纳入质量 A+B 级数据点")
@with_snapshot("meta_analysis",
               filter_keys=("disease", "province", "year_start", "year_end", "age_min", "age_max"),
               data_type_override="seroprevalence", quality_filter_key="include_low_quality")
async def get_meta_analysis(
    disease: str = Query(..., description="疾病筛选（必填）"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    group_by: Optional[str] = Query(None, description="分组字段，逗号分隔：province / year / age_group"),
    include_low_quality: bool = Query(False, description="是否放开质量过滤（默认仅 A+B 级）"),
    db: AsyncSession = Depends(get_db),
):
    """多文献血清阳性率随机效应 Meta 分析（Freeman-Tukey 变换 + 模型选择）"""
    data = await analysis_service.get_meta_analysis(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        age_min=age_min,
        age_max=age_max,
        group_by=group_by,
        include_low_quality=include_low_quality,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "meta_analysis",
        {"disease": disease, "province": province, "year_start": year_start,
         "year_end": year_end, "age_min": age_min, "age_max": age_max, "group_by": group_by},
    ))


@router.get("/analysis/spatial-hotspots", response_model=ApiResponse, summary="省级空间热点/冷点分析", description="基于省级加权阳性率计算 Moran's I 全局自相关与 Getis-Ord Gi* 局部热点/冷点（hot_99/hot_95/hot_90/cold_*/ns）。有数据省份 < 8 时返回 422。")
@with_snapshot("spatial_hotspots", filter_keys=("disease", "year_start", "year_end"))
async def get_spatial_hotspots(
    disease: str = Query(..., description="疾病筛选（必填）"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    level: str = Query("province", description="空间级别（当前仅支持 province，city 预留）"),
    db: AsyncSession = Depends(get_db),
):
    """省级空间热点/冷点分析（Moran's I + Getis-Ord Gi*）"""
    if level != "province":
        raise HTTPException(
            status_code=400,
            detail=f"level={level} 暂不支持，当前仅支持 province（city 预留）",
        )
    data = await analysis_service.get_spatial_hotspots(
        db=db,
        disease=disease,
        year_start=year_start,
        year_end=year_end,
        level=level,
    )
    if (data.get("n_valid") or 0) < 8:
        raise HTTPException(
            status_code=422,
            detail=f"有效数据省份不足，无法进行空间统计（需≥8，当前{data.get('n_valid', 0)}个）",
        )
    return ApiResponse(data=_attach_methodology_note(
        data, "spatial_hotspots",
        {"disease": disease, "year_start": year_start, "year_end": year_end, "level": level},
    ))


@router.get("/analysis/assay-heterogeneity", response_model=ApiResponse, summary="检测方法(assay)异质性", description="按 assay 分层对比各检测方法的加权阳性率与95%CI，并计算跨 assay 的 I² 异质性")
@with_snapshot("assay_heterogeneity", filter_keys=("disease", "province"))
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
    return ApiResponse(data=_attach_methodology_note(
        data, "assay_heterogeneity",
        {"disease": disease, "province": province},
    ))


@router.get("/analysis/simulate", response_model=ApiResponse, summary="免疫屏障模拟", description="复用 FOI 催化模型反推 R0/HIT，结合假设接种覆盖与加强针比例模拟有效免疫比例，判定屏障状态并反推达标所需覆盖")
@with_snapshot("simulate", filter_keys=("disease", "province"))
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
    return ApiResponse(data=_attach_methodology_note(
        data, "simulate",
        {"disease": disease, "province": province,
         "assumed_coverage": assumed_coverage, "booster_rate": booster_rate},
    ))


@router.get("/analysis/age-stratify", response_model=ApiResponse, summary="年龄分层分析", description="获取按年龄分层的抗体水平分析数据，支持按疾病、省份、年份范围、年龄范围、数据类型筛选")
@with_snapshot("age_stratify")
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
    return ApiResponse(data=_attach_methodology_note(
        data, "age_stratify",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end},
    ))


@router.get("/analysis/summary", response_model=ApiResponse, summary="汇总统计", description="获取抗体数据的汇总统计信息，包括总数据点数、覆盖省份数、发表文献数等")
@with_snapshot("summary")
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
    return ApiResponse(data=_attach_methodology_note(
        data, "summary",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end},
    ))


@router.get("/analysis/immune-barrier", response_model=ApiResponse, summary="免疫屏障评估", description="评估免疫屏障状态，分析各省份各年龄组的抗体保护水平，判断免疫缺口")
@with_snapshot("immune_barrier")
async def get_immune_barrier(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    age_min: Optional[int] = Query(None, description="最小年龄"),
    age_max: Optional[int] = Query(None, description="最大年龄"),
    life_expectancy: float = Query(75.0, ge=50, le=100, description="期望寿命（年），默认75"),
    seroreversion_mu: Optional[float] = Query(None, ge=0, le=0.2, description="血清转阴率 μ（0/0.01/0.02，留空则按数据估计）"),
    hit_source_override: Optional[str] = Query(None, pattern="^(who|literature|foi)$", description="HIT 阈值来源覆盖（who|literature|foi）"),
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
        life_expectancy=life_expectancy,
        seroreversion_mu=seroreversion_mu,
        hit_source_override=hit_source_override,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "immune_barrier",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end,
         "life_expectancy": life_expectancy, "seroreversion_mu": seroreversion_mu,
         "hit_source_override": hit_source_override},
    ))


@router.get("/analysis/immunity-projection", response_model=ApiResponse, summary="免疫屏障动态预测", description="基于抗体衰减 + 新出生队列，预测某省某病种未来若干年的有效免疫屏障轨迹，并给出屏障首次跌破安全阈值（默认0.92）的年份。")
@with_snapshot("immunity_projection", filter_keys=("disease", "province"))
async def get_immunity_projection(
    disease: str = Query(..., description="疾病筛选（必填）"),
    province: Optional[str] = Query(None, description="省份筛选"),
    waning_rate: Optional[float] = Query(None, ge=0, le=0.5, description="每年抗体转阴比例（0~0.5，留空则从多年份实测数据自动估计）"),
    projection_years: int = Query(10, ge=1, le=50, description="预测年数（默认10）"),
    birth_cohort_size: float = Query(0.012, ge=0, le=0.5, description="每年新出生零保护人口占比（默认0.012）"),
    barrier_threshold: float = Query(0.92, gt=0, le=1, description="屏障安全阈值（默认0.92，跌破则预警）"),
    db: AsyncSession = Depends(get_db),
):
    """免疫屏障动态预测（抗体衰减 + 新出生队列）"""
    data = await analysis_service.get_immunity_projection(
        db=db,
        disease=disease,
        province=province,
        waning_rate=waning_rate,
        projection_years=projection_years,
        birth_cohort_size=birth_cohort_size,
        barrier_threshold=barrier_threshold,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "immunity_projection",
        {"disease": disease, "province": province, "waning_rate": waning_rate,
         "projection_years": projection_years, "birth_cohort_size": birth_cohort_size,
         "barrier_threshold": barrier_threshold},
    ))


@router.get("/analysis/effective-barrier", response_model=ApiResponse, summary="有效免疫屏障", description="用年龄接触矩阵（社会接触调查）对人群阳性率加权计算有效免疫屏障，量化各年龄组传播权重与缺口，定位最薄弱年龄组。替代仅看总阳性率的粗糙评估")
@with_snapshot("effective_barrier", filter_keys=("disease", "province"))
async def get_effective_barrier(
    disease: Optional[str] = Query(None, description="疾病筛选"),
    province: Optional[str] = Query(None, description="省份筛选"),
    db: AsyncSession = Depends(get_db),
):
    """有效免疫屏障（接触矩阵加权）"""
    data = await analysis_service.get_effective_barrier(
        db=db,
        disease=disease,
        province=province,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "effective_barrier",
        {"disease": disease, "province": province},
    ))


@router.get("/analysis/barrier-probability", response_model=ApiResponse, summary="免疫屏障达标概率评估", description="把数据点的置信区间误差经 Monte Carlo 传播到 HIT，输出达标概率（替代达标/不达标二元结论）。传入 disease、province 必填。")
@with_snapshot("barrier_probability", filter_keys=("disease", "province"),
               data_type_override="seroprevalence")
async def get_barrier_probability(
    disease: str = Query(..., description="疾病筛选（必填）"),
    province: str = Query(..., description="省份筛选（必填）"),
    db: AsyncSession = Depends(get_db),
):
    """免疫屏障不确定性量化：达标概率 + 建议动作。"""
    data = await analysis_service.get_barrier_probability(
        db=db,
        disease=disease,
        province=province,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "barrier_probability", {"disease": disease, "province": province},
    ))


@router.get("/analysis/approved-data-points", response_model=ApiResponse, summary="获取审核通过的数据点", description="分页获取所有审核通过的数据点，用于数据分析模块，支持多维度筛选和排序")
@with_snapshot("approved_data_points")
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
    return ApiResponse(data=_attach_methodology_note(
        {"items": items, "total": total}, "approved_data_points",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end,
         "age_min": age_min, "age_max": age_max, "data_type": data_type},
    ))


@router.get("/analysis/data-gaps", response_model=ApiResponse, summary="数据覆盖度分析", description="分析各省份各年份的数据点分布，识别需要审核和补充的数据缺口，支持按疾病筛选")
@with_snapshot("data_gaps", filter_keys=("disease",), review_status=None)
async def get_data_gaps(
    disease: Optional[str] = Query(None, description="疾病筛选（不传则分析全库）"),
    db: AsyncSession = Depends(get_db),
):
    """数据覆盖度分析：统计各省份各年份的数据点分布，识别需要审核和补充的数据缺口"""
    data = await analysis_service.get_data_gap_analysis(
        db=db,
        disease=disease,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "data_gaps", {"disease": disease},
    ))


@router.get("/analysis/coverage-review", response_model=ApiResponse, summary="审核状态统计", description="按疾病维度统计数据点数、样本量、审核状态(approved/pending/rejected)与通过率，默认按待审核数降序排序")
@with_snapshot("coverage_review", filter_keys=("disease",), review_status=None)
async def get_coverage_review(
    disease: Optional[str] = Query(None, description="疾病筛选（不传则统计全部疾病）"),
    db: AsyncSession = Depends(get_db),
):
    """按疾病维度的审核状态统计（数据点/样本量/通过率）"""
    data = await analysis_service.get_coverage_review_stats(
        db=db,
        disease=disease,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "coverage_review", {"disease": disease},
    ))


@router.get("/analysis/review-stats", response_model=ApiResponse, summary="审核统计", description="按疾病/审核人维度统计审核量、通过率、平均审核时间（仅统计已审核并记录审核时间的数据点）")
async def get_review_stats(
    db: AsyncSession = Depends(get_db),
):
    """审核仪表盘：按疾病 / 审核人聚合审核量、通过率、平均审核时间"""
    from app.services.extraction_service import get_review_stats as compute_review_stats

    data = await compute_review_stats(db)
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
):
    """导出分析数据为 Excel 多 sheet"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    # 并行获取所有分析数据（每个任务使用独立 AsyncSession，避免共享 session 并发不安全）
    import asyncio
    from app.models.base import async_session

    async def _run(fn, **kw):
        async with async_session() as s:
            return await fn(db=s, **kw)

    trend_data, region_data, age_data, summary_data, approved_result = await asyncio.gather(
        _run(analysis_service.get_trend, disease=disease, province=province,
             year_start=year_start, year_end=year_end,
             age_min=age_min, age_max=age_max, data_type=data_type),
        _run(analysis_service.get_region_compare, disease=disease, province=province,
             year_start=year_start, year_end=year_end,
             age_min=age_min, age_max=age_max, data_type=data_type),
        _run(analysis_service.get_age_stratify, disease=disease, province=province,
             year_start=year_start, year_end=year_end,
             age_min=age_min, age_max=age_max, data_type=data_type),
        _run(analysis_service.get_summary, disease=disease, province=province,
             year_start=year_start, year_end=year_end,
             age_min=age_min, age_max=age_max, data_type=data_type),
        _run(analysis_service.get_approved_data_points, disease=disease, province=province,
             year_start=year_start, year_end=year_end,
             age_min=age_min, age_max=age_max, data_type=data_type,
             offset=0, limit=10000),
    )
    approved_items, _ = approved_result

    content = build_excel_export(
        trend_data=trend_data,
        region_data=region_data,
        age_data=age_data,
        summary_data=summary_data,
        approved_items=approved_items,
    )

    return Response(
        content=content,
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
@with_snapshot("foi", filter_keys=("disease", "province", "year_start", "year_end"))
async def get_foi_herd_immunity(
    disease: Optional[str] = Query(None, description="疾病筛选（不传则全库分析）"),
    province: Optional[str] = Query(None, description="省份筛选"),
    year_start: Optional[int] = Query(None, description="起始年份"),
    year_end: Optional[int] = Query(None, description="结束年份"),
    life_expectancy: float = Query(75.0, ge=50, le=100, description="期望寿命（年），默认75"),
    seroreversion_mu: Optional[float] = Query(None, ge=0, le=0.2, description="血清转阴率 μ（0/0.01/0.02，留空则按数据估计）"),
    hit_source_override: Optional[str] = Query(None, pattern="^(who|literature|foi)$", description="HIT 阈值来源覆盖（who|literature|foi）"),
    db: AsyncSession = Depends(get_db),
):
    """P0: FOI（感染力）+ 群体免疫阈值综合分析。

    纯分析逻辑（无 DB 变更）：
    - 用催化模型 λ = -ln(1-SP)/age 估算各年龄组 FOI
    - 反推 R0 ≈ λ·L（L 取期望寿命参数，默认 75 年）
    - 计算 HIT = 1 - 1/R0，并与 WHO 阈值对比
    - 按省份 × 疾病输出 FOI 热力矩阵与群体免疫状态
    """
    data = await analysis_service.get_foi_analysis(
        db=db,
        disease=disease,
        province=province,
        year_start=year_start,
        year_end=year_end,
        life_expectancy=life_expectancy,
        seroreversion_mu=seroreversion_mu,
        hit_source_override=hit_source_override,
    )
    return ApiResponse(data=_attach_methodology_note(
        data, "foi",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end,
         "life_expectancy": life_expectancy, "seroreversion_mu": seroreversion_mu,
         "hit_source_override": hit_source_override},
    ))


@router.get("/analysis/vaccine-effectiveness-coverage", response_model=ApiResponse, summary="疫苗效果和接种率分析", description="P1：分析疫苗效果（VE）和接种覆盖率，计算VE，返回省×疾病覆盖率矩阵，判断接种进度是否达标")
@with_snapshot("vaccine", filter_keys=("disease", "province", "year_start", "year_end"),
               include_subgroups=True)
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
    return ApiResponse(data=_attach_methodology_note(
        data, "vaccine",
        {"disease": disease, "province": province, "year_start": year_start, "year_end": year_end},
    ))


# ---------------------------------------------------------------------------
# 分析快照：重放 + 引用导出
# ---------------------------------------------------------------------------
@router.get("/analysis/snapshot/{token}", response_model=ApiResponse,
            summary="分析快照重放", description="凭快照 token 重放参数直出结果（缓存响应 json，不重新计算）")
async def replay_snapshot(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """按快照 token 重放：直接返回生成时缓存的响应 JSON（含 meta.snapshot_token）。"""
    from app.services.snapshot_service import get_snapshot
    snap = await get_snapshot(db, token)
    if snap is None:
        raise HTTPException(status_code=404, detail="快照不存在或已失效")
    data = dict(snap.response_json or {})
    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta
    meta["snapshot_token"] = str(snap.id)
    meta["snapshot_module"] = snap.module
    meta["snapshot_data_hash"] = snap.data_hash
    meta["snapshot_created_at"] = (
        snap.created_at.isoformat() if snap.created_at else None
    )
    return ApiResponse(data=data)


@router.get("/analysis/snapshot/{token}/citation", summary="分析快照引用导出",
            description="生成快照引用文本（style=gbt7714|bibtex），含版本号与访问日期")
async def snapshot_citation(
    token: str,
    style: str = Query("gbt7714", pattern="^(gbt7714|bibtex)$", description="引用格式：gbt7714 或 bibtex"),
    db: AsyncSession = Depends(get_db),
):
    """生成快照引用文本（GBT7714 电子文献[EB/OL] 或 BibTeX 条目）。"""
    from app.services.snapshot_service import build_citation, get_snapshot
    snap = await get_snapshot(db, token)
    if snap is None:
        raise HTTPException(status_code=404, detail="快照不存在或已失效")
    return Response(
        content=build_citation(snap, style=style),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "inline"},
    )


@router.get("/analysis/titer-tables", response_model=ApiResponse,
            summary="滴度矩阵表列表", description="列出可制图的滴度矩阵（仅审核通过 approved）：含文献标题、检测类型、矩阵维度、质量分。可选按 assay_type 过滤。")
async def list_titer_tables(
    assay_type: Optional[str] = Query(None, description="检测类型过滤：hi/vnt/elisa"),
    db: AsyncSession = Depends(get_db),
):
    """滴度矩阵列表：供前端"抗原图谱"Tab 选择矩阵。"""
    from app.models.titer_table import TiterTable
    from app.models.literature import Literature

    stmt = (
        select(TiterTable, Literature.title)
        .join(Literature, TiterTable.literature_id == Literature.id)
        .where(TiterTable.review_status == "approved")
        .order_by(TiterTable.created_at.desc())
    )
    if assay_type:
        stmt = stmt.where(TiterTable.assay_type == assay_type)
    rows = (await db.execute(stmt)).all()

    items = []
    for tt, title in rows:
        n_rows = len(tt.titers) if isinstance(tt.titers, list) else 0
        n_cols = len(tt.titers[0]) if n_rows and isinstance(tt.titers[0], list) else 0
        items.append({
            "id": str(tt.id),
            "literature_id": str(tt.literature_id),
            "literature_title": title or "未知文献",
            "assay_type": tt.assay_type,
            "unit": tt.unit,
            "n_antigens": n_rows,
            "n_sera": n_cols,
            "quality_score": tt.quality_score,
            "confidence": tt.confidence,
            "created_at": tt.created_at.isoformat() if tt.created_at else None,
        })
    return ApiResponse(data={"items": items, "total": len(items)})


@router.get("/analysis/antigenic-map/{titer_table_id}", response_model=ApiResponse,
            summary="抗原图谱（滴度矩阵制图）",
            description="对指定滴度矩阵表做抗原制图：log₂(titer/10) 预处理 + 列基准表格距离 + metric MDS，输出 2D 坐标（抗原■/血清●）、应力值与网格说明。仅审核通过(approved)的矩阵可制图。")
async def get_antigenic_map(
    titer_table_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """抗原图谱：读取 TiterTable 矩阵 → 制图引擎 → 输出坐标/应力/网格说明。"""
    from app.models.titer_table import TiterTable
    from app.core.antigenic_cartography import antigenic_map

    tt = await db.get(TiterTable, titer_table_id)
    if tt is None:
        raise HTTPException(status_code=404, detail="滴度矩阵表不存在")
    if tt.review_status != "approved":
        raise HTTPException(
            status_code=422,
            detail=f"该滴度矩阵尚未审核通过（当前状态: {tt.review_status}），无法生成抗原图谱",
        )
    if not tt.titers:
        raise HTTPException(status_code=422, detail="滴度矩阵数据为空")

    try:
        result = antigenic_map(
            titers_2d=tt.titers,
            antigen_names=[str(a) for a in (tt.antigens or [])],
            serum_names=[str(s) for s in (tt.ref_antisera or [])],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    data = {
        "titer_table_id": str(tt.id),
        "literature_id": str(tt.literature_id),
        "assay_type": tt.assay_type,
        "unit": tt.unit,
        "antigens": [str(a) for a in (tt.antigens or [])],
        "ref_antisera": [str(s) for s in (tt.ref_antisera or [])],
        "quality_score": tt.quality_score,
        "confidence": tt.confidence,
        "source_page": tt.source_page,
        **result,
    }
    return ApiResponse(data=_attach_methodology_note(
        data, "antigenic_map",
        {"titer_table_id": str(tt.id), "assay_type": tt.assay_type},
    ))
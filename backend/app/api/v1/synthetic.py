"""AI 提取准确度自测 API：合成文献生成、提取、评估、历史、导出。"""
import asyncio
import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.timeutil import iso_ts
from app.models.base import async_session
from app.models.data_point import DataPoint
from app.models.kg_entity import KGEntity
from app.models.literature import Literature
from app.models.synthetic_extraction import SyntheticExtraction
from app.models.synthetic_task import SyntheticTask
from app.schemas.common import ApiResponse
from app.schemas.synthetic import SyntheticCreate, SyntheticExtract
from app.services.synthetic_service import (
    compute_assessment,
    compute_multi_assessment,
    extraction_progress,
    generate_ground_truth,
    resolve_literature_ids_by_tag,
    run_generation,
    runs_progress,
    trigger_extraction_for_task,
    trigger_reference_gt,
    trigger_serial_multi_extraction,
)
from app.services.literature.crud import _cleanup_txt_cache

logger = logging.getLogger("uvicorn")
router = APIRouter()

# 后台生成任务引用，防止被垃圾回收
_bg_generations: set[asyncio.Task] = set()


def _secs(a, b):
    """两时间戳间隔秒数（a→b，无法计算返回 None）。"""
    if not a or not b:
        return None
    d = (b - a).total_seconds()
    return round(d, 1) if d >= 0 else None


def _task_dict(t: SyntheticTask) -> dict:
    return {
        "id": str(t.id),
        "disease": t.disease,
        "n_literatures": t.n_literatures,
        "points_per_literature": t.points_per_literature,
        "literature_source": t.literature_source,
        "generator_model": t.generator_model,
        "extractor_model": t.extractor_model,
        "reference_model": t.reference_model,
        "models": t.models,
        "tag_id": str(t.tag_id) if t.tag_id else None,
        "noise_ratio": t.noise_ratio,
        "seed": t.seed,
        "output_format": t.output_format,
        "include_table": t.include_table,
        "status": t.status,
        "error_message": t.error_message,
        "literature_count": len(t.literature_ids or []),
        "created_at": iso_ts(t.created_at),
        "updated_at": iso_ts(t.updated_at),
        "report": (t.report_json or {}).get("summary") if t.report_json else None,
        # 阶段耗时（秒）：生成、提取、总耗时
        "generation_seconds": _secs(t.generation_started_at, t.generated_at),
        "extraction_seconds": _secs(t.extraction_started_at, t.extracted_at),
        "total_seconds": _secs(t.created_at, t.extracted_at or t.updated_at),
    }


async def _run_reference_gt(task_id: uuid.UUID, reference_model: str | None):
    """后台：existing 来源任务的参考模型基准(GT)生成。独立会话，失败落库。"""
    try:
        async with async_session() as db:
            await trigger_reference_gt(db, task_id, reference_model)
    except Exception as e:
        logger.error(f"[Synthetic] 参考基准生成失败 task={task_id}: {e}", exc_info=True)
        async with async_session() as db:
            from sqlalchemy import update
            await db.execute(
                update(SyntheticTask)
                .where(SyntheticTask.id == task_id)
                .values(status="failed", error_message=f"参考基准生成失败: {e}"[:2000])
            )
            await db.commit()


@router.post("/synthetic", response_model=ApiResponse, summary="创建自测任务", description="创建 AI 提取准确度自测任务。generated 来源：后台用生成模型 A 生成含已知答案的合成文献；existing 来源：用参考模型对所选已有文献（可传 literature_ids 或按编组 tag_id）产出基准(GT)")
async def create_synthetic(
    req: SyntheticCreate,
    db: AsyncSession = Depends(get_db),
):
    if req.literature_source == "existing":
        # 测试文献来源：优先按编组(tag)取该编组下全部文献，否则用显式选择的文献 id
        literature_ids = list(req.literature_ids or [])
        tag_id = None
        if req.tag_id:
            try:
                tag_uuid = uuid.UUID(req.tag_id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail="tag_id 格式非法") from e
            literature_ids = await resolve_literature_ids_by_tag(db, tag_uuid)
            tag_id = tag_uuid
            if not literature_ids:
                raise HTTPException(status_code=400, detail="该编组下没有可用文献")
        if not literature_ids:
            raise HTTPException(status_code=400, detail="existing 来源必须选择编组或数据库已有文献")
        task = SyntheticTask(
            disease=req.disease,
            n_literatures=len(literature_ids),
            points_per_literature=req.points_per_literature,
            literature_source="existing",
            generator_model=req.generator_model,
            noise_ratio=req.noise_ratio,
            seed=req.seed,
            output_format=req.output_format,
            include_table=req.include_table,
            literature_ids=literature_ids,
            reference_model=req.reference_model,
            tag_id=tag_id,
            status="queued",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        bg = asyncio.create_task(_run_reference_gt(task.id, req.reference_model))
        _bg_generations.add(bg)
        bg.add_done_callback(_bg_generations.discard)
        return ApiResponse(message="自测任务已创建，正在用参考模型产出基准(GT)", data=_task_dict(task))

    gt = generate_ground_truth(
        req.disease, req.n_literatures, req.points_per_literature,
        req.noise_ratio, req.seed,
    )
    task = SyntheticTask(
        disease=req.disease,
        n_literatures=req.n_literatures,
        points_per_literature=req.points_per_literature,
        literature_source="generated",
        generator_model=req.generator_model,
        noise_ratio=req.noise_ratio,
        seed=req.seed,
        output_format=req.output_format,
        include_table=req.include_table,
        status="queued",
        gt_json=gt,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    bg = asyncio.create_task(run_generation(task.id))
    _bg_generations.add(bg)
    bg.add_done_callback(_bg_generations.discard)

    return ApiResponse(message="自测任务已创建，正在后台生成合成文献", data=_task_dict(task))


@router.post("/synthetic/{task_id}/extract", response_model=ApiResponse, summary="触发提取", description="单模型：用提取模型 B 走现有提取链路写库；多模型：models 传入时按「一个模型跑完全部文献再切换下一个」串行纯抽取（跳过缓存、结果按运行分别存 synthetic_extraction、不污染真实数据）")
async def extract_synthetic(
    task_id: uuid.UUID,
    req: SyntheticExtract,
    db: AsyncSession = Depends(get_db),
):
    try:
        if req.models:
            result = await trigger_serial_multi_extraction(db, task_id, req.models)
            message = f"已提交 {result['submitted']} 次提取（{len(result['models'])} 个模型 × {result['literatures']} 篇，串行执行）"
        else:
            if not req.model:
                raise ValueError("请提供单模型 model 或多模型 models")
            result = await trigger_extraction_for_task(db, task_id, req.model)
            message = f"已提交 {result['submitted']} 篇文献提取"
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(message=message, data=result)


@router.get("/synthetic", response_model=ApiResponse, summary="自测任务历史", description="列出所有 AI 提取准确度自测任务（历史）")
async def list_synthetic(db: AsyncSession = Depends(get_db)):
    tasks = (await db.execute(
        select(SyntheticTask).order_by(SyntheticTask.created_at.desc())
    )).scalars().all()
    return ApiResponse(data=[_task_dict(t) for t in tasks])


@router.get("/synthetic/{task_id}", response_model=ApiResponse, summary="自测任务详情/进度", description="查看单个自测任务的参数、生成/提取进度、以及评估结果摘要")
async def get_synthetic(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    task = (await db.execute(
        select(SyntheticTask).where(SyntheticTask.id == task_id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    data = _task_dict(task)
    # 按运行（单模型 × 全部文献）分组的进度与效率指标
    runs = await runs_progress(db, task_id)
    if runs:
        data["runs"] = runs
    if task.literature_ids:
        if task.literature_source == "existing" or task.models:
            # 多模型对比：逐 (模型×文献) 提取进度（无 run 记录的历史任务才回退该口径）
            if not runs:
                rows = (await db.execute(
                    select(SyntheticExtraction).where(
                        SyntheticExtraction.task_id == task_id
                    ).order_by(SyntheticExtraction.model, SyntheticExtraction.updated_at)
                )).scalars().all()
                meta = {
                    str(lit.id): lit.title for lit in (
                        await db.execute(select(Literature).where(Literature.id.in_(
                            [uuid.UUID(x) for x in task.literature_ids]
                        )))
                    ).scalars().all()
                }
                data["multi_progress"] = [
                    {
                        "model": r.model,
                        "literature_id": str(r.literature_id),
                        "title": meta.get(str(r.literature_id), ""),
                        "status": r.status,
                        "error": r.error,
                        "updated_at": iso_ts(r.updated_at),
                        "points_count": len(r.points_json or []),
                    }
                    for r in rows
                ]
        else:
            data["literature_progress"] = await extraction_progress(db, task_id)
    if task.report_json:
        data["report_by_literature"] = task.report_json.get("by_literature", [])
        data["report_per_noise"] = task.report_json.get("summary", {}).get("per_noise_type", {})
        data["multi_model"] = task.report_json.get("multi_model")
    return ApiResponse(data=data)


@router.post("/synthetic/{task_id}/assess", response_model=ApiResponse, summary="执行评估", description="将提取结果与 ground truth 比对。多模型任务产出多模型横向对比 + 逐篇比对；单模型产出原有评估报告")
async def assess_synthetic(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    task = (await db.execute(
        select(SyntheticTask).where(SyntheticTask.id == task_id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        if task.models:
            report = await compute_multi_assessment(db, task_id)
        else:
            report = await compute_assessment(db, task_id)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(message="评估完成", data=report)


@router.get("/synthetic/{task_id}/export", summary="导出评估报告 CSV", description="导出该自测任务的评估明细为 CSV（逐文献 + 汇总指标）")
async def export_synthetic(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    task = (await db.execute(
        select(SyntheticTask).where(SyntheticTask.id == task_id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.report_json:
        raise HTTPException(status_code=400, detail="尚未生成评估报告")

    buf = io.StringIO()
    writer = csv.writer(buf)
    summary = task.report_json.get("summary", {})
    writer.writerow(["指标", "值"])
    for k, v in summary.items():
        if isinstance(v, (dict,)):
            writer.writerow([k, v])
        else:
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["literature_id", "标题", "clean_total", "clean_matched", "noise_total", "noise_rejected"])
    by_lit = task.report_json.get("by_literature", [])
    for row in by_lit:
        writer.writerow([row["literature_id"], row.get("title"), row["clean_total"],
                         row["clean_matched"], row["noise_total"], row["noise_rejected"]])
    # 逐篇真实数据点与提取识别点明细
    for row in by_lit:
        writer.writerow([])
        writer.writerow([f"【文献】 {row.get('title')}  ({row['literature_id']})"])
        writer.writerow(["真实数据点 | 数据类型", "真实值", "单位", "样本量", "省份", "年份", "噪声类型", "是否命中"])
        for g in row.get("gt_points", []):
            writer.writerow([g.get("data_type"), g.get("value"), g.get("unit"), g.get("sample_size"),
                             g.get("province"), g.get("collection_year"), g.get("noise_kind") or "", g.get("matched")])
        writer.writerow([])
        writer.writerow(["提取识别点 | 数据类型", "识别值", "单位", "样本量", "省份", "城市", "年份", "对应GT idx"])
        for e in row.get("extracted_points", []):
            writer.writerow([e.get("data_type"), e.get("value"), e.get("unit"), e.get("sample_size"),
                             e.get("province"), e.get("city"), e.get("collection_year"), e.get("gt_idx", "")])

    # 多模型对比：横向指标 + 逐篇逐模型明细
    multi = task.report_json.get("multi_model")
    if multi:
        writer.writerow([])
        writer.writerow(["==== 多模型横向对比 ===="])
        writer.writerow(["模型(运行)", "基础模型", "运行序号", "GT口径",
                         "清洁点", "命中", "召回率", "值级准确度", "字段P", "字段R", "字段F1",
                         "噪声点", "拒噪", "噪声拒绝率", "额外识别率", "幻觉率", "JSON合法率",
                         "成功率", "总数据点", "单篇均耗时(s)", "平均首token延迟(ms)", "平均生成速度(t/s)", "峰值显存(MB)"])
        gt_source = multi.get("gt_source") or ""
        for c in multi.get("comparison", []):
            prf = c.get("field_prf_macro") or {}
            writer.writerow([
                c.get("model"), c.get("base_model"), c.get("run_index"), gt_source,
                c.get("clean_total"), c.get("clean_matched"), c.get("clean_recall"),
                c.get("value_accuracy"), prf.get("precision"), prf.get("recall"), prf.get("f1"),
                c.get("noise_total"), c.get("noise_rejected"), c.get("noise_rejection_rate"),
                c.get("extra_rate"), c.get("hallucination_rate"), c.get("json_ok_rate"),
                c.get("success_rate"), c.get("total_points"), c.get("avg_duration_s"),
                c.get("avg_first_token_ms"), c.get("avg_tokens_per_sec"), c.get("peak_vram_mb"),
            ])

        # 同一模型多次运行的稳定性（均值 ± 标准差）
        stability = multi.get("stability") or []
        if stability:
            writer.writerow([])
            writer.writerow(["==== 同一模型多次运行稳定性（均值 ± 标准差）===="])
            writer.writerow(["模型", "运行次数", "指标", "均值", "标准差"])
            for s in stability:
                for k, mv in (s.get("metrics") or {}).items():
                    writer.writerow([s.get("model"), s.get("runs"), k,
                                     (mv or {}).get("mean"), (mv or {}).get("std")])

        for lit in multi.get("by_literature", []):
            writer.writerow([])
            writer.writerow([f"【多模型·文献】 {lit.get('title')}  ({lit.get('literature_id')})"])
            writer.writerow(["真实数据点 | 数据类型", "真实值", "单位", "样本量", "省份", "年份", "噪声类型", "是否命中"])
            for g in lit.get("gt_points", []):
                writer.writerow([g.get("data_type"), g.get("value"), g.get("unit"), g.get("sample_size"),
                                 g.get("province"), g.get("collection_year"), g.get("noise_kind") or "", g.get("matched")])
            for model_name, info in (lit.get("models") or {}).items():
                writer.writerow([])
                writer.writerow([f"模型 {model_name} 提取识别点 | 数据类型", "识别值", "单位", "样本量", "省份", "城市", "年份", "对应GT idx"])
                for e in info.get("extracted_points", []):
                    writer.writerow([e.get("data_type"), e.get("value"), e.get("unit"), e.get("sample_size"),
                                     e.get("province"), e.get("city"), e.get("collection_year"), e.get("gt_idx", "")])

    buf.seek(0)
    filename = f"synthetic_assessment_{task.disease}_{task.id}.csv"
    # 文件名可能含中文疾病名，HTTP 响应头仅 latin-1；用 filename*=UTF-8'' 承载中文，
    # 并用纯 ASCII 的 filename 兜底，避免 UnicodeEncodeError -> 500
    ascii_filename = f"synthetic_assessment_{task.id}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.delete("/synthetic/{task_id}", response_model=ApiResponse, summary="删除自测任务", description="仅允许删除已失败的自测任务，级联清理该任务生成的合成文献及其数据点，不影响正式数据")
async def delete_synthetic(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    task = (await db.execute(
        select(SyntheticTask).where(SyntheticTask.id == task_id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != "failed":
        raise HTTPException(status_code=409, detail="仅失败状态的任务可删除")

    lit_ids = [uuid.UUID(x) for x in (task.literature_ids or [])]
    if lit_ids:
        # 级联清理该任务的合成文献及其关联数据点 / KG 实体 / 溯源缓存，防止孤儿数据与国际 FK 失败
        await db.execute(
            delete(DataPoint).where(DataPoint.literature_id.in_(lit_ids))
        )
        await db.execute(
            delete(KGEntity).where(KGEntity.source_literature_id.in_(lit_ids))
        )
        await db.execute(
            delete(Literature).where(Literature.id.in_(lit_ids))
        )
    await db.delete(task)
    await db.commit()

    # 删除溯源文本缓存文件（对齐永久删除文献时的清理约定）
    for lit_id in lit_ids:
        _cleanup_txt_cache(str(lit_id))
    return ApiResponse(data={"deleted": str(task_id)})
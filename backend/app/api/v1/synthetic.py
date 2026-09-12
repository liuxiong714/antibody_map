"""AI 提取准确度自测 API：合成文献生成、提取、评估、历史、导出。"""
import asyncio
import csv
import io
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.synthetic_task import SyntheticTask
from app.schemas.common import ApiResponse
from app.schemas.synthetic import SyntheticCreate, SyntheticExtract
from app.services.synthetic_service import (
    compute_assessment,
    extraction_progress,
    generate_ground_truth,
    run_generation,
    trigger_extraction_for_task,
)

logger = logging.getLogger("uvicorn")
router = APIRouter()

# 后台生成任务引用，防止被垃圾回收
_bg_generations: set[asyncio.Task] = set()


def _task_dict(t: SyntheticTask) -> dict:
    return {
        "id": str(t.id),
        "disease": t.disease,
        "n_literatures": t.n_literatures,
        "points_per_literature": t.points_per_literature,
        "generator_model": t.generator_model,
        "extractor_model": t.extractor_model,
        "noise_ratio": t.noise_ratio,
        "seed": t.seed,
        "status": t.status,
        "error_message": t.error_message,
        "literature_count": len(t.literature_ids or []),
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "report": (t.report_json or {}).get("summary") if t.report_json else None,
    }


@router.post("/synthetic", response_model=ApiResponse, summary="创建合成文献自测任务", description="创建 AI 提取准确度自测任务，后台用生成模型 A 生成指定数量含已知答案（含噪声）的合成文献并入库")
async def create_synthetic(
    req: SyntheticCreate,
    db: AsyncSession = Depends(get_db),
):
    gt = generate_ground_truth(
        req.disease, req.n_literatures, req.points_per_literature,
        req.noise_ratio, req.seed,
    )
    task = SyntheticTask(
        disease=req.disease,
        n_literatures=req.n_literatures,
        points_per_literature=req.points_per_literature,
        generator_model=req.generator_model,
        noise_ratio=req.noise_ratio,
        seed=req.seed,
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


@router.post("/synthetic/{task_id}/extract", response_model=ApiResponse, summary="对合成文献触发提取", description="用指定的提取模型 B 对任务内所有合成文献触发现有 AI 提取链路")
async def extract_synthetic(
    task_id: uuid.UUID,
    req: SyntheticExtract,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await trigger_extraction_for_task(db, task_id, req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(message=f"已提交 {result['submitted']} 篇文献提取", data=result)


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
    if task.literature_ids:
        data["literature_progress"] = await extraction_progress(db, task_id)
    if task.report_json:
        data["report_by_literature"] = task.report_json.get("by_literature", [])
        data["report_per_noise"] = task.report_json.get("summary", {}).get("per_noise_type", {})
    return ApiResponse(data=data)


@router.post("/synthetic/{task_id}/assess", response_model=ApiResponse, summary="执行评估", description="待任务内所有文献提取完成后，将提取结果与 ground truth 比对并生成评估报告")
async def assess_synthetic(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
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
    writer.writerow(["literature_id", "clean_total", "clean_matched", "noise_total", "noise_rejected"])
    for row in task.report_json.get("by_literature", []):
        writer.writerow([row["literature_id"], row["clean_total"], row["clean_matched"],
                         row["noise_total"], row["noise_rejected"]])

    buf.seek(0)
    filename = f"synthetic_assessment_{task.disease}_{task.id}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
"""查重与合并端点 —— 检查重复、全库扫描、预览合并、执行合并。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiResponse
from app.schemas.literature import (
    CheckDuplicateRequest,
    LiteratureResponse,
    MergePreviewRequest,
    MergeRequest,
)
from app.services.literature.duplicates import (
    check_duplicates,
    merge_literatures,
    preview_merge,
    scan_duplicates,
)

router = APIRouter()


@router.post("/literatures/check-duplicate", response_model=ApiResponse, summary="检查文献重复", description="检查指定文献是否存在重复，支持按文献ID、标题、DOI、作者、PDF哈希值进行匹配检测")
async def check_duplicate(
    req: CheckDuplicateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await check_duplicates(
            db, req.literature_id,
            title=req.title, doi=req.doi, authors=req.authors, pdf_hash=req.pdf_hash,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ApiResponse(data={
        "literature_id": result["literature_id"],
        "total": result["total"],
        "duplicates": [
            {
                "literature": LiteratureResponse.model_validate(d["literature"]).model_dump(),
                "match_reasons": d["match_reasons"],
                "match_values": d["match_values"],
            }
            for d in result["duplicates"]
        ],
    })


@router.post("/literatures/scan-duplicates", response_model=ApiResponse, summary="全库扫描重复文献", description="扫描整个文献库，识别所有重复文献并分组返回，用于批量管理重复记录")
async def scan_duplicates_endpoint(
    db: AsyncSession = Depends(get_db),
):
    result = await scan_duplicates(db)
    serializable_groups = []
    for g in result["groups"]:
        serializable_groups.append({
            "literature_ids": [str(uid) for uid in g["literature_ids"]],
            "match_reasons": g["match_reasons"],
            "representative_id": str(g["representative_id"]),
        })
    return ApiResponse(data={
        "groups": serializable_groups,
        "total_groups": result["total_groups"],
        "total_duplicates": result["total_duplicates"],
    })


@router.post("/literatures/merge/preview", response_model=ApiResponse, summary="预览文献合并", description="预览合并结果：展示两篇文献的字段对比及数据点冲突检测，供用户确认合并策略")
async def merge_preview(
    req: MergePreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await preview_merge(db, req.source_id, req.target_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ApiResponse(data=result)


@router.post("/literatures/merge", response_model=ApiResponse, summary="执行文献合并", description="执行合并操作：将源文献合并进目标文献，根据用户选择的字段和冲突策略处理数据点，删除源文献")
async def merge(
    req: MergeRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await merge_literatures(
            db, req.source_id, req.target_id,
            req.field_choices,
            req.dp_conflict_strategy,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(
        message="合并成功",
        data={
            "merged_literature": LiteratureResponse.model_validate(result["merged_literature"]).model_dump(),
            "moved_data_points": result["moved_data_points"],
            "deleted_conflict_data_points": result["deleted_conflict_data_points"],
            "deleted_source_id": result["deleted_source_id"],
        },
    )
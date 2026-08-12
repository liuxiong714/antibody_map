"""文件夹监控 API 端点。"""
import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.base import async_session
from app.schemas.common import ApiResponse
from app.schemas.folder_monitor import (
    MonitoredFolderCreate,
    MonitoredFolderUpdate,
    MonitoredFolderResponse,
    MonitoredFileResponse,
)
from app.services.folder_monitor_service import (
    list_monitored_folders,
    get_monitored_folder,
    create_monitored_folder,
    update_monitored_folder,
    delete_monitored_folder,
    list_monitored_files,
    scan_folder,
)

logger = logging.getLogger("uvicorn")
router = APIRouter()


@router.get("/folders", response_model=ApiResponse)
async def list_folders(db: AsyncSession = Depends(get_db)):
    """列出所有监控文件夹"""
    folders = await list_monitored_folders(db)
    return ApiResponse(data=[
        MonitoredFolderResponse.model_validate(f).model_dump() for f in folders
    ])


@router.post("/folders", response_model=ApiResponse)
async def create_folder(
    req: MonitoredFolderCreate,
    db: AsyncSession = Depends(get_db),
):
    """添加监控文件夹"""
    try:
        folder = await create_monitored_folder(db, req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(
        message="添加成功",
        data=MonitoredFolderResponse.model_validate(folder).model_dump(),
    )


@router.put("/folders/{folder_id}", response_model=ApiResponse)
async def update_folder(
    folder_id: uuid.UUID,
    req: MonitoredFolderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新监控文件夹配置"""
    try:
        folder = await update_monitored_folder(db, folder_id, req.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return ApiResponse(
        message="更新成功",
        data=MonitoredFolderResponse.model_validate(folder).model_dump(),
    )


@router.delete("/folders/{folder_id}", response_model=ApiResponse)
async def delete_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """删除监控文件夹"""
    success = await delete_monitored_folder(db, folder_id)
    if not success:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return ApiResponse(message="删除成功")


async def _run_scan_background(folder_id: uuid.UUID):
    """在后台执行扫描，使用独立的数据库会话。"""
    try:
        async with async_session() as db:
            folder = await get_monitored_folder(db, folder_id)
            if not folder:
                return
            await scan_folder(db, folder)
    except Exception as e:
        logger.error(f"后台扫描文件夹 {folder_id} 异常: {e}", exc_info=True)
        async with async_session() as db:
            folder = await get_monitored_folder(db, folder_id)
            if folder:
                from datetime import datetime, timezone
                folder.status = "error"
                folder.error_message = str(e)[:500]
                folder.last_scan_at = datetime.now(timezone.utc)
                await db.commit()


@router.post("/folders/{folder_id}/scan", response_model=ApiResponse)
async def trigger_scan(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """手动触发扫描指定文件夹（异步后台执行，立即返回）"""
    folder = await get_monitored_folder(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    if folder.status == "scanning":
        raise HTTPException(status_code=409, detail="该文件夹正在扫描中，请等待完成")
    # 启动后台扫描任务，立即返回
    asyncio.create_task(_run_scan_background(folder_id))
    return ApiResponse(message="扫描已启动，请稍后在列表中查看结果")


@router.get("/folders/{folder_id}/files", response_model=ApiResponse)
async def list_files(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """查看指定文件夹的文件处理记录"""
    files = await list_monitored_files(db, folder_id)
    return ApiResponse(data=[
        MonitoredFileResponse.model_validate(f).model_dump() for f in files
    ])

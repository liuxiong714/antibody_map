import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.literature import Literature
from app.models.literature_tag import Tag, literature_tag
from app.schemas.common import ApiResponse

router = APIRouter()
logger = logging.getLogger("uvicorn")


class TagCreate(BaseModel):
    name: str
    color: Optional[str] = "#1677ff"


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


# ── 标签 CRUD ──

@router.get("/tags", response_model=ApiResponse, summary="获取所有标签", description="获取系统中所有已定义的标签列表，按名称排序")
async def list_tags(db: AsyncSession = Depends(get_db)):
    """获取所有标签"""
    result = await db.execute(select(Tag).order_by(Tag.name))
    tags = result.scalars().all()
    return ApiResponse(data=[{"id": str(t.id), "name": t.name, "color": t.color} for t in tags])


@router.post("/tags", response_model=ApiResponse, summary="创建标签", description="创建一个新标签，需指定标签名称和颜色")
async def create_tag(req: TagCreate, db: AsyncSession = Depends(get_db)):
    """创建标签"""
    existing = await db.execute(select(Tag).where(Tag.name == req.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"标签「{req.name}」已存在")
    tag = Tag(name=req.name.strip(), color=req.color or "#1677ff")
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    logger.info(f"创建标签: id={tag.id}, name={tag.name}")
    return ApiResponse(data={"id": str(tag.id), "name": tag.name, "color": tag.color})


@router.put("/tags/{tag_id}", response_model=ApiResponse, summary="更新标签", description="更新指定标签的名称和颜色")
async def update_tag(tag_id: uuid.UUID, req: TagUpdate, db: AsyncSession = Depends(get_db)):
    """更新标签"""
    result = await db.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")
    if req.name is not None:
        tag.name = req.name.strip()
    if req.color is not None:
        tag.color = req.color
    await db.commit()
    await db.refresh(tag)
    return ApiResponse(data={"id": str(tag.id), "name": tag.name, "color": tag.color})


@router.delete("/tags/{tag_id}", response_model=ApiResponse, summary="删除标签", description="删除指定标签，同时解除所有文献与该标签的关联")
async def delete_tag(tag_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """删除标签"""
    result = await db.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")
    await db.delete(tag)
    await db.commit()
    logger.info(f"删除标签: id={tag_id}")
    return ApiResponse(message="标签已删除")


# ── 文献 ↔ 标签 关联 ──

@router.post("/literatures/{literature_id}/tags", response_model=ApiResponse, summary="设置文献标签", description="全量替换指定文献的标签（设置文献关联的标签集合），传入标签ID列表")
async def set_literature_tags(
    literature_id: uuid.UUID,
    tag_ids: list[str],
    db: AsyncSession = Depends(get_db),
):
    """设置文献的标签（全量替换）"""
    lit = await db.get(Literature, literature_id)
    if not lit:
        raise HTTPException(status_code=404, detail="文献不存在")

    # 查询标签对象
    uuids = [uuid.UUID(tid) for tid in tag_ids]
    result = await db.execute(select(Tag).where(Tag.id.in_(uuids)))
    tags = result.scalars().all()

    lit.tags = list(tags)
    await db.commit()
    logger.info(f"设置文献标签: literature_id={literature_id}, tags={[t.name for t in tags]}")
    return ApiResponse(data={"tag_ids": tag_ids, "tags": [{"id": str(t.id), "name": t.name, "color": t.color} for t in tags]})


@router.get("/literatures/{literature_id}/tags", response_model=ApiResponse, summary="获取文献标签", description="获取指定文献的所有关联标签")
async def get_literature_tags(literature_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """获取文献的标签"""
    lit = await db.get(Literature, literature_id)
    if not lit:
        raise HTTPException(status_code=404, detail="文献不存在")
    # 确保 tags 已加载
    await db.refresh(lit, ["tags"])
    return ApiResponse(data=[{"id": str(t.id), "name": t.name, "color": t.color} for t in lit.tags])
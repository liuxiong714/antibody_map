import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.core.crypto import mask
from app.models.api_model_config import ApiModelConfig
from app.schemas.common import ApiResponse
from app.schemas.model_config import (
    ApiModelConfigCreate,
    ApiModelConfigUpdate,
    ApiModelConfigResponse,
    ModelOption,
    ModelsListResponse,
)

logger = logging.getLogger("uvicorn")

router = APIRouter()

# 本地模型列表
LOCAL_MODELS = [
    {"value": "", "label": "默认 (qwen2.5:14b)"},
    {"value": "qwen2.5:14b", "label": "Qwen2.5:14B"},
    {"value": "qwen2.5:7b", "label": "Qwen2.5:7B"},
    {"value": "qwen3:32b", "label": "Qwen3:32B"},
    {"value": "qwen3:8b", "label": "Qwen3:8B"},
    {"value": "deepseek-r1:14b", "label": "DeepSeek R1:14B"},
    {"value": "deepseek-r1:7b", "label": "DeepSeek R1:7B"},
    {"value": "llama3.1:8b", "label": "Llama 3.1:8B"},
    {"value": "llama3.1:70b", "label": "Llama 3.1:70B"},
    {"value": "mistral:7b", "label": "Mistral:7B"},
    {"value": "glm4:9b", "label": "GLM4:9B"},
]


@router.get("/models", response_model=ApiResponse)
async def list_models(db: AsyncSession = Depends(get_db)):
    """获取可用模型列表（本地 + 远程配置）"""
    # 本地模型
    local_list = [
        {"value": m["value"], "label": m["label"], "group": "local", "is_default": (m["value"] == "")}
        for m in LOCAL_MODELS
    ]

    # 远程模型
    result = await db.execute(select(ApiModelConfig).where(ApiModelConfig.is_active == True))
    remote_configs = result.scalars().all()
    remote_list = [
        {"value": str(c.id), "label": c.name, "group": "remote"}
        for c in remote_configs
    ]

    return ApiResponse(data={"local": local_list, "remote": remote_list})


@router.get("/models/remote", response_model=ApiResponse)
async def list_remote_models(db: AsyncSession = Depends(get_db)):
    """获取所有远程模型配置"""
    result = await db.execute(select(ApiModelConfig).order_by(ApiModelConfig.created_at.desc()))
    configs = result.scalars().all()
    items = [_config_to_dict(c) for c in configs]
    return ApiResponse(data=items)


@router.post("/models/remote", response_model=ApiResponse)
async def create_remote_model(
    req: ApiModelConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """新增远程模型配置"""
    config = ApiModelConfig(
        name=req.name,
        model_name=req.model_name,
        api_key=req.api_key,
        base_url=req.base_url,
        description=req.description,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return ApiResponse(message="远程模型配置已添加", data=_config_to_dict(config))


@router.put("/models/remote/{config_id}", response_model=ApiResponse)
async def update_remote_model(
    config_id: str,
    req: ApiModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新远程模型配置"""
    uid = UUID(config_id)
    result = await db.execute(select(ApiModelConfig).where(ApiModelConfig.id == uid))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    if req.name is not None:
        config.name = req.name
    if req.model_name is not None:
        config.model_name = req.model_name
    # 仅当提供非空且非掩码的 api_key 时才更新（避免掩码覆盖真实 key）
    if req.api_key is not None and req.api_key.strip() and "***" not in req.api_key:
        config.api_key = req.api_key
    if req.base_url is not None:
        config.base_url = req.base_url
    if req.description is not None:
        config.description = req.description
    if req.is_active is not None:
        config.is_active = req.is_active

    await db.commit()
    await db.refresh(config)
    return ApiResponse(message="远程模型配置已更新", data=_config_to_dict(config))


@router.delete("/models/remote/{config_id}", response_model=ApiResponse)
async def delete_remote_model(
    config_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除远程模型配置"""
    uid = UUID(config_id)
    result = await db.execute(select(ApiModelConfig).where(ApiModelConfig.id == uid))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    await db.delete(config)
    await db.commit()
    return ApiResponse(message="远程模型配置已删除")


def _config_to_dict(c: ApiModelConfig) -> dict:
    """将配置对象转为字典，api_key 返回掩码形式（不泄露明文）"""
    return {
        "id": str(c.id),
        "name": c.name,
        "model_name": c.model_name,
        # 对外响应只返回掩码（如 "sk-***890"），真实 key 仅在后端调用 LLM 时读取
        "api_key": mask(c.api_key),
        "base_url": c.base_url,
        "description": c.description,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }
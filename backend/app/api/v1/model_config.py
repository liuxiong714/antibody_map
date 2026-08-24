import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_db, require_admin
from app.config import settings
from app.core.crypto import mask
from app.models.api_model_config import ApiModelConfig
from app.models.local_model_config import LocalModelConfig
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.model_config import (
    ApiModelConfigCreate,
    ApiModelConfigUpdate,
    ApiModelConfigResponse,
    LocalModelConfigCreate,
    LocalModelConfigUpdate,
    LocalModelConfigResponse,
    ModelOption,
    ModelsListResponse,
)

logger = logging.getLogger("uvicorn")

router = APIRouter()

# 默认模型选项（value 为空表示使用后端 .env 中 LLM_MODEL 配置的默认模型）
DEFAULT_MODEL_OPTION = {"value": "", "label": "默认配置（后端配置的模型）"}

# 本地模型回退列表（本地模型配置表为空时的兜底，保证旧环境不报错）
FALLBACK_LOCAL_MODELS = [
    {"value": "qwen3.8:27b", "label": "Qwen3.8:27B"},
    {"value": "qwen3:32b", "label": "Qwen3:32B"},
    {"value": "qwen3:8b", "label": "Qwen3:8B"},
    {"value": "qwen2.5:14b", "label": "Qwen2.5:14B"},
    {"value": "qwen2.5:7b", "label": "Qwen2.5:7B"},
    {"value": "deepseek-r1:14b", "label": "DeepSeek R1:14B"},
    {"value": "deepseek-r1:7b", "label": "DeepSeek R1:7B"},
    {"value": "llama3.1:8b", "label": "Llama 3.1:8B"},
    {"value": "llama3.1:70b", "label": "Llama 3.1:70B"},
    {"value": "mistral:7b", "label": "Mistral:7B"},
    {"value": "glm4:9b", "label": "GLM4:9B"},
]


@router.get("/models", response_model=ApiResponse, summary="获取可用模型列表", description="获取可用模型列表，包括本地模型（Ollama等）和远程API模型配置")
async def list_models(db: AsyncSession = Depends(get_db)):
    """获取可用模型列表（本地 + 远程配置）"""
    # 本地模型：优先从本地模型配置表读取启用项，表为空时回退到静态列表
    result = await db.execute(
        select(LocalModelConfig).where(LocalModelConfig.is_active == True).order_by(LocalModelConfig.created_at)
    )
    local_rows = result.scalars().all()
    if local_rows:
        local_list = [
            {**DEFAULT_MODEL_OPTION, "group": "local", "is_default": True},
        ] + [
            {"value": m.model_name, "label": m.name, "group": "local", "is_default": False}
            for m in local_rows
        ]
    else:
        local_list = [
            {**m, "group": "local", "is_default": (m["value"] == "")}
            for m in [{**DEFAULT_MODEL_OPTION}] + FALLBACK_LOCAL_MODELS
        ]

    # 远程模型
    result = await db.execute(select(ApiModelConfig).where(ApiModelConfig.is_active == True))
    remote_configs = result.scalars().all()
    remote_list = [
        {"value": str(c.id), "label": c.name, "group": "remote"}
        for c in remote_configs
    ]

    return ApiResponse(data={"local": local_list, "remote": remote_list})


@router.get("/models/remote", response_model=ApiResponse, summary="获取远程模型配置列表", description="获取所有远程模型配置，包括API Key（掩码显示）、Base URL、模型名等")
async def list_remote_models(db: AsyncSession = Depends(get_db)):
    """获取所有远程模型配置"""
    result = await db.execute(select(ApiModelConfig).order_by(ApiModelConfig.created_at.desc()))
    configs = result.scalars().all()
    items = [_config_to_dict(c) for c in configs]
    return ApiResponse(data=items)


@router.post("/models/remote", response_model=ApiResponse, summary="新增远程模型配置", description="管理员新增远程模型配置，需指定模型名称、API Key、Base URL等信息")
async def create_remote_model(
    req: ApiModelConfigCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """新增远程模型配置"""
    config = ApiModelConfig(
        name=req.name,
        model_name=req.model_name,
        api_key=req.api_key,
        base_url=req.base_url,
        description=req.description,
        expires_at=req.expires_at,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return ApiResponse(message="远程模型配置已添加", data=_config_to_dict(config))


@router.put("/models/remote/{config_id}", response_model=ApiResponse, summary="更新远程模型配置", description="管理员更新远程模型配置，可以修改名称、模型名、API Key、Base URL、描述、激活状态")
async def update_remote_model(
    config_id: str,
    req: ApiModelConfigUpdate,
    admin: User = Depends(require_admin),
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
    if req.expires_at is not None:
        config.expires_at = req.expires_at

    await db.commit()
    await db.refresh(config)
    return ApiResponse(message="远程模型配置已更新", data=_config_to_dict(config))


@router.delete("/models/remote/{config_id}", response_model=ApiResponse, summary="删除远程模型配置", description="管理员删除指定的远程模型配置")
async def delete_remote_model(
    config_id: str,
    admin: User = Depends(require_admin),
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
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


# ── 本地模型配置管理（Ollama 等）────────────────────────────

@router.get("/models/local", response_model=ApiResponse, summary="获取本地模型配置列表", description="获取所有本地模型配置，包括名称、模型名、描述、启用状态")
async def list_local_models(db: AsyncSession = Depends(get_db)):
    """获取所有本地模型配置"""
    result = await db.execute(
        select(LocalModelConfig).order_by(LocalModelConfig.created_at)
    )
    configs = result.scalars().all()
    items = [
        LocalModelConfigResponse.model_validate(c).model_dump()
        for c in configs
    ]
    return ApiResponse(data=items)


@router.post("/models/local", response_model=ApiResponse, summary="新增本地模型配置", description="管理员新增本地模型配置（Ollama 等），需指定显示名称和模型名")
async def create_local_model(
    req: LocalModelConfigCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """新增本地模型配置"""
    config = LocalModelConfig(
        name=req.name.strip(),
        model_name=req.model_name.strip(),
        description=req.description,
    )
    db.add(config)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"模型名 {req.model_name} 已存在")
    await db.refresh(config)
    return ApiResponse(message="本地模型配置已添加", data=LocalModelConfigResponse.model_validate(config).model_dump())


@router.put("/models/local/{config_id}", response_model=ApiResponse, summary="更新本地模型配置", description="管理员更新本地模型配置，可以修改名称、模型名、描述、启用状态")
async def update_local_model(
    config_id: str,
    req: LocalModelConfigUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新本地模型配置"""
    uid = UUID(config_id)
    result = await db.execute(select(LocalModelConfig).where(LocalModelConfig.id == uid))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    if req.name is not None:
        config.name = req.name.strip()
    if req.model_name is not None:
        config.model_name = req.model_name.strip()
    if req.description is not None:
        config.description = req.description
    if req.is_active is not None:
        config.is_active = req.is_active

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"模型名 {req.model_name} 已存在")
    await db.refresh(config)
    return ApiResponse(message="本地模型配置已更新", data=LocalModelConfigResponse.model_validate(config).model_dump())


@router.delete("/models/local/{config_id}", response_model=ApiResponse, summary="删除本地模型配置", description="管理员删除指定的本地模型配置")
async def delete_local_model(
    config_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除本地模型配置"""
    uid = UUID(config_id)
    result = await db.execute(select(LocalModelConfig).where(LocalModelConfig.id == uid))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    await db.delete(config)
    await db.commit()
    return ApiResponse(message="本地模型配置已删除")
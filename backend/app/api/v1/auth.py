"""认证 API：登录、用户管理、修改密码"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_admin
from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User
from app.schemas.common import ApiResponse

router = APIRouter()
logger = logging.getLogger("uvicorn")

# 新用户默认密码
DEFAULT_PASSWORD = "myk123456"


# ── 请求/响应模型 ──────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False


class LoginResponse(BaseModel):
    token: str
    username: str
    display_name: Optional[str] = None
    is_admin: bool = False


class CreateUserRequest(BaseModel):
    username: str
    display_name: Optional[str] = None
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    password: Optional[str] = None  # 重置密码


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: Optional[str] = None
    is_admin: bool
    is_active: bool
    created_at: str


# ── 登录 ──────────────────────────────────────────────────

@router.post("/auth/login", response_model=ApiResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录，返回 JWT 令牌"""
    result = await db.execute(
        select(User).where(User.username == req.username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token = create_access_token(str(user.id), user.username, user.is_admin)
    logger.info(f"用户 {user.username} 登录成功")

    return ApiResponse(
        message="登录成功",
        data=LoginResponse(
            token=token,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
        ),
    )


@router.get("/auth/me", response_model=ApiResponse)
async def get_me(user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return ApiResponse(
        data=UserResponse(
            id=str(user.id),
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else None,
        ),
    )


# ── 修改密码 ──────────────────────────────────────────────

@router.post("/auth/change-password", response_model=ApiResponse)
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户修改自己的密码"""
    if not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 个字符")

    user.hashed_password = hash_password(req.new_password)
    await db.commit()
    logger.info(f"用户 {user.username} 修改了密码")
    return ApiResponse(message="密码修改成功")


# ── 用户管理（仅管理员）──────────────────────────────────

@router.get("/auth/users", response_model=ApiResponse)
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取所有用户列表（管理员）"""
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return ApiResponse(
        data=[
            UserResponse(
                id=str(u.id),
                username=u.username,
                display_name=u.display_name,
                is_admin=u.is_admin,
                is_active=u.is_active,
                created_at=u.created_at.isoformat() if u.created_at else None,
            )
            for u in users
        ],
    )


@router.post("/auth/users", response_model=ApiResponse)
async def create_user(
    req: CreateUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员创建新用户，默认密码 myk123456"""
    result = await db.execute(select(User).where(User.username == req.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="用户名已存在")

    user = User(
        username=req.username,
        hashed_password=hash_password(DEFAULT_PASSWORD),
        display_name=req.display_name,
        is_admin=req.is_admin,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    logger.info(f"管理员 {admin.username} 创建了用户 {user.username}，默认密码: {DEFAULT_PASSWORD}")
    return ApiResponse(
        message=f"用户创建成功，默认密码: {DEFAULT_PASSWORD}",
        data=UserResponse(
            id=str(user.id),
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else None,
        ),
    )


@router.put("/auth/users/{user_id}", response_model=ApiResponse)
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员更新用户信息 / 重置密码"""
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if req.display_name is not None:
        user.display_name = req.display_name
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.is_admin is not None:
        user.is_admin = req.is_admin
    if req.password:
        user.hashed_password = hash_password(req.password)

    await db.commit()
    logger.info(f"管理员 {admin.username} 更新了用户 {user.username}")
    return ApiResponse(message="用户更新成功")


@router.delete("/auth/users/{user_id}", response_model=ApiResponse)
async def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员删除用户"""
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    await db.delete(user)
    await db.commit()
    logger.info(f"管理员 {admin.username} 删除了用户 {user.username}")
    return ApiResponse(message="用户删除成功")

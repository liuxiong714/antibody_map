"""认证 API：登录、用户管理、修改密码"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_admin
from app.core.audit import log_audit
from app.core.rate_limiter import login_rate_limit
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from app.core.token_revocation import is_token_revoked, revoke_token, token_issued_before_password_change
from app.models.user import User
from app.schemas.common import ApiResponse

router = APIRouter()

logger = logging.getLogger("uvicorn")

# 新用户默认密码（从环境变量读取，未配置时使用硬编码默认值）
DEFAULT_PASSWORD = "myk123456"


# ── 请求/响应模型 ──────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False


class LoginResponse(BaseModel):
    token: str
    refresh_token: str = ""
    username: str
    display_name: Optional[str] = None
    is_admin: bool = False


class RefreshTokenRequest(BaseModel):
    refresh_token: str


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


# ── 密码校验 ──────────────────────────────────────────────

def _validate_password_strength(password: str) -> Optional[str]:
    """校验密码强度，返回错误信息或 None"""
    if len(password) < 8:
        return "密码至少 8 个字符"
    if not re.search(r"[A-Z]", password):
        return "密码需包含至少一个大写字母"
    if not re.search(r"[a-z]", password):
        return "密码需包含至少一个小写字母"
    if not re.search(r"\d", password):
        return "密码需包含至少一个数字"
    return None


# ── 登录 ──────────────────────────────────────────────────

@router.post("/auth/login", response_model=ApiResponse, summary="用户登录", description="用户登录认证，验证用户名和密码，返回JWT访问令牌和刷新令牌")
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(login_rate_limit),
):
    """用户登录，返回 JWT 令牌"""
    result = await db.execute(
        select(User).where(User.username == req.username)
    )
    user = result.scalar_one_or_none()
    client_ip = request.client.host if request.client else None

    # F5：统一判定，避免向攻击者泄露"用户名是否存在"
    if not user or not verify_password(req.password, user.hashed_password):
        failed_username = req.username
        await log_audit(
            db, "login_failed", username=failed_username,
            client_ip=client_ip, detail={"reason": "invalid_credentials"},
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        await log_audit(
            db, "login_failed", user_id=str(user.id), username=req.username,
            client_ip=client_ip, detail={"reason": "inactive"},
        )
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token = create_access_token(str(user.id), user.username, user.is_admin)
    refresh_token = create_refresh_token(str(user.id))

    await log_audit(
        db, "login", user_id=str(user.id), username=user.username,
        client_ip=client_ip,
    )

    return ApiResponse(
        message="登录成功",
        data=LoginResponse(
            token=token,
            refresh_token=refresh_token,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
        ),
    )


# ── 刷新令牌 ──────────────────────────────────────────────

@router.post("/auth/refresh", response_model=ApiResponse, summary="刷新访问令牌", description="使用刷新令牌换取新的访问令牌，用于保持登录状态")
async def refresh_token(
    req: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """用刷新令牌换取新的访问令牌（轮换 + 重放拒绝，fail-closed）"""
    payload = decode_refresh_token(req.refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="刷新令牌无效或已过期")

    jti = payload.get("jti")
    # fail-closed：吊销的检查与"标记已用"写操作任一因 Redis 故障失败，
    # 一律拒绝刷新（503），绝不静默放行，保证重放保护不被绕过。
    try:
        if jti and await is_token_revoked(jti):
            raise HTTPException(status_code=401, detail="刷新令牌已被使用，请重新登录")
        # 轮换：将当前 refresh token 标记为已使用（含剩余的撤回保护期）
        if jti:
            await revoke_token(jti, payload.get("exp"))
    except HTTPException:
        raise
    except RedisError as e:
        logger.warning(f"刷新令牌吊销校验失败，拒绝刷新（fail-closed）: {e}")
        raise HTTPException(status_code=503, detail="令牌验证服务暂不可用，请稍后重试")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    # F3：改密后旧 refresh token 一并失效（签发早于改密的令牌拒绝续期）
    if token_issued_before_password_change(payload.get("iat"), user.password_changed_at):
        raise HTTPException(status_code=401, detail="密码已变更，请重新登录")

    new_token = create_access_token(str(user.id), user.username, user.is_admin)
    new_refresh_token = create_refresh_token(str(user.id))

    return ApiResponse(
        data=LoginResponse(
            token=new_token,
            refresh_token=new_refresh_token,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
        ),
    )


# ── 退出登录 ──────────────────────────────────────────────

@router.post("/auth/logout", response_model=ApiResponse, summary="用户登出", description="退出登录，吊销当前访问令牌，使其失效")
async def logout(
    authorization: str | None = Header(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """退出登录：吊销当前访问令牌"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        payload = decode_access_token(token)
        if payload and payload.get("jti"):
            try:
                await revoke_token(payload["jti"], payload.get("exp"))
            except RedisError as e:
                # 登出吊销为尽力而为：Redis 不可用时记录并继续，不让登出硬失败。
                # （验证路径已 fail-closed，登出本身不构成安全放行窗口。）
                logger.warning(f"登出吊销访问令牌失败: {e}")
    await log_audit(db, "logout", user_id=str(user.id), username=user.username)
    return ApiResponse(message="退出登录成功")


@router.get("/auth/me", response_model=ApiResponse, summary="获取当前用户信息", description="获取当前登录用户的详细信息，包括用户名、显示名、角色等")
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

@router.post("/auth/change-password", response_model=ApiResponse, summary="修改密码", description="当前用户修改自己的密码，需验证原密码，新密码需满足强度要求（至少8位，含大小写字母和数字）")
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户修改自己的密码"""
    if not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")

    err = _validate_password_strength(req.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)

    user.hashed_password = hash_password(req.new_password)
    user.password_changed_at = datetime.now(timezone.utc)  # F3：改密后吊销所有旧令牌
    await db.commit()
    await log_audit(db, "change_password", user_id=str(user.id), username=user.username)
    return ApiResponse(message="密码修改成功")


# ── 用户管理（仅管理员）──────────────────────────────────

@router.get("/auth/users", response_model=ApiResponse, summary="获取用户列表", description="管理员获取所有用户列表，按创建时间排序")
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


@router.post("/auth/users", response_model=ApiResponse, summary="创建用户", description="管理员创建新用户，默认密码为myk123456，可指定用户名、显示名和是否为管理员")
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
    await log_audit(
        db, "create_user", user_id=str(admin.id), username=admin.username,
        target=req.username, detail={"is_admin": req.is_admin},
    )
    return ApiResponse(
        message="用户创建成功",
        data=UserResponse(
            id=str(user.id),
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else None,
        ),
    )


@router.put("/auth/users/{user_id}", response_model=ApiResponse, summary="更新用户信息", description="管理员更新用户信息，可以修改显示名、激活状态、管理员权限，以及重置密码")
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
        err = _validate_password_strength(req.password)
        if err:
            raise HTTPException(status_code=400, detail=err)
        user.hashed_password = hash_password(req.password)
        user.password_changed_at = datetime.now(timezone.utc)  # F3：重置密码后吊销该用户所有旧令牌

    await db.commit()
    await log_audit(
        db, "update_user", user_id=str(admin.id), username=admin.username,
        target=user.username,
        detail={"is_active": req.is_active, "is_admin": req.is_admin, "password_reset": bool(req.password)},
    )
    return ApiResponse(message="用户更新成功")


@router.delete("/auth/users/{user_id}", response_model=ApiResponse, summary="删除用户", description="管理员删除指定用户，不能删除自己")
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

    target_username = user.username
    await db.delete(user)
    await db.commit()
    await log_audit(
        db, "delete_user", user_id=str(admin.id), username=admin.username,
        target=target_username,
    )
    return ApiResponse(message="用户删除成功")

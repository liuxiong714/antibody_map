import uuid
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.core.token_revocation import is_token_revoked
from app.models.base import async_session
from app.models.user import User


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Authorization 头解析 JWT 令牌，返回当前登录用户"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")

    # 检查 Token 是否已被吊销（退出登录后）
    jti = payload.get("jti")
    if jti and await is_token_revoked(jti):
        raise HTTPException(status_code=401, detail="令牌已被吊销，请重新登录")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """要求当前用户是管理员"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user

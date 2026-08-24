"""认证安全工具：密码哈希 + JWT 令牌签发/验证"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from app.config import settings

# JWT 配置
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 2       # 访问令牌有效期 2 小时
REFRESH_TOKEN_EXPIRE_DAYS = 7       # 刷新令牌有效期 7 天


def _get_secret() -> str:
    """获取 JWT 签名密钥：开发环境随机生成，生产环境必须显式配置。"""
    if settings.SECRET_KEY:
        return settings.SECRET_KEY
    if settings.APP_ENV == "development":
        return secrets.token_hex(32)  # 本地开发：每次启动随机，不持久
    raise RuntimeError("生产环境必须配置 SECRET_KEY")


def hash_password(password: str, rounds: int = 12) -> str:
    """对明文密码进行 bcrypt 哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与哈希是否匹配"""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, username: str, is_admin: bool = False) -> str:
    """签发访问令牌（短有效期）"""
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": user_id,
        "username": username,
        "is_admin": is_admin,
        "exp": expire,
        "iat": datetime.now(timezone.utc),   # F3：签发时间，用于改密后吊销旧令牌
        "jti": uuid.uuid4().hex,      # 唯一令牌 ID，用于后续吊销
        "type": "access",
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """签发刷新令牌（长有效期，仅用于换取新的 access token）"""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),   # F3：签发时间，用于改密后吊销旧令牌
        "jti": uuid.uuid4().hex,
        "type": "refresh",
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """解析访问令牌，失败返回 None"""
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.PyJWTError:
        return None


def decode_refresh_token(token: str) -> Optional[dict]:
    """解析刷新令牌，失败返回 None"""
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        return payload
    except jwt.PyJWTError:
        return None

"""API Key 加密存储工具

使用 Fernet 对称加密（AES-128-CBC + HMAC-SHA256）保护敏感凭证。
密钥从 settings.SECRET_KEY 派生，未配置时使用 RuntimeError 拒绝启动。

密钥派生版本：
- V1：sha256(secret).digest() → base64  （存量密文，兼容读取）
- V2：HKDF-SHA256(salt="antibody-map-apikey-v2", info="fernet", length=32).base64 （新写入）

解密先试 V2，InvalidToken 再试 V1，**两次都失败则 raise ValueError**
（绝不返回密文原值给调用方——避免密文被误发为 API Key 的安全事故）。
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

logger = logging.getLogger("uvicorn")

# Fernet 密文固定前缀，用于判断是否已加密
_FERNET_TOKEN_PREFIX = "gAAAAA"

# HKDF v2 派生参数
_HKDF_SALT = b"antibody-map-apikey-v2"
_HKDF_INFO = b"fernet"


def _derive_key_v1(secret: str) -> bytes:
    """V1 派生（sha256，存量兼容）"""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _derive_key_v2(secret: str) -> bytes:
    """V2 派生（HKDF-SHA256，新写入）"""
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))


def _build_fernet_pair(secret: str) -> tuple[Fernet, Fernet]:
    """同时构建 v2 (primary, 新写入) + v1 (fallback, 兼容存量) Fernet"""
    if not secret:
        raise RuntimeError(
            "SECRET_KEY 未配置，无法派生加密密钥。"
            "请确保 .env 中 SECRET_KEY 已配置且长度 >= 32。"
        )
    return Fernet(_derive_key_v2(secret)), Fernet(_derive_key_v1(secret))


# 模块级单例：v2 主实例 + v1 兼容实例
try:
    _fernet_v2, _fernet_v1 = _build_fernet_pair(settings.SECRET_KEY)
except RuntimeError:
    # SECRET_KEY 缺失时延迟初始化（待首次调用 encrypt/decrypt 时再抛）
    _fernet_v2 = _fernet_v1 = None


def encrypt(plaintext: str) -> str:
    """加密明文（使用 V2 HKDF 派生的密钥），返回 Fernet 密文字符串"""
    if not plaintext:
        return ""
    if _fernet_v2 is None:
        _init_lazy()
    token = _fernet_v2.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def _init_lazy() -> None:
    """SECRET_KEY 缺失时延迟初始化（避免模块导入即 RuntimeError）"""
    global _fernet_v2, _fernet_v1
    if _fernet_v2 is None:
        _fernet_v2, _fernet_v1 = _build_fernet_pair(settings.SECRET_KEY)


def decrypt(ciphertext: str) -> str:
    """解密密文，返回明文。

    安全约定：
    - 若非密文格式（历史明文、None、空）→ 直接返回原值（迁移平滑）
    - 是密文格式：先试 V2 密钥解密 → InvalidToken 再试 V1 密钥 →
      **两次都失败 raise ValueError("API_KEY_DECRYPT_FAILED")**
      ——不再返回密文原值给调用方（避免密文被当作 API Key 外发）
    """
    if not ciphertext:
        return ""
    # 已是密文格式才尝试解密
    if ciphertext.startswith(_FERNET_TOKEN_PREFIX):
        if _fernet_v2 is None:
            _init_lazy()
        enc = ciphertext.encode("utf-8")
        # V2 优先（新密文）
        try:
            return _fernet_v2.decrypt(enc).decode("utf-8")
        except InvalidToken:
            pass
        # V1 回退（存量密文）
        try:
            plain = _fernet_v1.decrypt(enc).decode("utf-8")
            logger.info("API Key 用 V1(sha256) 密钥成功解密，下次保存将自动升级到 V2")
            return plain
        except InvalidToken:
            logger.error(
                "API Key 解密失败（V2+V1 均 InvalidToken），"
                "可能 SECRET_KEY 已变更或密文损坏。"
            )
            raise ValueError("API_KEY_DECRYPT_FAILED")
    # 历史明文直接返回
    return ciphertext


def mask(api_key: str) -> str:
    """生成 API Key 的掩码形式，用于对外响应"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:3]}***{api_key[-3:]}"


def is_encrypted(value: str) -> bool:
    """判断字符串是否为 Fernet 密文格式"""
    return bool(value) and value.startswith(_FERNET_TOKEN_PREFIX)

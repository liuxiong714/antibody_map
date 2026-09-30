"""API Key 加密存储工具

使用 Fernet 对称加密（AES-128-CBC + HMAC-SHA256）保护敏感凭证。
密钥从 settings 派生：**C7 起与 JWT 的 SECRET_KEY 分离**，优先使用独立
CRYPTO_KEY（未配置时回退 SECRET_KEY，保证存量部署零配置迁移）。
两者均未配置时使用 RuntimeError 拒绝启动。

密钥派生版本：
- V1：sha256(SECRET_KEY).digest() → base64  （历史密文，兼容读取）
- V2(新)：HKDF-SHA256(CRYPTO_KEY 或 SECRET_KEY)  （C7 之后新写入）
- V2(旧)：HKDF-SHA256(SECRET_KEY)  （C7 之前存量密文，仅在 CRYPTO_KEY 单独配置时存在）

解密链：V2(新) → V2(旧) → V1，**全部 InvalidToken 则 raise ValueError**
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


def _crypto_secret() -> str:
    """C7：加密密钥来源——优先独立 CRYPTO_KEY，未配置回退 SECRET_KEY。

    存量部署未配置 CRYPTO_KEY 时，此函数返回 SECRET_KEY，行为与 C7 前完全一致
    （新写入密钥不变、解密链仍由 SECRET_KEY 派生），实现零配置向后兼容。
    """
    return settings.CRYPTO_KEY or settings.SECRET_KEY


def _build_fernet_trio(primary_secret: str, legacy_secret: str) -> tuple[Fernet, Fernet | None, Fernet]:
    """构建三级解密链 Fernet 实例：

    - primary：由 primary_secret（CRYPTO_KEY 或 SECRET_KEY）HKDF-V2 派生，新写入用
    - legacy_v2：由 legacy_secret（SECRET_KEY）HKDF-V2 派生，兼容 C7 前存量密文；
      与 primary_secret 相同时（未单独配置 CRYPTO_KEY）返回 None 避免重复尝试
    - v1：sha256(legacy_secret) 派生，历史密文兜底

    任一 secret 为空时 raise RuntimeError，拒绝静默使用弱密钥启动。
    """
    if not primary_secret or not legacy_secret:
        raise RuntimeError(
            "SECRET_KEY/CRYPTO_KEY 均未配置，无法派生加密密钥。"
            "请确保 .env 中 SECRET_KEY 已配置且长度 >= 32（建议同时单独配置 CRYPTO_KEY）。"
        )
    primary = Fernet(_derive_key_v2(primary_secret))
    legacy_v2 = None
    if legacy_secret != primary_secret:
        legacy_v2 = Fernet(_derive_key_v2(legacy_secret))
    v1 = Fernet(_derive_key_v1(legacy_secret))
    return primary, legacy_v2, v1


# 模块级单例：新 v2 主实例 + 旧 v2 兼容实例 + v1 历史实例
try:
    _fernet_primary, _fernet_legacy_v2, _fernet_v1 = _build_fernet_trio(
        _crypto_secret(), settings.SECRET_KEY
    )
except RuntimeError:
    # 密钥缺失时延迟初始化（待首次调用 encrypt/decrypt 时再抛）
    _fernet_primary = _fernet_legacy_v2 = _fernet_v1 = None


def encrypt(plaintext: str) -> str:
    """加密明文（使用新密钥 HKDF-V2 派生，C7 起为 CRYPTO_KEY 派生），返回 Fernet 密文字符串"""
    if not plaintext:
        return ""
    if _fernet_primary is None:
        _init_lazy()
    token = _fernet_primary.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def _init_lazy() -> None:
    """密钥缺失时延迟初始化（避免模块导入即 RuntimeError）"""
    global _fernet_primary, _fernet_legacy_v2, _fernet_v1
    if _fernet_primary is None:
        _fernet_primary, _fernet_legacy_v2, _fernet_v1 = _build_fernet_trio(
            _crypto_secret(), settings.SECRET_KEY
        )


def decrypt(ciphertext: str) -> str:
    """解密密文，返回明文。

    安全约定：
    - 若非密文格式（历史明文、None、空）→ 直接返回原值（迁移平滑）
    - 是密文格式：依次尝试 新V2(CRYPTO_KEY) → 旧V2(SECRET_KEY) → V1(sha256) →
      **全部失败 raise ValueError("API_KEY_DECRYPT_FAILED")**
      ——不再返回密文原值给调用方（避免密文被当作 API Key 外发）
    """
    if not ciphertext:
        return ""
    # 已是密文格式才尝试解密
    if ciphertext.startswith(_FERNET_TOKEN_PREFIX):
        if _fernet_primary is None:
            _init_lazy()
        enc = ciphertext.encode("utf-8")
        # 新 V2 优先（CRYPTO_KEY 派生的新密文）
        try:
            return _fernet_primary.decrypt(enc).decode("utf-8")
        except InvalidToken:
            pass
        # 旧 V2 回退（C7 前 SECRET_KEY 派生的存量密文）
        if _fernet_legacy_v2 is not None:
            try:
                plain = _fernet_legacy_v2.decrypt(enc).decode("utf-8")
                logger.info("API Key 用旧 V2(SECRET_KEY) 密钥成功解密，下次保存将升级到新密钥")
                return plain
            except InvalidToken:
                pass
        # V1 回退（历史密文）
        try:
            plain = _fernet_v1.decrypt(enc).decode("utf-8")
            logger.info("API Key 用 V1(sha256) 密钥成功解密，下次保存将自动升级到 V2")
            return plain
        except InvalidToken:
            logger.error(
                "API Key 解密失败（新V2+旧V2+V1 均 InvalidToken），"
                "可能 CRYPTO_KEY/SECRET_KEY 已变更或密文损坏。"
            )
            raise ValueError("API_KEY_DECRYPT_FAILED") from None
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

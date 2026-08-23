"""API Key 加密存储工具

使用 Fernet 对称加密（AES-128-CBC + HMAC-SHA256）保护敏感凭证。
密钥从 settings.SECRET_KEY 派生，未配置时使用开发回退密钥并打印警告。

设计要点：
- 列名保持 `api_key` 不变，存储密文，兼容历史数据
- decrypt() 对非密文（历史明文）自动透传，平滑迁移
- 提供 mask() 生成对外响应的掩码字符串
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger("uvicorn")

# SECRET_KEY 为空时的开发回退密钥（仅用于本地开发，生产环境必须配置 SECRET_KEY）
# 已移除 — 见 _derive_key 中的 RuntimeError 检查

# Fernet 密文固定前缀（base64 编码后的版本字节），用于判断是否已加密
_FERNET_TOKEN_PREFIX = "gAAAAA"


def _derive_key(secret: str) -> bytes:
    """从任意长度的 SECRET_KEY 派生 Fernet 兼容的 32 字节密钥"""
    if not secret:
        raise RuntimeError(
            "SECRET_KEY 未配置，无法派生加密密钥。"
            "请确保 .env 中 SECRET_KEY 已配置且长度 >= 32。"
        )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


# 模块级单例 Fernet 实例（首次导入时初始化）
_fernet = Fernet(_derive_key(settings.SECRET_KEY))


def encrypt(plaintext: str) -> str:
    """加密明文，返回 Fernet 密文字符串

    Args:
        plaintext: 明文 API Key

    Returns:
        Fernet 密文（base64 字符串）；空输入返回空字符串
    """
    if not plaintext:
        return ""
    token = _fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """解密密文，返回明文

    采用容错策略：解密失败（如历史明文、密钥变更）时返回原值，
    保证旧数据不丢失，便于平滑迁移。

    Args:
        ciphertext: Fernet 密文或历史明文

    Returns:
        解密后的明文；空输入返回空字符串
    """
    if not ciphertext:
        return ""
    # 已是密文格式才尝试解密
    if ciphertext.startswith(_FERNET_TOKEN_PREFIX):
        try:
            return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.warning("API Key 解密失败（可能 SECRET_KEY 已变更），返回原值")
            return ciphertext
    # 历史明文直接返回（迁移脚本会逐步加密）
    return ciphertext


def mask(api_key: str) -> str:
    """生成 API Key 的掩码形式，用于对外响应

    Examples:
        "sk-abcdef1234567890" -> "sk-***890"
        "abc" -> "abc"（过短不掩码）
        "" -> ""
    """
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:3]}***{api_key[-3:]}"


def is_encrypted(value: str) -> bool:
    """判断字符串是否为 Fernet 密文格式"""
    return bool(value) and value.startswith(_FERNET_TOKEN_PREFIX)

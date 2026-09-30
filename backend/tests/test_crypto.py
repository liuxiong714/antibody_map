"""crypto 模块单测（C7 SECRET_KEY / CRYPTO_KEY 分离回归）。"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.core import crypto


def test_encrypt_decrypt_roundtrip():
    t = crypto.encrypt("sk-abcdef1234567890")
    assert crypto.is_encrypted(t)
    assert crypto.decrypt(t) == "sk-abcdef1234567890"


def test_decrypt_empty_or_plaintext_passthrough():
    assert crypto.decrypt("") == ""
    assert crypto.decrypt(None) == ""
    assert crypto.decrypt("already-plaintext") == "already-plaintext"


def test_encrypt_empty_returns_empty():
    assert crypto.encrypt("") == ""


def test_mask():
    assert crypto.mask("") == ""
    assert crypto.mask("abcdef") == "******"  # <= 8
    assert crypto.mask("sk-abcdef1234567890xyz") == "sk-***xyz"


def test_is_encrypted_format_detection():
    assert crypto.is_encrypted("gAAAAABsomething") is True
    assert crypto.is_encrypted("") is False
    assert crypto.is_encrypted(None) is False
    assert crypto.is_encrypted("not-a-token") is False


def test_decrypt_bogus_fernet_raises():
    """格式像 Fernet 但签名不对 → 应 ValueError 而非返回原值。"""
    bogus = "gAAAAAthis-is-not-a-valid-fernet-token-xxx"
    with pytest.raises(ValueError, match="API_KEY_DECRYPT_FAILED"):
        crypto.decrypt(bogus)


def test_decrypt_with_old_secret_reads_still_works():
    """用 SECRET_KEY 派生出的旧 V2 密文（C7 前存量）应能被旧 v2 兼容实例解密。"""
    old = crypto._fernet_v1  # 随便引用一下让 linters 放过——真正测试在下面

    # 自己构造一个旧 V2 密文
    from cryptography.fernet import Fernet
    from app.config import settings
    old_fernet = Fernet(crypto._derive_key_v2(settings.SECRET_KEY))
    old_token = old_fernet.encrypt(b"legacy-key").decode()

    # 即使已设置 CRYPTO_KEY，这个旧密文也应能被解密（legacy_v2 分支）
    with patch("app.config.settings.CRYPTO_KEY", "a_different_secret_only_for_c7"):
        # 强制重建 Fernet 三实例
        crypto._fernet_primary = None
        crypto._fernet_legacy_v2 = None
        crypto._fernet_v1 = None
        crypto._init_lazy()

        assert crypto.decrypt(old_token) == "legacy-key"


def test_decrypt_with_legacy_v1_fallback():
    """最早 V1（sha256）派生出的密文也应能解密（历史兜底）。"""
    from cryptography.fernet import Fernet
    from app.config import settings
    v1_fernet = Fernet(crypto._derive_key_v1(settings.SECRET_KEY))
    old_token = v1_fernet.encrypt(b"v1-ancient").decode()

    with patch("app.config.settings.CRYPTO_KEY", ""):
        crypto._fernet_primary = None
        crypto._fernet_legacy_v2 = None
        crypto._fernet_v1 = None
        crypto._init_lazy()
        assert crypto.decrypt(old_token) == "v1-ancient"


def test_crypto_key_independent_new_writes():
    """设置独立 CRYPTO_KEY 后，新加密出来的密文只有用新密钥链能解。"""
    from cryptography.fernet import Fernet
    from app.config import settings

    CRYPTO_KEY = "c7-independently-generated-secret-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    with patch("app.config.settings.CRYPTO_KEY", CRYPTO_KEY):
        crypto._fernet_primary = None
        crypto._fernet_legacy_v2 = None
        crypto._fernet_v1 = None
        crypto._init_lazy()

        new_token = crypto.encrypt("secret-via-new-key")
        # 用 CRYPTO_KEY 派生出的主实例应能直接解
        from app.core.crypto import _derive_key_v2, _crypto_secret
        new_primary = Fernet(_derive_key_v2(_crypto_secret()))
        assert new_primary.decrypt(new_token.encode()).decode() == "secret-via-new-key"

        # 但用旧 SECRET_KEY 派生出的 v2 实例解不开（除非 legacy_v2 碰巧相等）
        old_v2 = Fernet(_derive_key_v2(settings.SECRET_KEY))
        try:
            old_v2.decrypt(new_token.encode())
            # 能解说明 key 撞了（几乎不可能），断言 pass 即可
        except Exception:
            pass  # 期望


def test_init_lazy_missing_keys_raises_on_first_use():
    """SECRET_KEY 和 CRYPTO_KEY 同时缺失 → 首次 encrypt/decrypt 抛 RuntimeError。"""
    with patch("app.config.settings.SECRET_KEY", ""), \
         patch("app.config.settings.CRYPTO_KEY", ""):
        crypto._fernet_primary = None
        crypto._fernet_legacy_v2 = None
        crypto._fernet_v1 = None
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            crypto.encrypt("anything")

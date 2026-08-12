"""encrypt_api_keys

加密 api_model_config 表中已有的明文 api_key（Fernet 对称加密）。
此迁移不修改表结构，仅做数据迁移：将历史明文 api_key 转为 Fernet 密文。
列名保持 api_key 不变，业务层通过 hybrid_property 透明解密。

Revision ID: encrypt_api_keys
Revises: add_api_model_config
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'encrypt_api_keys'
down_revision: Union[str, Sequence[str], None] = 'add_api_model_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic")


def upgrade() -> None:
    """将 api_model_config 表中的明文 api_key 加密为 Fernet 密文"""
    from app.core.crypto import encrypt, is_encrypted

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, api_key FROM api_model_config")
    ).fetchall()

    if not rows:
        logger.info("api_model_config 表为空，无需迁移")
        return

    migrated = 0
    skipped = 0
    for row in rows:
        row_id, raw_key = row[0], row[1]
        # 跳过空值或已加密的记录
        if not raw_key:
            skipped += 1
            continue
        if is_encrypted(raw_key):
            skipped += 1
            continue
        # 加密并更新
        encrypted = encrypt(raw_key)
        conn.execute(
            sa.text("UPDATE api_model_config SET api_key = :enc WHERE id = :rid"),
            {"enc": encrypted, "rid": row_id},
        )
        migrated += 1

    logger.info(
        f"api_key 加密迁移完成：加密 {migrated} 条，跳过 {skipped} 条（空值或已加密）"
    )


def downgrade() -> None:
    """回滚：将 Fernet 密文解密回明文"""
    from app.core.crypto import decrypt, is_encrypted

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, api_key FROM api_model_config")
    ).fetchall()

    if not rows:
        return

    reverted = 0
    for row in rows:
        row_id, raw_key = row[0], row[1]
        if not raw_key or not is_encrypted(raw_key):
            continue
        plain = decrypt(raw_key)
        conn.execute(
            sa.text("UPDATE api_model_config SET api_key = :p WHERE id = :rid"),
            {"p": plain, "rid": row_id},
        )
        reverted += 1

    logger.info(f"api_key 解密回滚完成：恢复 {reverted} 条")

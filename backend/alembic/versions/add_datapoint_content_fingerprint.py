"""add_datapoint_content_fingerprint

V2-05: DataPoint 加 content_fingerprint — 7 字段去重 key 的 SHA256 指纹。

根因: A6 跨批次查重只有应用层前置查询 (extract_task.py:1260-1295)，
多 Celery worker 并发时存在 TOCTOU 竞态，仍可能写入重复点。

改法（严格三步，分别提交 — 本迁移只做第一步）:
  Step 1 (本文件): ADD COLUMN content_fingerprint VARCHAR(64) IF NOT NULL
  Step 2 (独立脚本): 回填 fingerprints + 审计存量重复（--dry-run 先报数）
  Step 3 (独立脚本): 建部分唯一索引（事务外执行）

指纹算法 (与 extract_task.py:1282 一致):
  sha256(f"{disease}|{province}|{city}|{data_type}|{age_min}|{age_max}|{collection_year}|{round(value,6)}")
  所有 None 值统一为 "NULL" 字符串。
"""
from __future__ import annotations

from alembic import op

revision = "add_datapoint_content_fingerprint"
down_revision = "add_datapoint_review_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: 加列（可空，回填脚本再填值，避免大表重写）
    op.execute(
        "ALTER TABLE data_point ADD COLUMN IF NOT EXISTS content_fingerprint "
        "VARCHAR(64) DEFAULT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE data_point DROP COLUMN IF EXISTS content_fingerprint")

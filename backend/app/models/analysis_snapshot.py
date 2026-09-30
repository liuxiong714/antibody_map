"""分析快照模型：记录分析查询的可复现参数与数据指纹。

用于「分析请求可复现」：
- 每次 /analysis/* GET 请求旁路写入一条快照（同参数同 data_hash 去重复用）；
- data_hash 由过滤后数据点 (id, review_status, value) 有序列表的 sha256 前 16 位构成；
- 通过快照 token 可重放参数直出结果 / 生成引用文本。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalysisSnapshot(Base):
    __tablename__ = "analysis_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 分析模块标识（与 methodology 的 module key 对齐，如 trend / foi / immune_barrier）
    module: Mapped[str] = mapped_column(String(50), index=True)
    # 复现所需的完整查询参数（JSONB，服务层 kwargs，不含 db）
    params: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    # 过滤后 (id, review_status, value) 有序列表 sha256 前 16 位
    data_hash: Mapped[str] = mapped_column(String(32), index=True)
    # 生成快照时的完整分析响应（含 meta），供重放"不重新计算则缓存响应 json"
    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        # 去重复用查询：同模块 + 同数据指纹
        Index("ix_snapshot_module_hash", "module", "data_hash"),
        # 并发安全的按(模块+指纹+完整过滤参数)去重：保证同参数同结果只写入一条
        UniqueConstraint(
            "module", "data_hash", "params",
            name="uq_snapshot_identity",
        ),
    )

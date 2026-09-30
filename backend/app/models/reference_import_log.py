"""题录导入日志模型

记录每次题录导入操作的详细信息，包括文件路径、导入数量、操作人等。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReferenceImportLog(Base):
    """题录导入日志"""
    __tablename__ = "reference_import_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 导入的文件名
    file_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    # 导入时间
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    # 识别总数（解析出的题录条数）
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 剔除数量（重复/无效的条数）
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 实际导入数量
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 操作人用户名
    operator_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 格式（auto / ris / enw / pubmed / wos / woscsv / duxiu）
    fmt: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    # 操作人 ID（可选）
    operator_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
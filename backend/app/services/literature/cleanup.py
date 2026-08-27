import uuid
from typing import Optional

from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.services.literature._common import (
    logger,
)
from app.services.literature.crud import (
    delete_literature,
)


async def batch_delete_literatures(
    db: AsyncSession,
    literature_ids: list[uuid.UUID],
    deleted_by: Optional[uuid.UUID] = None,
) -> int:
    """批量软删除文献：逐篇设置 deleted_at，跳过已在回收站中的记录，返回实际删除数。"""
    if not literature_ids:
        return 0
    deleted = 0
    for lit_id in literature_ids:
        try:
            if await delete_literature(db, lit_id, deleted_by=deleted_by):
                deleted += 1
        except Exception as e:
            logger.warning(f"[文献] 批量软删除失败跳过: id={lit_id}, err={e}")
    return deleted


async def cleanup_empty_literatures(
    db: AsyncSession,
    dry_run: bool = True,
) -> dict:
    """清理既无文档又无摘要的文献记录。

    返回 {"preview_count": int, "deleted_count": int}。
    - dry_run=True: 只统计不删除
    - dry_run=False: 执行删除
    """
    # 仅清理未删除（不在回收站）的既无文档又无摘要的文献，与列表查询口径一致
    stmt = select(Literature).where(
        and_(
            Literature.deleted_at.is_(None),
            Literature.file_path.is_(None),
            func.coalesce(Literature.abstract, '') == '',
        )
    ).order_by(Literature.created_at.desc())
    result = await db.execute(stmt)
    lits = result.scalars().all()
    preview_count = len(lits)

    # 返回候选文献明细，供前端列出具体是哪些文献
    items = [
        {
            "id": str(lit.id),
            "title": lit.title or "",
            "created_at": lit.created_at.isoformat() if lit.created_at else None,
        }
        for lit in lits
    ]

    if dry_run:
        return {"preview_count": preview_count, "deleted_count": 0, "items": items}

    if not lits:
        return {"preview_count": 0, "deleted_count": 0, "items": []}

    ids = [lit.id for lit in lits]
    deleted = await batch_delete_literatures(db, ids)
    return {"preview_count": preview_count, "deleted_count": deleted, "items": items}
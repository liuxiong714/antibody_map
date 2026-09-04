"""数据点质量评分异步任务（审核通过后触发，幂等更新）。"""
import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from app.models.base import async_session
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.task")


def _score_with_literature_text(dp: DataPoint, literature_text: str | None) -> dict:
    """纯同步包装，便于在任务内同步调用评分纯函数。"""
    from app.services.quality_service import score_data_point

    return score_data_point(dp, literature_text=literature_text)


async def _load_literature_text(db, literature_id) -> str | None:
    """加载可用于抽样判定的文献文本：优先摘要；有全文文件时再尝试全文（失败不阻塞）。"""
    result = await db.execute(
        select(Literature.abstract, Literature.file_path).where(
            Literature.id == literature_id
        )
    )
    row = result.first()
    if not row:
        return None
    abstract, file_path = row[0], row[1]

    # 摘要已足够做离线标注
    if abstract and len(abstract.strip()) >= 20:
        return abstract

    # 尝试全文解析（复用 extract_task 的本地/MinIO 查找策略，仅在有文件时尝试）
    if file_path:
        try:
            from app.core.document_parser import extract_text
            from app.tasks.extract_task import _download_pdf

            file_bytes = _download_pdf(file_path)
            if file_bytes:
                text = extract_text(file_bytes, Path(file_path).suffix.lower())
                if text and len(text.strip()) >= 20:
                    return text
        except Exception as e:  # 解析失败不阻塞打分（退化为元数据粗打）
            logger.warning(f"质量打分全文解析失败（退化元数据打分）: {e}")
    return None


@celery_app.task(bind=True, max_retries=2, acks_late=True)
def score_data_point_task(self, data_point_id: str):
    """异步质量打分（幂等）：审核通过后先用元数据粗打，全文可用后再精打覆盖。"""
    async def _run():
        async with async_session() as db:
            dp = await db.get(DataPoint, uuid.UUID(data_point_id))
            if dp is None or dp.review_status != "approved":
                return {"status": "skipped", "reason": "not_approved_or_missing"}

            literature_text = None
            if dp.literature_id:
                literature_text = await _load_literature_text(db, dp.literature_id)

            result = _score_with_literature_text(dp, literature_text)
            dp.quality_score = result["quality_score"]
            dp.quality_grade = result["quality_grade"]
            dp.estimate_grade = result["estimate_grade"]
            await db.commit()
            return {
                "status": "scored",
                "quality_score": result["quality_score"],
                "quality_grade": result["quality_grade"],
                "estimate_grade": result["estimate_grade"],
                "used_fulltext": literature_text is not None,
            }

    try:
        return run_async(_run())
    except Exception as e:
        logger.error(f"数据点质量打分失败 dp={data_point_id}: {e}")
        raise self.retry(exc=e) from e

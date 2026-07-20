import asyncio
import logging
from typing import Optional

from sqlalchemy import select

from app.config import settings
from app.core.llm_extractor import LLMExtractor
from app.core.pdf_parser import extract_text as pdf_extract_text
from app.core.text_preprocessor import preprocess
from app.models.base import async_session
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.tasks.celery_app import celery_app
from app.core.minio_client import get_minio_client

logger = logging.getLogger("celery.task")


def _download_pdf(object_name: str) -> Optional[bytes]:
    """从 MinIO 下载 PDF 文件"""
    client = get_minio_client()
    if client is None:
        logger.error("MinIO 不可用，无法下载文件")
        return None

    try:
        response = client.get_object(
            bucket_name=settings.MINIO_BUCKET_LITERATURE,
            object_name=object_name,
        )
        data = response.read()
        response.close()
        response.release_conn()
        return data
    except Exception as e:
        logger.error(f"MinIO 下载失败: {e}")
        return None


def _extract_result_to_datapoints(
    literature_id: str,
    extract_result: dict,
) -> list[DataPoint]:
    """将 LLM 提取结果转换为 DataPoint 列表（血清阳性率 + GMC）"""
    data_points = []

    common = {
        "literature_id": literature_id,
        "disease": extract_result.get("disease_name"),
        "province": extract_result.get("province"),
        "city": extract_result.get("city"),
        "age_min": extract_result.get("age_min"),
        "age_max": extract_result.get("age_max"),
        "sample_size": extract_result.get("sample_size"),
        "method": extract_result.get("detection_method"),
        "assay": extract_result.get("antibody_type"),
        "population": extract_result.get("population_type"),
        "collection_year": extract_result.get("sample_year") or extract_result.get("study_start_year"),
        "review_status": "pending",
        "confidence": "medium",
    }

    # 血清阳性率数据点
    if extract_result.get("positivity_rate") is not None:
        dp_sp = DataPoint(
            data_type="seroprevalence",
            value=extract_result["positivity_rate"],
            unit="%",
            ci_lower=extract_result.get("positivity_ci_lower"),
            ci_upper=extract_result.get("positivity_ci_upper"),
            **common,
        )
        data_points.append(dp_sp)

    # GMC 数据点
    if extract_result.get("gmc_value") is not None:
        dp_gmc = DataPoint(
            data_type="gmc",
            value=extract_result["gmc_value"],
            unit=extract_result.get("gmc_unit"),
            ci_lower=extract_result.get("gmc_ci_lower"),
            ci_upper=extract_result.get("gmc_ci_upper"),
            **common,
        )
        data_points.append(dp_gmc)

    return data_points


async def _process_literature_async(
    literature_id: str,
    model: Optional[str] = None,
) -> dict:
    """异步文献处理：PDF 解析 → LLM 提取 → 保存数据点"""
    async with async_session() as db:
        # 1. 查找文献记录
        result = await db.execute(
            select(Literature).where(Literature.id == literature_id)
        )
        literature = result.scalar_one_or_none()
        if not literature:
            raise ValueError(f"文献不存在: {literature_id}")

        if not literature.file_path:
            raise ValueError("文献无关联 PDF 文件")

        # 2. 下载 PDF 文件
        file_bytes = _download_pdf(literature.file_path)
        if not file_bytes:
            raise RuntimeError("PDF 文件下载失败")

        # 3. 解析 PDF 文本
        raw_text = pdf_extract_text(file_bytes)
        if not raw_text:
            raise RuntimeError("PDF 解析后文本为空")

        # 4. 预处理文本
        clean_text = preprocess(raw_text)

        # 5. LLM 提取
        extractor = LLMExtractor(model=model)
        extract_result = await extractor.extract(
            text=clean_text,
            language="zh",
            title=literature.title or "",
            journal=literature.journal or "",
            pub_year=literature.pub_year,
        )

        # 6. 创建 DataPoint 记录
        data_points = _extract_result_to_datapoints(literature_id, extract_result)
        for dp in data_points:
            db.add(dp)

        # 7. 更新文献元信息（LLM 提取的作者/杂志/摘要）
        if extract_result.get("authors") and not literature.authors:
            literature.authors = extract_result["authors"]
        if extract_result.get("author_affiliations"):
            pass  # 暂不单独存储，保留在 extracted_data 中
        if extract_result.get("journal") and not literature.journal:
            literature.journal = extract_result["journal"]

        # 8. 更新 literature 状态
        literature.extraction_status = "done"
        literature.extracted_count = len(data_points)

        await db.commit()

        return {
            "literature_id": literature_id,
            "extracted_count": len(data_points),
            "extract_result": extract_result,
        }


@celery_app.task(bind=True, max_retries=3)
def process_literature(self, literature_id: str, model: Optional[str] = None):
    """Celery 任务：文献处理（PDF 解析 + AI 提取）"""
    try:
        result = asyncio.run(_process_literature_async(literature_id, model))
        logger.info(f"文献 {literature_id} 提取完成，数据点: {result['extracted_count']}")
        return result

    except Exception as e:
        logger.error(f"文献 {literature_id} 提取失败: {e}")

        # 更新状态为 failed
        async def _mark_failed():
            async with async_session() as db:
                result = await db.execute(
                    select(Literature).where(Literature.id == literature_id)
                )
                lit = result.scalar_one_or_none()
                if lit:
                    lit.extraction_status = "failed"
                    await db.commit()

        try:
            asyncio.run(_mark_failed())
        except Exception:
            pass

        # 重试
        retry_in = 60 * (2 ** self.request.retries)
        raise self.retry(exc=e, countdown=retry_in)

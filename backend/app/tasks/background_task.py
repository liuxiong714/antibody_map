"""后台长任务 Celery 任务：报告生成（三类）与知识图谱抽取。

这些任务此前在 FastAPI HTTP 同步请求内执行，改为 Celery 后台异步后，
通过 Redis-backed 注册表（app.core.redis_background_tasks）上报运行进度，
供 backend /system/active-tasks 与前端轮询读取。

worker 与 backend 共享同一 Redis（Celery broker），天然跨进程可见状态。
"""
import logging
import traceback
from pathlib import Path

from app.config import settings
from app.core import redis_background_tasks as bg
from app.models.base import async_session
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.task")

_TEXT_DIR = Path("/app/backend/data/pdfs")


# ===================== 报告生成 =====================

@celery_app.task(bind=True, max_retries=0, soft_time_limit=3600, time_limit=4200)
def run_report_generation(
    self,
    language: str = "zh",
    disease: str | None = None,
    province: str | None = None,
    data_type: str | None = None,
    title: str | None = None,
    model: str | None = None,
    template_id: str | None = None,
    kind: str = "antibody",
):
    """后台生成免疫学报告（kind: antibody | barrier）。"""
    task_id = self.request.id  # 始终使用 Celery 任务 id，保证 API 返回的 task_id 与 Redis 状态 key 一致
    run_async(bg.start("report_generation", task_id=task_id, kind=_kind_label(kind), disease=disease, province=province, title=title, model=model))
    try:
        data = run_async(__run_report_generation(
            task_id, language, disease, province, data_type, title, model, template_id, kind
        ))
        return data
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error(f"后台报告生成失败（{kind}）: {err}\n{traceback.format_exc()}")
        run_async(bg.finish("report_generation", task_id, status="failed", error=err))
        raise


@celery_app.task(bind=True, max_retries=0, soft_time_limit=3600, time_limit=4200)
def run_vaccination_strategy(
    self,
    task_type: str,
    task_time: str,
    task_location: str,
    personnel_count: int,
    personnel_gender: str = "",
    personnel_age: str = "",
    personnel_vaccination_history: str = "",
    title: str | None = None,
    template_id: str | None = None,
    model: str | None = None,
):
    """后台生成疫苗接种策略研判报告。"""
    task_id = self.request.id
    run_async(bg.start("report_generation", task_id=task_id, kind="疫苗接种策略报告", title=title, model=model, task_location=task_location))
    try:
        data = run_async(__run_vaccination_strategy(
            task_id, task_type, task_time, task_location, personnel_count,
            personnel_gender, personnel_age, personnel_vaccination_history,
            title, template_id, model,
        ))
        return data
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error(f"后台疫苗接种策略报告生成失败: {err}\n{traceback.format_exc()}")
        run_async(bg.finish("report_generation", task_id, status="failed", error=err))
        raise


# ===================== 知识图谱抽取 =====================

@celery_app.task(bind=True, max_retries=0, soft_time_limit=3600, time_limit=4200)
def run_kg_extraction(
    self,
    scope: str = "auto",
    limit: int = 5,
    literature_ids: list | None = None,
):
    """后台执行 LLM 三元组抽取。

    scope: auto（自动批量，从全部未抽取缓存文本取前 limit 篇）或 directed（定向）。
    literature_ids: 定向抽取的目标文献 id；省略时自动批量。
    """
    task_id = self.request.id
    run_async(bg.start("kg_extraction", task_id=task_id, scope=scope))
    try:
        result = run_async(__run_kg_extraction(task_id, scope, limit, literature_ids))
        return result
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error(f"后台知识图谱抽取失败: {err}\n{traceback.format_exc()}")
        run_async(bg.finish("kg_extraction", task_id, status="failed", error=err))
        raise


# ===================== 内部实现 =====================

def _kind_label(kind: str) -> str:
    return "免疫屏障评估报告" if kind == "barrier" else "抗体分析报告"


async def __run_report_generation(task_id, language, disease, province, data_type, title, model, template_id, kind):
    from app.services.report_service import generate_immune_barrier_report, generate_report

    async with async_session() as db:
        if task_id:
            await bg.update("report_generation", task_id, status="running", progress="正在查询数据点")
        try:
            if kind == "barrier":
                data = await generate_immune_barrier_report(
                    db=db, disease=disease, province=province, data_type=data_type,
                    language=language, title=title, model=model, template_id=template_id,
                )
            else:
                data = await generate_report(
                    db=db, disease=disease, province=province, data_type=data_type,
                    language=language, title=title, model=model, template_id=template_id,
                )
        except Exception as e:
            if task_id:
                await bg.finish("report_generation", task_id, status="failed", error=f"{type(e).__name__}: {e}")
            raise

        if task_id:
            await bg.update("report_generation", task_id, progress="报告已生成，正在保存")
        report_id = data.get("id")
        if task_id:
            await bg.finish("report_generation", task_id, status="done", result={"report_id": report_id})
        return data


async def __run_vaccination_strategy(task_id, task_type, task_time, task_location, personnel_count,
                                     personnel_gender, personnel_age, personnel_vaccination_history,
                                     title, template_id, model):
    from app.services.report_service import generate_vaccination_strategy_report

    async with async_session() as db:
        if task_id:
            await bg.update("report_generation", task_id, status="running", progress="正在查询任务地点疫情数据")
        try:
            data = await generate_vaccination_strategy_report(
                db=db, task_type=task_type, task_time=task_time, task_location=task_location,
                personnel_count=personnel_count, personnel_gender=personnel_gender,
                personnel_age=personnel_age, personnel_vaccination_history=personnel_vaccination_history,
                title=title, template_id=template_id, model=model,
            )
        except Exception as e:
            if task_id:
                await bg.finish("report_generation", task_id, status="failed", error=f"{type(e).__name__}: {e}")
            raise

        report_id = data.get("id")
        if task_id:
            await bg.finish("report_generation", task_id, status="done", result={"report_id": report_id})
        return data


async def __run_kg_extraction(task_id, scope, limit, literature_ids):
    from sqlalchemy import select

    from app.models.kg_entity import KGEntity
    from app.models.literature import Literature
    from app.services.kg_llm_integration import run_kg_extraction as _run_one

    if not _TEXT_DIR.exists():
        await bg.finish("kg_extraction", task_id, status="failed", error="缓存文本目录不存在")
        return {"processed": 0, "total_written": 0, "remaining": 0, "errors": ["缓存文本目录不存在"]}

    async with async_session() as db:
        done_stmt = select(KGEntity.source_literature_id).where(KGEntity.source_literature_id.isnot(None))
        done_result = await db.execute(done_stmt)
        already = {str(r) for r in done_result.scalars().all()}

        txt_ids = [p.stem for p in _TEXT_DIR.glob("*.txt")]

        if literature_ids:
            requested = {str(i) for i in literature_ids}
            candidates = [i for i in txt_ids if i in requested]
        else:
            candidates = txt_ids

        todo = [i for i in candidates if i not in already]
        if not todo:
            await bg.finish("kg_extraction", task_id, status="done",
                            result={"processed": 0, "total_written": 0, "remaining": 0})
            return {"processed": 0, "total_written": 0, "remaining": 0}

        chunk = todo[:limit]
        processed = 0
        total_written = 0
        errors = []
        if task_id:
            await bg.update("kg_extraction", task_id, status="running", processed=processed, total=len(chunk))

        for lit_id in chunk:
            txt_path = _TEXT_DIR / f"{lit_id}.txt"
            try:
                clean_text = txt_path.read_text(encoding="utf-8")
            except Exception:
                errors.append(f"{lit_id}: 读文本失败")
                continue
            if len(clean_text) < 100:
                continue

            row = await db.execute(
                select(Literature.title, Literature.journal, Literature.pub_year).where(Literature.id == lit_id)
            )
            title, journal, pub_year = row.first() or (None, None, None)

            # 跳过已删除（软删除/硬删除）的文献：只查 title 等字段不校验 deleted_at，
            # 若 row.first() 为 None 则说明该文献记录已被物理删除，直接跳过以免后续
            # kg_entity 插入时 source_literature_id 外键约束失败。
            if title is None:
                errors.append(f"{lit_id}: 文献记录不存在（可能已被删除）")
                continue

            try:
                written = await _run_one(
                    db=db,
                    text=clean_text,
                    literature_id=lit_id,
                    title=title or "",
                    journal=journal or "",
                    pub_year=pub_year,
                    model=settings.LLM_MODEL,
                    api_key="",
                    base_url=settings.LLM_BASE_URL,
                )
                total_written += written
                processed += 1
            except TimeoutError:
                errors.append(f"{lit_id}: 超时")
                logger.warning(f"文献 {lit_id} 抽取超时（后台）")
            except Exception as e:
                errors.append(f"{lit_id}: {type(e).__name__}")
                logger.error(f"文献 {lit_id} 抽取失败（后台）", exc_info=True)
            if task_id:
                await bg.update("kg_extraction", task_id, processed=processed)

        if task_id:
            await bg.finish("kg_extraction", task_id, status="done",
                            result={"processed": processed, "total_written": total_written, "remaining": len(todo) - len(chunk), "errors": errors})
        return {"processed": processed, "total_written": total_written, "remaining": len(todo) - len(chunk), "errors": errors}
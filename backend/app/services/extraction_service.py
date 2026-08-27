import asyncio
import logging
import uuid
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, func, update, delete as sa_delete, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.literature import Literature
from app.models.data_point import DataPoint
from app.models.extraction_history import ExtractionHistory
from app.models.api_model_config import ApiModelConfig
from app.models.base import async_session
from app.tasks.extract_task import process_literature

logger = logging.getLogger("uvicorn")


# P1-6：同省+同病+同年+同类型 已审核数据点的冲突检测阈值
#   seroprevalence：相对差异 ≥ 50% 且绝对差异 ≥ 10 个百分点（避免低值噪声）
#   gmc：相对差异 ≥ 50%
CONFLICT_RELATIVE_THRESHOLD = 0.5
CONFLICT_ABS_THRESHOLD_SEROPREVALENCE = 10.0


def _relative_diff(a: float, b: float) -> float:
    """相对差异 = |a-b| / max(|a|,|b|)；两者皆为 0 时为 0。"""
    if a == 0 and b == 0:
        return 0.0
    base = max(abs(a), abs(b))
    return abs(a - b) / base if base > 0 else 0.0


def _is_conflict(data_type: str, value: float, existing_value: float) -> bool:
    rel = _relative_diff(value, existing_value)
    if rel < CONFLICT_RELATIVE_THRESHOLD:
        return False
    if data_type == "seroprevalence" and abs(value - existing_value) < CONFLICT_ABS_THRESHOLD_SEROPREVALENCE:
        return False
    return True


async def compute_data_point_conflicts(
    db: AsyncSession,
    data_points: list[DataPoint],
) -> dict[str, list[dict]]:
    """P1-6：为数据点查找「同省+同病+同年+同类型」已审核通过的主估计数据点并计算差异。

    仅比较 estimate_type='primary' 的数据点（避免子估计与汇总值误判冲突）；
    排除同一文献内的数据点，聚焦跨文献的「已有数据」对比。
    返回 {dp_id_str: [{literature_id, literature_title, value, unit, sample_size,
                       collection_year, relative_diff, conflict}]}
    """
    conflicts: dict[str, list[dict]] = {}
    candidates = [
        dp for dp in data_points
        if dp.estimate_type == "primary"
        and dp.province and dp.disease and dp.collection_year
        and dp.value is not None and dp.data_type
    ]
    if not candidates:
        return conflicts

    keys = {
        (dp.province, dp.disease, dp.collection_year, dp.data_type)
        for dp in candidates
    }
    own_lit_ids = {dp.literature_id for dp in candidates if dp.literature_id}

    stmt = (
        select(DataPoint, Literature.title)
        .join(Literature, DataPoint.literature_id == Literature.id)
        .where(Literature.deleted_at.is_(None))
        .where(DataPoint.review_status == "approved")
        .where(DataPoint.estimate_type == "primary")
        .where(DataPoint.value.is_not(None))
        .where(
            tuple_(
                DataPoint.province, DataPoint.disease,
                DataPoint.collection_year, DataPoint.data_type,
            ).in_(keys)
        )
    )
    if own_lit_ids:
        stmt = stmt.where(DataPoint.literature_id.notin_(own_lit_ids))
    existing_rows = (await db.execute(stmt)).all()

    from collections import defaultdict

    by_key: dict[tuple, list[tuple[DataPoint, str]]] = defaultdict(list)
    for edp, title in existing_rows:
        by_key[(edp.province, edp.disease, edp.collection_year, edp.data_type)].append((edp, title))

    for dp in candidates:
        matches = by_key.get((dp.province, dp.disease, dp.collection_year, dp.data_type), [])
        if not matches:
            continue
        rels = []
        for edp, title in matches:
            rel = _relative_diff(float(dp.value), float(edp.value))
            rels.append({
                "literature_id": str(edp.literature_id) if edp.literature_id else None,
                "literature_title": title or "",
                "value": float(edp.value),
                "unit": edp.unit,
                "sample_size": edp.sample_size,
                "collection_year": edp.collection_year,
                "relative_diff": round(rel, 4),
                "conflict": _is_conflict(dp.data_type, float(dp.value), float(edp.value)),
            })
        conflicts[str(dp.id)] = rels

    return conflicts


def _metadata_quality_breakdown(dp: DataPoint) -> dict | None:
    """元数据级质量明细（无文献全文时的实时估算，仅用于前端 Tooltip 展示）。

    有全文时以异步任务落库的 quality_score/quality_grade 为准；此处仅给出六项分项。
    """
    try:
        from app.services.quality_service import score_data_point

        result = score_data_point(dp, literature_text=None)
        return result["breakdown"]
    except Exception as e:  # 评分失败不应影响列表加载
        logger.warning(f"质量明细估算失败: {e}")
        return None


async def trigger_extraction(
    db: AsyncSession,
    literature_id: uuid.UUID,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_config_id: Optional[str] = None,
    clear_existing_data: bool = False,
    use_cache: bool = True,
) -> dict:
    """触发文献 AI 提取任务（通过 Celery 异步执行）

    安全说明：前端自定义的 api_key/base_url 会先加密存入 ApiModelConfig，
    任务参数只传递 model_config_id，避免明文凭证出现在 Redis 队列中。
    """
    # 检查文献存在
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = result.scalar_one_or_none()
    if not literature:
        raise ValueError("文献不存在")

    if not literature.file_path and not literature.abstract:
        raise ValueError("文献既无 PDF 文件也无摘要，无法提取")

    # == 竞态防护：原子抢占，防止并发对同一文献重复触发提取 ==
    # 仅当状态非 processing/queued 时才允许置为 queued；rowcount=0 表示已被其他请求占用
    claimed = await db.execute(
        update(Literature)
        .where(Literature.id == literature_id)
        .where(Literature.extraction_status.notin_(["processing", "queued"]))
        .values(
            extraction_status="queued",
            extraction_started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    if claimed.rowcount == 0:
        # 重新读取当前状态以给出准确提示（尽力而为）
        cur = (
            await db.execute(
                select(Literature.extraction_status).where(Literature.id == literature_id)
            )
        ).scalar_one_or_none()
        raise ValueError(
            f"文献正在提取中（当前状态: {cur or 'unknown'}），请等待完成后再试"
        )

    # == 安全处理：如果前端提供了自定义 api_key，先加密存入 ApiModelConfig ==
    # 任务参数只传 model_config_id，不传明文 api_key/base_url
    resolved_model_config_id = model_config_id
    if api_key and not model_config_id:
        # 创建临时 ApiModelConfig，加密存储 api_key/base_url，并设置 24h 过期 TTL
        # （过期后由后台清理任务自动删除，避免明文凭证长期滞留数据库）
        from datetime import timedelta
        temp_config = ApiModelConfig(
            name=f"临时提取配置-{model or 'default'}",
            model_name=model or "",
            base_url=base_url or "",
            is_active=False,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        # 通过 hybrid_property setter 自动加密
        temp_config.api_key = api_key
        db.add(temp_config)
        await db.flush()
        resolved_model_config_id = str(temp_config.id)
        logger.info(f"前端自定义 API Key 已加密存入 ApiModelConfig(id={temp_config.id})")

    # 提交到 Celery 队列异步执行（失败标记与重试由任务自身处理）
    lit_id_str = str(literature_id)
    process_literature.delay(
        literature_id=lit_id_str,
        model=model,
        model_config_id=resolved_model_config_id,
        clear_existing_data=clear_existing_data,
        use_cache=use_cache,
    )

    return {
        "literature_id": lit_id_str,
        "status": "queued",
    }


async def get_extraction_status(
    db: AsyncSession,
    literature_id: uuid.UUID,
) -> dict:
    """获取提取状态"""
    result = await db.execute(
        select(Literature).where(Literature.id == literature_id)
    )
    literature = result.scalar_one_or_none()
    if not literature:
        raise ValueError("文献不存在")

    # 查询数据点数量
    count_result = await db.execute(
        select(func.count(DataPoint.id)).where(
            DataPoint.literature_id == literature_id
        )
    )
    data_point_count = count_result.scalar() or 0

    return {
        "literature_id": str(literature_id),
        "status": literature.extraction_status,
        "extracted_count": literature.extracted_count,
        "approved_count": literature.approved_count,
        "data_point_count": data_point_count,
        # LLM token 用量与费用（提取完成时写入，未提取时为默认值）
        "llm_model_used": literature.llm_model_used,
        "prompt_tokens": literature.prompt_tokens or 0,
        "completion_tokens": literature.completion_tokens or 0,
        "total_tokens": literature.total_tokens or 0,
        "llm_cost_usd": float(literature.llm_cost_usd) if literature.llm_cost_usd is not None else 0.0,
        "llm_call_count": literature.llm_call_count or 0,
        "llm_usage_detail": literature.llm_usage_detail,
    }


async def get_extraction_results(
    db: AsyncSession,
    literature_id: uuid.UUID,
) -> list[dict]:
    """获取提取的数据点列表"""
    result = await db.execute(
        select(DataPoint).where(
            DataPoint.literature_id == literature_id
        ).order_by(DataPoint.created_at.desc())
    )
    data_points = result.scalars().all()

    # 一次性解析审核人姓名（reviewer_id -> display_name/username）
    from app.models.user import User

    reviewer_ids = {dp.reviewer_id for dp in data_points if dp.reviewer_id}
    reviewer_names: dict[uuid.UUID, str] = {}
    if reviewer_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(reviewer_ids)))
        ).scalars().all()
        reviewer_names = {u.id: (u.display_name or u.username) for u in users}

    # P1-6：同省同病同年已有已审核数据点冲突对比（审核页只读提示）
    conflicts = await compute_data_point_conflicts(db, data_points)

    return [
        {
            "id": str(dp.id),
            "disease": dp.disease,
            "region": dp.region,
            "province": dp.province,
            "city": dp.city,
            "data_type": dp.data_type,
            "value": float(dp.value) if dp.value else None,
            "unit": dp.unit,
            "ci_lower": float(dp.ci_lower) if dp.ci_lower else None,
            "ci_upper": float(dp.ci_upper) if dp.ci_upper else None,
            "sample_size": dp.sample_size,
            "method": dp.method,
            "assay": dp.assay,
            "population": dp.population,
            "age_min": dp.age_min,
            "age_max": dp.age_max,
            "collection_year": dp.collection_year,
            "source_page": dp.source_page,
            "source_context": dp.source_context,
            # P0 新增：精确字符级溯源
            "source_char_start": dp.source_char_start,
            "source_char_end": dp.source_char_end,
            "is_grounded": bool(dp.is_grounded),
            "confidence": dp.confidence,
            "review_status": dp.review_status,
            "review_comment": dp.review_comment,
            "reviewer_id": str(dp.reviewer_id) if dp.reviewer_id else None,
            "reviewer_name": reviewer_names.get(dp.reviewer_id) if dp.reviewer_id else None,
            "reviewed_at": dp.reviewed_at.isoformat() if dp.reviewed_at else None,
            # 质量分级（审核通过后异步打分写入；breakdown 为元数据级实时估算，用于前端 Tooltip 明细）
            "quality_score": dp.quality_score,
            "quality_grade": dp.quality_grade,
            "estimate_grade": dp.estimate_grade,
            "quality_breakdown": _metadata_quality_breakdown(dp),
            # P1-6：同省同病同年已有已审核数据点冲突对比（审核页只读提示）
            "conflicts": conflicts.get(str(dp.id), []),
            "created_at": dp.created_at.isoformat() if dp.created_at else None,
            "updated_at": dp.updated_at.isoformat() if dp.updated_at else None,
        }
        for dp in data_points
    ]


async def get_extraction_history(
    db: AsyncSession,
    literature_id: uuid.UUID,
) -> list[dict]:
    """获取文献的 AI 提取历史记录"""
    result = await db.execute(
        select(ExtractionHistory).where(
            ExtractionHistory.literature_id == literature_id
        ).order_by(ExtractionHistory.extracted_at.desc())
    )
    history_list = result.scalars().all()

    return [
        {
            "id": str(h.id),
            "extracted_at": h.extracted_at.isoformat() if h.extracted_at else None,
            "model": h.model,
            "status": h.status,
            "data_point_count": h.data_point_count,
            "error_message": h.error_message,
            "prompt_tokens": h.prompt_tokens,
            "completion_tokens": h.completion_tokens,
            "total_tokens": h.total_tokens,
            "llm_cost_usd": float(h.llm_cost_usd) if h.llm_cost_usd is not None else 0.0,
            "llm_call_count": h.llm_call_count,
            "llm_usage_detail": h.llm_usage_detail,
            "duration_seconds": float(h.duration_seconds) if h.duration_seconds is not None else None,
        }
        for h in history_list
    ]


async def review_data_points(
    db: AsyncSession,
    literature_id: uuid.UUID,
    ids: list[str],
    status: str,
    comment: Optional[str],
    reviewer_id: uuid.UUID,
) -> int:
    """批量审核数据点：写入审核意见、审核人与审核时间。

    审核状态固定为 status（approved/rejected），仅覆盖给定 ids 且属于该文献的数据点。
    返回受影响行数。调用方负责 commit。
    """
    uuids = [uuid.UUID(i) for i in ids]
    now = datetime.now(timezone.utc)
    stmt = (
        update(DataPoint)
        .where(DataPoint.id.in_(uuids))
        .where(DataPoint.literature_id == literature_id)
        .values(
            review_status=status,
            review_comment=comment,
            reviewer_id=reviewer_id,
            reviewed_at=now,
        )
    )
    result = await db.execute(stmt)
    return result.rowcount


async def get_review_stats(db: AsyncSession) -> dict:
    """审核统计：按疾病 / 审核人维度聚合审核量、通过率、平均审核时间。

    平均审核时间 = approved 与 rejected 均视为已审核，取 reviewed_at 与 created_at 的分钟差均值。
    """
    from app.models.user import User

    reviewed_rows = (
        select(
            DataPoint.disease,
            DataPoint.reviewer_id,
            DataPoint.review_status,
            DataPoint.reviewed_at,
            DataPoint.created_at,
        )
        .where(DataPoint.review_status.in_(("approved", "rejected")))
        .where(DataPoint.reviewed_at.is_not(None))
    )
    rows = (await db.execute(reviewed_rows)).all()

    def _fold(items):
        total = len(items)
        approved = sum(1 for st, _, _ in items if st == "approved")
        durations = [
            (rv - created).total_seconds() / 60.0
            for st, rv, created in items
            if rv and created and rv > created
        ]
        avg_min = round(sum(durations) / len(durations), 2) if durations else None
        return {
            "reviewed": total,
            "approved": approved,
            "rejected": total - approved,
            "pass_rate": round(approved / total, 4) if total else 0.0,
            "avg_review_minutes": avg_min,
        }

    # 按疾病聚合
    by_disease: dict[str, list] = {}
    for disease, _rid, st, rv, created in rows:
        key = disease or "未知"
        by_disease.setdefault(key, []).append((st, rv, created))
    total_by_disease = [
        {"disease": key, **_fold(items)} for key, items in by_disease.items()
    ]
    total_by_disease.sort(key=lambda x: x["reviewed"], reverse=True)

    # 按审核人聚合（汇总用户 id -> 名称）
    reviewer_ids = {r.reviewer_id for r in rows if r.reviewer_id}
    reviewer_names: dict[uuid.UUID, str] = {}
    if reviewer_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(reviewer_ids)))
        ).scalars().all()
        reviewer_names = {
            u.id: (u.display_name or u.username or str(u.id)) for u in users
        }

    by_reviewer: dict[uuid.UUID, list] = {}
    for _disease, rid, st, rv, created in rows:
        if not rid:
            continue
        by_reviewer.setdefault(rid, []).append((st, rv, created))
    total_by_reviewer = [
        {
            "reviewer_id": str(rid),
            "reviewer_name": reviewer_names.get(rid, "未知用户"),
            **_fold(items),
        }
        for rid, items in by_reviewer.items()
    ]
    total_by_reviewer.sort(key=lambda x: x["reviewed"], reverse=True)

    all_items = [(st, rv, created) for _d, _r, st, rv, created in rows]
    return {
        "grand_total": _fold(all_items),
        "by_disease": total_by_disease,
        "by_reviewer": total_by_reviewer,
    }


async def cleanup_expired_model_configs() -> int:
    """删除所有已过期的临时 ApiModelConfig（TTL 自动回收）。

    返回删除条数。防止单次提取注入的自定义凭证（api_key/base_url）长期滞留数据库。
    """
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = sa_delete(ApiModelConfig).where(
            ApiModelConfig.expires_at.isnot(None),
            ApiModelConfig.expires_at < now,
        )
        result = await db.execute(stmt)
        await db.commit()
        deleted = result.rowcount or 0
        if deleted:
            logger.info(f"已清理 {deleted} 条过期的临时模型配置")
        return deleted


async def _expired_model_config_cleanup_loop(interval: int = 3600) -> None:
    """后台循环：定期清理过期的临时 ApiModelConfig（默认每小时一次）。"""
    while True:
        try:
            await cleanup_expired_model_configs()
        except Exception as e:
            logger.warning(f"清理过期模型配置失败: {e}")
        await asyncio.sleep(interval)

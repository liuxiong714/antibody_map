"""每病保护目标阈值配置服务。

阈值以数据库表 goal_threshold_config 为可配置来源（迁移时以
app.core.goal_thresholds.GOAL_THRESHOLDS 默认值种子化），管理员可通过
系统设置 API 调整；未配置/已重置的疾病回退到 GOAL_THRESHOLDS 硬编码默认值。
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.goal_thresholds import GOAL_THRESHOLDS
from app.core.term_normalizer import normalize_disease
from app.models.goal_threshold_config import GoalThresholdConfig

logger = logging.getLogger("uvicorn")


def _norm_key(disease: str | None) -> str:
    return normalize_disease(disease) or (disease or "").strip().lower()


async def get_goal_threshold(db: AsyncSession, disease_key: str) -> float | None:
    """获取某疾病的保护目标阈值（%）：优先查配置表，未覆盖时回退默认值。"""
    result = await db.execute(
        select(GoalThresholdConfig.threshold_percent).where(
            GoalThresholdConfig.disease == disease_key
        )
    )
    row = result.scalars().first()
    if row is not None:
        return float(row)
    return GOAL_THRESHOLDS.get(disease_key)


async def list_goal_thresholds(db: AsyncSession) -> list[dict]:
    """列出全部疾病的有效保护目标阈值（配置表 + 默认值合并）。"""
    result = await db.execute(select(GoalThresholdConfig))
    cfg_rows = {r.disease: r for r in result.scalars().all()}
    diseases = sorted(set(GOAL_THRESHOLDS) | set(cfg_rows))
    items = []
    for key in diseases:
        default = GOAL_THRESHOLDS.get(key)
        cfg = cfg_rows.get(key)
        value = cfg.threshold_percent if cfg else default
        items.append({
            "disease": key,
            "threshold_percent": value,
            "is_default": cfg is None or value == default,
            "updated_at": cfg.updated_at.isoformat() if cfg and cfg.updated_at else None,
            "updated_by": cfg.updated_by if cfg else None,
        })
    return items


async def upsert_goal_threshold(
    db: AsyncSession,
    disease: str,
    threshold_percent: float,
    updated_by: str | None = None,
) -> dict:
    """新增或更新某疾病的保护目标阈值（管理员调用）。"""
    key = _norm_key(disease)
    if not key:
        raise ValueError("疾病名称无效")
    if threshold_percent is None or not (0 <= threshold_percent <= 100):
        raise ValueError("阈值必须为 0-100 之间的百分比数值")
    result = await db.execute(
        select(GoalThresholdConfig).where(GoalThresholdConfig.disease == key)
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        db.add(GoalThresholdConfig(
            disease=key,
            threshold_percent=threshold_percent,
            updated_by=updated_by,
        ))
    else:
        cfg.threshold_percent = threshold_percent
        cfg.updated_by = updated_by
        cfg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"disease": key, "threshold_percent": threshold_percent}


async def delete_goal_threshold(db: AsyncSession, disease: str) -> bool:
    """删除某疾病的阈值覆盖，恢复为默认值（管理员调用）。"""
    key = _norm_key(disease)
    result = await db.execute(
        delete(GoalThresholdConfig).where(GoalThresholdConfig.disease == key)
    )
    await db.commit()
    return result.rowcount > 0

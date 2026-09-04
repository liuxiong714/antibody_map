"""分析快照服务：数据指纹(data_hash)、快照去重写入、重放与引用文本生成。

设计（「分析请求可复现」）：
- 每次 /analysis/* GET 请求旁路写入一条快照：同参数(module, params, data_hash)
  去重复用，响应 meta 注入 ``snapshot_token``（uuid）。
- ``data_hash`` = 过滤后数据点 (id, review_status, value) 有序列表的
  sha256 前 16 位；数据变更 → hash 变化 → 新 token。
- ``response_json`` 缓存生成时的完整分析响应，供重放直出（不重新计算）。
- ``build_citation`` 生成 GBT7714 / BibTeX 引用文本（含版本号与访问日期）。
"""

import asyncio
import functools
import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import logger
from app.models.analysis_snapshot import AnalysisSnapshot
from app.models.data_point import DataPoint
from app.models.literature import Literature
from app.schemas.common import ApiResponse
from app.services import analysis_service

# 数据库/口径版本（引用文本与快照元数据标注用）
DB_VERSION = "v1.0"
DB_NAME = "抗体地图数据库"

# 参与哈希取数的标准筛选参数（与 _build_base_query 对齐）
_STD_FILTER_KEYS = ("disease", "province", "year_start", "year_end",
                    "age_min", "age_max", "data_type")

# 哈希取数 SELECT 的额外统计/分组字段（任一变化都应使 data_hash 变化）
_HASH_EXTRA_FIELDS = (
    "sample_size", "ci_lower", "ci_upper", "disease", "province",
    "collection_year", "data_type", "age_min", "age_max", "quality_grade",
)


# ---------------------------------------------------------------------------
# 数据指纹
# ---------------------------------------------------------------------------
def _norm_value(v: Any) -> str:
    """把 value 规范化为确定性的字符串（int/float/bool/None 稳定表示）。"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        # 避免 25.0 / 25 歧义；浮点统一用 repr（25.0 → '25.0'）
        return repr(v)
    return str(v)


def calculate_data_hash(rows: Any) -> str:
    """对过滤后数据点行计算 sha256 前 16 位。

    ``rows`` 可为 SQLAlchemy 结果（DataPoint 或 with_only_columns 的 Row），
    统一按 id 升序排列保证确定性。参与哈希的字段覆盖 id / review_status /
    value 及影响分析结果的统计与分组字段（见 _HASH_EXTRA_FIELDS），任一字段
    变化都会使 hash 变化，保证与各分析模块的实际口径一致。
    """
    triplets: list[list[str]] = []
    for r in rows:
        rid = r.id if hasattr(r, "id") else r[0]
        rs = r.review_status if hasattr(r, "review_status") else (r[1] if len(r) > 1 else "")
        val = r.value if hasattr(r, "value") else (r[2] if len(r) > 2 else None)
        rec = [str(rid), str(rs or ""), _norm_value(val)]
        # 关键统计/分组字段：缺失时按 None 归一，保证旧行（仅 3 列）兼容
        for key in _HASH_EXTRA_FIELDS:
            rec.append(_norm_value(getattr(r, key, None)))
        triplets.append(rec)
    triplets.sort(key=lambda t: t[0])  # 按 id 有序
    payload = json.dumps(triplets, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 哈希取数查询（镜像 _build_base_query 的过滤语义）
# ---------------------------------------------------------------------------
def _build_hash_query(filter_keys: tuple[str, ...], params: dict,
                      data_type_override: str | None = None,
                      review_status: str | None = "approved",
                      quality_filter_key: str | None = None,
                      include_subgroups: bool | None = None):
    """构造哈希取数查询：与 analysis_service._build_base_query 语义一致。

    - filter_keys: 参与过滤的 params 键名；
    - data_type_override: 强制 data_type（如 meta/equity 固定 seroprevalence）；
    - review_status: 审核状态过滤；None 表示不过滤（data_gaps/coverage_review 统计全状态）；
    - quality_filter_key: 参数键名，False/缺省时仅取 A/B 级（meta 类证据门槛）；
    - include_subgroups: True 时不过滤 estimate_type（含子估计，与 vaccine 等模块一致）；
      None/False 时默认仅主估计。
    """
    fk = {k: params.get(k) for k in filter_keys if k in params}

    q = select(DataPoint.id, DataPoint.review_status, DataPoint.value,
               *[getattr(DataPoint, f) for f in _HASH_EXTRA_FIELDS])
    # 排除软删除文献的数据点，与 _build_base_query 口径一致
    q = q.outerjoin(Literature, DataPoint.literature_id == Literature.id)
    q = q.where(Literature.deleted_at.is_(None))
    # 与 _build_base_query 一致：默认仅主估计（include_subgroups=True 时包含子估计）
    if not include_subgroups:
        q = q.where(DataPoint.estimate_type == "primary")
    if review_status is not None:
        q = q.where(DataPoint.review_status == review_status)
    if fk.get("disease"):
        q = q.where(DataPoint.disease == analysis_service.normalize_disease(fk["disease"]))
    if fk.get("province"):
        provinces = [p.strip() for p in str(fk["province"]).split(",") if p.strip()]
        if len(provinces) == 1:
            q = q.where(DataPoint.province.ilike(f"%{provinces[0]}%"))
        else:
            q = q.where(DataPoint.province.in_(provinces))
    if fk.get("year_start"):
        q = q.where(DataPoint.collection_year >= fk["year_start"])
    if fk.get("year_end"):
        q = q.where(DataPoint.collection_year <= fk["year_end"])
    if fk.get("age_min") is not None:
        q = q.where(DataPoint.age_min >= fk["age_min"])
    if fk.get("age_max") is not None:
        q = q.where(DataPoint.age_max <= fk["age_max"])
    data_type = data_type_override or fk.get("data_type")
    if data_type:
        q = q.where(DataPoint.data_type == data_type)
    if quality_filter_key is not None and not params.get(quality_filter_key):
        q = q.where(DataPoint.quality_grade.in_(["A", "B"]))
    return q


async def _fetch_hash_rows(db: AsyncSession, filter_keys: tuple[str, ...], params: dict,
                           data_type_override: str | None = None,
                           review_status: str | None = "approved",
                           quality_filter_key: str | None = None,
                           include_subgroups: bool | None = None):
    if not filter_keys:
        return []
    q = _build_hash_query(filter_keys, params, data_type_override, review_status,
                          quality_filter_key, include_subgroups)
    result = await db.execute(q)
    return result.all()


# ---------------------------------------------------------------------------
# 快照写入 / 复用
# ---------------------------------------------------------------------------
def _clean_params(kwargs: dict) -> dict:
    """从端点 kwargs 提取可复现参数（剔除 db 及内部键）。"""
    return {k: v for k, v in kwargs.items()
            if k != "db" and not k.startswith("_") and v is not None}


async def attach_snapshot(db: AsyncSession, module: str, params: dict,
                          response_data: dict, *,
                          filter_keys: tuple[str, ...] | None = None,
                          data_type_override: str | None = None,
                          review_status: str | None = "approved",
                          quality_filter_key: str | None = None,
                          include_subgroups: bool | None = None) -> str:
    """计算数据指纹 → 去重写入/复用快照 → 返回 snapshot_token（uuid str）。

    旁路设计：快照写入失败不影响主流程（调用方捕获）。
    """
    filter_keys = filter_keys or _STD_FILTER_KEYS
    rows = await _fetch_hash_rows(db, filter_keys, params, data_type_override,
                                  review_status, quality_filter_key, include_subgroups)
    data_hash = calculate_data_hash(rows)
    return await _upsert_snapshot(db, module, params, data_hash, response_data)


async def _upsert_snapshot(db: AsyncSession, module: str, params: dict,
                           data_hash: str, response_data: dict) -> str:
    """同 (module, params, data_hash) 去重复用；否则新建并缓存响应 JSON。

    并发安全：DB 层 uq_snapshot_identity 唯一约束兜底，INSERT 触发 IntegrityError
    时回滚并读取既有快照返回同一 token，保证并发重复请求只写入一条。
    """
    _existing = (await db.execute(
        select(AnalysisSnapshot).where(
            AnalysisSnapshot.module == module,
            AnalysisSnapshot.data_hash == data_hash,
            AnalysisSnapshot.params == params,
        ).order_by(AnalysisSnapshot.created_at.desc()).limit(1)
    )).scalars().first()

    if _existing is not None:
        return str(_existing.id)

    snap = AnalysisSnapshot(module=module, params=params, data_hash=data_hash,
                            response_json=response_data)
    db.add(snap)
    try:
        await db.commit()
    except IntegrityError:
        # 并发另一事务已写入同一条：回滚并复用其 token
        await db.rollback()
        _existing = (await db.execute(
            select(AnalysisSnapshot).where(
                AnalysisSnapshot.module == module,
                AnalysisSnapshot.data_hash == data_hash,
                AnalysisSnapshot.params == params,
            ).order_by(AnalysisSnapshot.created_at.desc()).limit(1)
        )).scalars().first()
        if _existing is not None:
            return str(_existing.id)
        raise
    return str(snap.id)


async def get_snapshot(db: AsyncSession, token: str) -> AnalysisSnapshot | None:
    """按 token（uuid str）取快照；非法或不存在返回 None。"""
    try:
        uid = uuid.UUID(token)
    except (ValueError, AttributeError, TypeError):
        return None
    return (await db.execute(
        select(AnalysisSnapshot).where(AnalysisSnapshot.id == uid)
    )).scalars().first()


# ---------------------------------------------------------------------------
# 快照装饰器：统一为 /analysis/* GET 端点旁路写快照
# ---------------------------------------------------------------------------
def with_snapshot(module: str,
                  filter_keys: tuple[str, ...] | None = None,
                  data_type_override: str | None = None,
                  review_status: str | None = "approved",
                  quality_filter_key: str | None = None,
                  include_subgroups: bool | None = None) -> Callable:
    """FastAPI 端点装饰器：计算 data_hash、去重写快照、注入 meta.snapshot_token。

    依赖注入的 ``db`` 以命名参数传入端点，装饰器从 kwargs 取出。
    快照写入失败仅告警日志，不影响主响应。
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            db = kwargs.get("db")
            resp = await func(*args, **kwargs)
            if db is None or not isinstance(resp, ApiResponse):
                return resp
            data = resp.data
            if not isinstance(data, dict):
                return resp
            try:
                token = await attach_snapshot(
                    db, module, _clean_params(kwargs), data,
                    filter_keys=filter_keys, data_type_override=data_type_override,
                    review_status=review_status, quality_filter_key=quality_filter_key,
                    include_subgroups=include_subgroups,
                )
                meta = data.get("meta")
                if not isinstance(meta, dict):
                    meta = {}
                    data["meta"] = meta
                meta["snapshot_token"] = token
            except Exception:  # 旁路：快照失败不影响主流程
                pass
            return resp
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 引用文本
# ---------------------------------------------------------------------------
def build_citation(snapshot: AnalysisSnapshot, style: str = "gbt7714",
                   accessed_date: str | None = None) -> str:
    """生成快照引用文本。

    - style=gbt7714: 电子文献[EB/OL]样式（含版本号与访问日期）
    - style=bibtex: @misc 条目
    """
    from app.core.methodology import MODULE_NAMES
    module_name = MODULE_NAMES.get(snapshot.module, snapshot.module)
    accessed = accessed_date or date.today().isoformat()
    created = (snapshot.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
               if snapshot.created_at else "—")
    token = str(snapshot.id)
    path = f"/analysis/snapshot/{token}"

    if style == "bibtex":
        key = f"antibodymap_snapshot_{token[:8]}"
        return (
            f"@misc{{{key},\n"
            f"  title = {{{DB_NAME}分析快照——{module_name}（版本 {DB_VERSION}）}},\n"
            f"  author = {{{DB_NAME}}},\n"
            f"  howpublished = {{//分析快照接口 {path}}},\n"
            f"  note = {{快照号：{token}；生成日期：{created}；"
            f"数据截至：{created}；访问日期：{accessed}}},\n"
            f"  year = {{{created[:4]}}}\n"
            f"}}"
        )

    # 默认 GBT7714（电子资源[EB/OL]）
    return (
        f"{DB_NAME}分析快照——{module_name}[EB/OL]. {DB_NAME}（版本 {DB_VERSION}）. "
        f"数据截至：{created}；[引用日期 {accessed}]. "
        f"快照号：{token}；访问：{path}。"
    )


# ---------------------------------------------------------------------------
# 后台清理：回收超过 TTL 的旧快照（response_json 会占用存储）
# ---------------------------------------------------------------------------
async def _snapshot_cleanup_loop():
    """后台循环：定期删除超过 SNAPSHOT_TTL_DAYS 天的快照，回收 response_json 存储。"""
    from app.config import settings as _settings
    from app.models.base import async_session

    logger.info(
        "[快照] 后台清理任务已启动，每 %d 秒检查一次，保留 %d 天",
        _settings.SNAPSHOT_CLEANUP_INTERVAL, _settings.SNAPSHOT_TTL_DAYS,
    )
    while True:
        try:
            async with async_session() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(days=_settings.SNAPSHOT_TTL_DAYS)
                r = await db.execute(
                    delete(AnalysisSnapshot).where(AnalysisSnapshot.created_at < cutoff)
                )
                await db.commit()
                if r.rowcount and r.rowcount > 0:
                    logger.info(
                        "[快照] 自动清理: 删除 %d 条超过 %d 天的旧快照",
                        r.rowcount, _settings.SNAPSHOT_TTL_DAYS,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[快照] 自动清理检查异常: %s", e)
        await asyncio.sleep(_settings.SNAPSHOT_CLEANUP_INTERVAL)

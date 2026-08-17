"""分析快照服务：数据指纹(data_hash)、快照去重写入、重放与引用文本生成。

设计（「分析请求可复现」）：
- 每次 /analysis/* GET 请求旁路写入一条快照：同参数(module, params, data_hash)
  去重复用，响应 meta 注入 ``snapshot_token``（uuid）。
- ``data_hash`` = 过滤后数据点 (id, review_status, value) 有序列表的
  sha256 前 16 位；数据变更 → hash 变化 → 新 token。
- ``response_json`` 缓存生成时的完整分析响应，供重放直出（不重新计算）。
- ``build_citation`` 生成 GBT7714 / BibTeX 引用文本（含版本号与访问日期）。
"""

import functools
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_snapshot import AnalysisSnapshot
from app.models.data_point import DataPoint
from app.schemas.common import ApiResponse
from app.services import analysis_service

# 数据库/口径版本（引用文本与快照元数据标注用）
DB_VERSION = "v1.0"
DB_NAME = "抗体地图数据库"

# 参与哈希取数的标准筛选参数（与 _build_base_query 对齐）
_STD_FILTER_KEYS = ("disease", "province", "year_start", "year_end",
                    "age_min", "age_max", "data_type")


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
    """对过滤后 (id, review_status, value) 有序列表计算 sha256 前 16 位。

    ``rows`` 可为 SQLAlchemy 结果（DataPoint 或 with_only_columns 的 Row），
    统一按 id 升序排列保证确定性。
    """
    triplets: list[tuple[str, str, str]] = []
    for r in rows:
        rid = r.id if hasattr(r, "id") else r[0]
        rs = r.review_status if hasattr(r, "review_status") else r[1]
        val = r.value if hasattr(r, "value") else r[2]
        triplets.append((str(rid), str(rs or ""), _norm_value(val)))
    triplets.sort(key=lambda t: t[0])  # 按 id 有序
    payload = json.dumps(triplets, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 哈希取数查询（镜像 _build_base_query 的过滤语义，但仅取 id/review_status/value）
# ---------------------------------------------------------------------------
def _build_hash_query(filter_keys: tuple[str, ...], params: dict,
                      data_type_override: Optional[str] = None,
                      review_status: Optional[str] = "approved",
                      quality_filter_key: Optional[str] = None):
    """构造哈希取数查询：与 analysis_service._build_base_query 语义一致。

    - filter_keys: 参与过滤的 params 键名；
    - data_type_override: 强制 data_type（如 meta/equity 固定 seroprevalence）；
    - review_status: 审核状态过滤；None 表示不过滤（data_gaps/coverage_review 统计全状态）；
    - quality_filter_key: 参数键名，False/缺省时仅取 A/B 级（meta 类证据门槛）。
    """
    fk = {k: params.get(k) for k in filter_keys if k in params}

    q = select(DataPoint.id, DataPoint.review_status, DataPoint.value)
    # 与 _build_base_query 一致：默认仅主估计
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
                           data_type_override: Optional[str] = None,
                           review_status: Optional[str] = "approved",
                           quality_filter_key: Optional[str] = None):
    if not filter_keys:
        return []
    q = _build_hash_query(filter_keys, params, data_type_override, review_status,
                          quality_filter_key)
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
                          filter_keys: Optional[tuple[str, ...]] = None,
                          data_type_override: Optional[str] = None,
                          review_status: Optional[str] = "approved",
                          quality_filter_key: Optional[str] = None) -> str:
    """计算数据指纹 → 去重写入/复用快照 → 返回 snapshot_token（uuid str）。

    旁路设计：快照写入失败不影响主流程（调用方捕获）。
    """
    filter_keys = filter_keys or _STD_FILTER_KEYS
    rows = await _fetch_hash_rows(db, filter_keys, params, data_type_override,
                                  review_status, quality_filter_key)
    data_hash = calculate_data_hash(rows)
    return await _upsert_snapshot(db, module, params, data_hash, response_data)


async def _upsert_snapshot(db: AsyncSession, module: str, params: dict,
                           data_hash: str, response_data: dict) -> str:
    """同 (module, params, data_hash) 去重复用；否则新建并缓存响应 JSON。"""
    existing = (await db.execute(
        select(AnalysisSnapshot).where(
            AnalysisSnapshot.module == module,
            AnalysisSnapshot.data_hash == data_hash,
            AnalysisSnapshot.params == params,
        ).order_by(AnalysisSnapshot.created_at.desc()).limit(1)
    )).scalars().first()

    if existing is not None:
        return str(existing.id)

    snap = AnalysisSnapshot(module=module, params=params, data_hash=data_hash,
                            response_json=response_data)
    db.add(snap)
    await db.commit()
    return str(snap.id)


async def get_snapshot(db: AsyncSession, token: str) -> Optional[AnalysisSnapshot]:
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
                  filter_keys: Optional[tuple[str, ...]] = None,
                  data_type_override: Optional[str] = None,
                  review_status: Optional[str] = "approved",
                  quality_filter_key: Optional[str] = None) -> Callable:
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
                   accessed_date: Optional[str] = None) -> str:
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

"""去重 / 指纹计算工具。V8-09 从 extract_task.py 拆分出的纯工具模块。

V3-02 引入 DataPoint fingerprint 用于入库去重；V3-10 引入 _safe_get 统一
dict/Pydantic model 取值。两者零 DB 依赖、零 Redis 依赖，可被 backfill
脚本 / health check / 其他 service 安全 import。
"""
from __future__ import annotations

import hashlib


def safe_get(obj, key: str, default=None):
    """V3-10: 同时兼容 dict 和 object (Pydantic model) 的统一取值。

    抽取场景：extract_results 元素有时是 dict (json.loads 产物)，
    有时 LLM 中间结果是 Pydantic model — 统一接口避免 isinstance 散落在各处。
    """
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def compute_dp_fingerprint(dp) -> str:
    """V3-02: 计算 DataPoint content_fingerprint。

    算法与 scripts/backfill_dp_fingerprint.py 完全一致:
      sha256(disease|province|city|data_type|age_min|age_max|
             collection_year|round(value,6))
    所有 None 值统一替换为 "NULL" 字符串。

    独立成模块级函数的好处: backfill 脚本和 extract 主流程共用同一份
    算法实现，避免两处漂移。
    """
    v_raw = safe_get(dp, "value")
    v = round(v_raw, 6) if v_raw is not None else None
    parts = [
        str(safe_get(dp, "disease") or "NULL"),
        str(safe_get(dp, "province") or "NULL"),
        str(safe_get(dp, "city") or "NULL"),
        str(safe_get(dp, "data_type") or "NULL"),
        str(safe_get(dp, "age_min", "NULL") if safe_get(dp, "age_min") is not None else "NULL"),
        str(safe_get(dp, "age_max", "NULL") if safe_get(dp, "age_max") is not None else "NULL"),
        str(safe_get(dp, "collection_year", "NULL") if safe_get(dp, "collection_year") is not None else "NULL"),
        str(v if v is not None else "NULL"),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

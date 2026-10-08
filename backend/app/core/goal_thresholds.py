"""每病保护目标阈值（阳性率 %，对照 HIT 群体免疫目标）。

V8-08 迁移：默认值从硬编码迁移至 reference_data/immune_barrier_constants.json
的 who_thresholds section（每条含 source/year/citation 元数据）。GOAL_THRESHOLDS
对外接口保持不变（dict[str, float]），值从 JSON 派生。

旧 hepatitits_b 硬编码 95 → JSON 权威值 90（WHO Global Hepatitis Report 2017）。

阈值语义：衡量「全省/全国加权血清阳性率」是否达到该疾病的群体免疫保护目标，
用于 get_goal_tracking 的达标判定与 HIT 缺口计算。管理员可通过
goal_threshold_config 表覆盖默认值。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache


def _load_from_json() -> dict[str, float]:
    """从 immune_barrier_constants.json 的 who_thresholds section 派生默认值。

    路径相对本文件 → ../core/reference_data/immune_barrier_constants.json。
    JSON 不可读时回退到内置 defaults（保证 import 永不崩）。
    """
    _p = os.path.join(
        os.path.dirname(__file__), "reference_data", "immune_barrier_constants.json"
    )
    try:
        with open(_p, encoding="utf-8") as _f:
            data = json.load(_f)
        who = data.get("who_thresholds", {})
        return {k: float(v["value"]) for k, v in who.items() if "value" in v}
    except (OSError, ValueError, KeyError):
        return _DEFAULTS_FALLBACK


# 内置 fallback（与 V1.31 迁移前硬编码值一致 + 与 JSON 权威值对齐）
# 当 JSON 不可读时兜底；正常运行应全部从 JSON 派生
_DEFAULTS_FALLBACK: dict[str, float] = {
    "measles": 95.0, "rubella": 95.0, "mumps": 90.0, "polio": 95.0,
    "varicella": 85.0, "diphtheria": 90.0, "tetanus": 90.0, "pertussis": 90.0,
    "meningitis": 85.0, "hepatitis_a": 90.0, "hepatitis_b": 90.0,
    "influenza": 65.0, "covid19": 75.0, "hfmd": 75.0, "rotavirus": 80.0,
}


@lru_cache(maxsize=1)
def _get_thresholds() -> dict[str, float]:
    """一次性加载 + 缓存，后续全部复用。"""
    return _load_from_json()


# 对外主接口（goal_threshold_service / equity_quality / analysis API 全部 import 此名字）
# ↓ 兼容原 dict 常量语义：模块加载时立即求值一次
GOAL_THRESHOLDS: dict[str, float] = _get_thresholds()

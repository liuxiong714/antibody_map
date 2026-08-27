"""免疫屏障评估的不确定性量化。

通过 Monte Carlo 采样把数据点的置信区间误差传播到 HIT 判断，输出「达标概率」，
替代过去的「达标 / 不达标」二元结论。

设计要点：
- 仅依赖 numpy（不引入 pymc / torch / 重型贝叶斯库）。
- 对每个数据点，用其样本量 n 与血清阳性率构造 Beta 后验
  p ~ Beta(x+1, n-x+1)（x = round(sp·n)），实现对二项比例信念的传播：
  样本量越大，分布越"尖"，采样越集中在某一点（对应更"确定"的达标概率）。
- 每次采样对多个年龄组分别抽一个阳性率，再按样本量加权汇成"加权总阳性率"，
  与各 HIT 候选阈值比较（proportion 空间 0-1），统计超过阈值的采样占比 → 达标概率。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

import numpy as np


# HIT 三来源优先级（FOI > WHO > 文献 R0），用于在多候选阈值中选主阈值
_HIT_PRIORITY = ("foi", "who", "r0_lit")

# 置信区间分位数
CI_LOW_Q, CI_HIGH_Q = 0.025, 0.975


def _to_proportion(sp: Any) -> Optional[float]:
    """把血清阳性率（百分数 >1 或 0-1 比例）归一化为 0-1 比例。非法值返回 None。"""
    try:
        p = float(sp)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(p):
        return None
    if p > 1.0:
        p /= 100.0
    return float(min(max(p, 0.0), 1.0))


def _to_positive_int(n: Any) -> Optional[int]:
    """把样本量规整为 >0 的整数；None / 0 / 非法返回 None。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def sample_positivity(
    datapoints: Sequence[Any],
    n_samples: int = 1000,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """对每个数据点的血清阳性率做 Beta 采样。

    参数：
        datapoints: 数据点序列，每个对象需具备 ``sample_size`` 与血清阳性率。
            血清阳性率字段名通过 ``seroprevalence_field`` 约定，默认 ``value``
            （本项目 DataPoint.value 即阳性率百分比）；也支持 dict 形式
            （键 ``sample_size`` / ``value``）。阳性率可为百分数（>1）或 0-1 比例。
        n_samples: 每个数据点的采样次数（>0）。
        rng: 可选的 numpy 随机数生成器（便于复现/测试）。

    返回：
        shape 为 (n_samples, n_groups) 的 ndarray，列对应每个有效数据点，
        值均为 0-1 比例的阳性率采样。无有效数据点时不采样。
    """
    groups: list[Tuple[float, float]] = []  # (alpha, beta)
    for dp in datapoints:
        if isinstance(dp, dict):
            sample_size = dp.get("sample_size")
            sp = dp.get("value", dp.get("seroprevalence"))
        else:
            sample_size = getattr(dp, "sample_size", None)
            sp = getattr(dp, "value", None)
            if sp is None:
                sp = getattr(dp, "seroprevalence", None)
        n = _to_positive_int(sample_size)
        p = _to_proportion(sp)
        if n is None or p is None:
            continue  # 无效数据点剔除，不参与采样
        x = round(p * n)
        # Beta(x+1, n-x+1)：均匀先验下的贝叶斯后验，天然覆盖 0 / 1 边界与小样本
        groups.append((x + 1.0, n - x + 1.0))

    if not groups:
        return np.empty((0, 0), dtype=float)

    gen = rng or np.random.default_rng()
    return np.column_stack(
        [gen.beta(a=a, b=b, size=n_samples) for a, b in groups]
    )


def barrier_probability(
    sampled_positivity: np.ndarray,
    hit_thresholds: dict,
    weights: Optional[Sequence[float]] = None,
) -> dict:
    """把采样矩阵与 HIT 候选阈值比较，输出达标概率。

    参数：
        sampled_positivity: shape (n_samples, n_groups) 的采样矩阵（0-1 比例）。
        hit_thresholds: HIT 多个候选值（proportion 0-1），
            如 {"foi": 0.88, "who": 0.95, "r0_lit": 0.92}，顺序按优先级。
        weights: 每列（年龄组）的权重，长度须等于 n_groups（无需归一，内部归一化）；
            为 None 时等权平均。

    返回：
        {
          "thresholds_used": {"foi": {"threshold": 0.88, "pass_probability": 0.63,
                              "data_points": ...}, ...},
          "primary_threshold": "foi",
          "pass_probability": 0.63,          # 主阈值（优先级最高者）达标概率
          "weighted_mean": 0.86,             # 采样加权总阳性率均值（0-1）
          "weighted_ci": [0.82, 0.90],       # 采样加权总阳性率 95% 区间
        }
    """
    if sampled_positivity.ndim != 2 or sampled_positivity.shape[0] == 0:
        raise ValueError("sampled_positivity 必须为非空二维数组 (n_samples, n_groups)")

    n_samples, n_groups = sampled_positivity.shape
    if weights is None:
        w = np.full(n_groups, 1.0 / n_groups)
    else:
        w = np.asarray(weights, dtype=float).reshape(-1)
        if w.size != n_groups:
            raise ValueError(f"weights 长度 {w.size} 与 n_groups {n_groups} 不一致")
        total = w.sum()
        if not np.isfinite(total) or total <= 0:
            raise ValueError("weights 必须为正且可求和")
        w = w / total

    # 每次采样的加权总阳性率（0-1）
    totals = sampled_positivity @ w  # (n_samples,)

    thresholds_used = {}
    for key, thr in hit_thresholds.items():
        t = _to_proportion(thr)
        if t is None:
            continue
        pass_prob = float(np.mean(totals >= t))
        thresholds_used[key] = {
            "threshold": round(t, 4),
            "pass_probability": round(pass_prob, 4),
        }

    primary = next((k for k in _HIT_PRIORITY if k in thresholds_used), None)
    primary_prob = (
        thresholds_used[primary]["pass_probability"]
        if primary is not None else None
    )

    weighted_mean = float(np.mean(totals))
    ci = np.percentile(totals, [CI_LOW_Q * 100.0, CI_HIGH_Q * 100.0])
    return {
        "thresholds_used": thresholds_used,
        "primary_threshold": primary,
        "pass_probability": primary_prob,
        "weighted_mean": round(weighted_mean, 4),
        "weighted_ci": [round(float(ci[0]), 4), round(float(ci[1]), 4)],
    }


def fusion_hit(thresholds_dict: dict) -> Tuple[float, float, float]:
    """把多来源 HIT 做简单融合，返回 (mean, ci_low, ci_high)。

    取各来源阈值的等权算术平均作为融合值，区间取 [min, max] 反映来源分歧。
    无有效值则返回 (None, None, None)。
    """
    vals = [
        t for t in (thresholds_dict.get(k) for k in _HIT_PRIORITY)
        if t is not None
    ]
    if not vals:
        return (None, None, None)
    mean = float(np.mean(vals))
    return (round(mean, 4), round(float(min(vals)), 4), round(float(max(vals)), 4))
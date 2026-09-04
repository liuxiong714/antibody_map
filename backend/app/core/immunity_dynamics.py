"""免疫屏障动态预测（抗体衰减 + 新出生队列驱动）。

本模块提供两类底层计算：

1. ``project_barrier``：给定当前各年龄组阳性率，按「年抗体衰减 + 每年新出生
   零保护队列稀释」递推未来若干年的有效免疫屏障轨迹。
2. ``estimate_waning_rate``：用多个年份的总体阳性率实测值，拟合出每年的抗体
   转阴（衰减）比例。

模型约定（均为简化处理，详见各函数 docstring）：

- 屏障以「有效免疫比例」表示，取值 0~1（1 即 100% 保护）；
- 每年存量免疫按 ``1 - waning_rate`` 比例存续（即每年转阴 waning_rate）；
- 每年新出生且零保护的队列占比 ``birth_cohort_size``，对整体屏障产生稀释；
- 自然死亡 / 老化的年龄结构演化暂忽略（可在递推模型中补充，注释说明）。

仅依赖 numpy（项目已有），不引入 pymc / torch 等重型依赖。
"""

from __future__ import annotations

import logging
import math

import numpy as np

logger = logging.getLogger(__name__)

# 默认参数
DEFAULT_WANING_RATE = 0.02        # 默认每年抗体转阴比例（2%）
DEFAULT_BIRTH_COHORT_SIZE = 0.012  # 默认每年新出生零保护人口占比（1.2%）
DEFAULT_PROJECTION_YEARS = 10      # 默认预测年数
DEFAULT_BARRIER_THRESHOLD = 0.92   # 默认屏障安全阈值（92% 有效免疫）


def _as_fraction(value: float | None) -> float | None:
    """把阳性率统一为 0~1 的比例。

    项目内 ``DataPoint.value``（seroprevalence）通常以百分数（0~100）存储，
    但外部调用也可能直接传入比例（0~1）。为稳妥，本函数自动归一化：
    大于 1 的视为百分数除以 100，否则原样返回。
    """
    if value is None:
        return None
    v = float(value)
    if v > 1.0:
        return v / 100.0
    return v


def project_barrier(
    age_seropositivity: dict[str, float],
    waning_rate: float = DEFAULT_WANING_RATE,
    years: int = DEFAULT_PROJECTION_YEARS,
    birth_cohort_size: float = DEFAULT_BIRTH_COHORT_SIZE,
) -> list:
    """递推未来若干年的有效免疫屏障轨迹。

    参数
    ----
    age_seropositivity : dict
        形如 ``{年龄组: 阳性率}`` 的当前各年龄组阳性率。取值可为比例（0~1）
        或百分数（0~100），内部自动归一化。
    waning_rate : float
        每年抗体转阴比例（默认 0.02，即每年 2% 转阴，可配置）。
    years : int
        预测年数（默认 10）。
    birth_cohort_size : float
        每年新出生且零保护的人口占比（默认 0.012，即每年新增约 1.2% 零保护者）。

    返回
    ----
    list[float]
        有效免疫屏障轨迹，长度为 ``years + 1``：首元素为当前基线屏障
        （各年龄组阳性率的简单平均），后续元素依次为第 1、2、...、years 年的预测值。
        每个值均为 0~1 的比例（已四舍五入到 4 位小数）。

    模型递推（第 t 年）：
        barrier[t] = barrier[t-1] × (1 - waning_rate) × (1 - birth_cohort_size)

    说明
    ----
    - 当前基线屏障取各年龄组阳性率的简单平均，未按实际人口年龄结构加权；
    - ``(1 - birth_cohort_size)`` 表示新增零保护出生队列对整体屏障的稀释；
    - 自然死亡与老化的年龄结构演化暂忽略——即假设各年龄组比例在预测期内保持
      恒定，不区分人群进入/退出带来的结构变化；后续可扩展为基于实际人口金字塔
      的年龄转移矩阵。
    """
    values: list[float] = []
    for v in age_seropositivity.values():
        f = _as_fraction(v)
        if f is not None:
            values.append(f)
    if not values:
        logger.warning("[ImmunityDynamics] project_barrier 无有效阳性率，返回空轨迹")
        return []

    baseline = max(0.0, min(1.0, sum(values) / len(values)))

    w = max(0.0, min(1.0, float(waning_rate)))
    b = max(0.0, float(birth_cohort_size))
    n_years = max(0, int(years))

    trajectory: list[float] = [round(baseline, 4)]
    prev = baseline
    for _ in range(n_years):
        nxt = prev * (1.0 - w) * (1.0 - b)
        nxt = max(0.0, min(1.0, nxt))
        trajectory.append(round(nxt, 4))
        prev = nxt
    return trajectory


def estimate_waning_rate(
    observed_by_year: dict[int, float],
    default: float = DEFAULT_WANING_RATE,
) -> float:
    """用多年份总体阳性率实测值拟合年抗体衰减率。

    模型：``ln(y_t) = ln(y_0) + t·ln(1 - w)``，其中 ``y_t`` 为第 t 年总体阳性率，
    ``w`` 为每年转阴比例。对相对年份 ``t`` 与 ``ln(y_t)`` 做最小二乘线性回归，
    取斜率斜率 ``k = ln(1 - w)``，则 ``w = 1 - exp(k)``。

    参数
    ----
    observed_by_year : dict
        形如 ``{年份: 该年总体阳性率}``。阳性率可为比例（0~1）或百分数（0~100）。
    default : float
        数据不足（少于 2 个有效年份，或全部阳性率 ≤ 0）时回退的默认值。

    返回
    ----
    float
        估计出的年衰减率（0~0.5，被钳位）。若阳性率长期上升（斜率为正）则
        衰减率钳位到 0（表示无衰减）；数据不足时返回 ``default``。
    """
    items = []
    for year, val in observed_by_year.items():
        f = _as_fraction(val)
        if f is not None and f > 0.0:
            items.append((int(year), f))
    if len(items) < 2:
        logger.warning(
            f"[ImmunityDynamics] estimate_waning_rate 有效年份数 {len(items)} < 2，"
            f"回退默认衰减率 {default}"
        )
        return round(float(default), 4)

    items.sort(key=lambda x: x[0])  # 按年份升序
    years = np.array([it[0] for it in items], dtype=float)
    logy = np.log(np.array([it[1] for it in items], dtype=float))
    # 相对年份使截距无关紧要，只需斜率
    rel_years = years - years[0]
    slope = float(np.polyfit(rel_years, logy, 1)[0])
    w = 1.0 - math.exp(slope)
    # 钳位：衰减率取 0~0.5（>50%/年的极端值按 0.5 处理）
    w = max(0.0, min(0.5, w))
    return round(w, 4)
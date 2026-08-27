"""有效免疫屏障计算：用年龄接触矩阵对人群阳性率加权。

替代「只看总阳性率」的粗糙评估：以接触矩阵的（Perron-Frobenius）主导
特征向量作为各年龄组在传播中的相对重要性权重 w，对年龄组阳性率加权得到
有效免疫屏障，并量化各年龄组对屏障的缺口，从而定位最薄弱年龄组。

不引入新依赖：仅使用项目已有的 numpy。
"""

from __future__ import annotations

import json
import os
from typing import Optional

import numpy as np

# 接触矩阵年龄组标签（与 china_contact_matrix.json 的行顺序一致）
AGE_GROUPS_CONTACT = ["0-4", "5-17", "18-29", "30-59", "60+"]

# 各年龄组对应的年龄区间 [lo, hi]（顺序与 AGE_GROUPS_CONTACT 一致）
_AGE_GROUP_RANGES = [(0, 4), (5, 17), (18, 29), (30, 59), (60, 200)]

_CONTACT_MATRIX_PATH = os.path.join(
    os.path.dirname(__file__), "reference_data", "china_contact_matrix.json"
)


def load_contact_matrix() -> np.ndarray:
    """读取 china_contact_matrix.json，返回 n×n 的 numpy 接触矩阵（float）。"""
    with open(_CONTACT_MATRIX_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return np.asarray(data["matrix"], dtype=float)


def map_age_to_group(age_min: Optional[int], age_max: Optional[int]) -> Optional[str]:
    """把数据点的年龄区间 [age_min, age_max] 映射到 5 个接触矩阵年龄组之一。

    区间需完全落在某年龄组范围内才判定命中；无年龄信息（age_min 为 None）
    或区间跨多个年龄组时返回 None。
    """
    if age_min is None:
        return None
    for label, (lo, hi) in zip(AGE_GROUPS_CONTACT, _AGE_GROUP_RANGES):
        if age_min >= lo and (age_max is not None and age_max <= hi):
            return label
    return None


def effective_barrier(age_group_positivity: dict, contact_matrix: np.ndarray) -> dict:
    """用接触矩阵主导特征向量加权计算有效免疫屏障。

    age_group_positivity: {年龄组标签: 阳性率(%)}，标签需与矩阵行顺序一致
    （AGE_GROUPS_CONTACT）；缺失的年龄组不参与屏障计算。

    计算：
      a) 传播权重 w = 接触矩阵主导特征向量（numpy.linalg.eig 取最大特征值
         对应的右特征向量，取绝对值后归一化到和为 1），代表各年龄组在传播
         中的相对重要性；
      b) 有效免疫屏障 = Σ(w_i × 阳性率_i)；
      c) 各年龄组缺口 = w_i × (1 - 阳性率_i)，降序排序返回最薄弱年龄组。

    返回 {effective_barrier, group_weights, group_gaps, weakest_groups}：
    - effective_barrier: 加权有效免疫屏障（%，0-100）；
    - group_weights: 各年龄组传播权重（按矩阵行顺序）；
    - group_gaps: [{age_group, weight, positivity_percent, gap}, ...] 按 gap 降序；
    - weakest_groups: 最薄弱年龄组标签列表（缺口最大者在前）。
    """
    matrix = np.asarray(contact_matrix, dtype=float)
    n = matrix.shape[0]
    if n == 0:
        return {
            "effective_barrier": None,
            "group_weights": {},
            "group_gaps": [],
            "weakest_groups": [],
        }

    # 主导（Perron-Frobenius）特征向量 → 传播权重
    eigvals, eigvecs = np.linalg.eig(matrix)
    idx = int(np.argmax(np.real(eigvals)))
    w_raw = np.real(eigvecs[:, idx])
    w = np.abs(w_raw)
    total = w.sum()
    if total <= 0:
        w = np.ones(n) / n
    else:
        w = w / total

    group_weights: dict[str, float] = {
        AGE_GROUPS_CONTACT[i]: round(float(w[i]), 6) for i in range(n)
    }

    group_gaps: list[dict] = []
    barrier_terms: list[float] = []
    for i, label in enumerate(AGE_GROUPS_CONTACT):
        positivity = age_group_positivity.get(label)
        if positivity is None:
            continue
        p = float(positivity)
        wi = float(w[i])
        gap = wi * (1.0 - p / 100.0)
        group_gaps.append({
            "age_group": label,
            "weight": round(wi, 6),
            "positivity_percent": round(p, 2),
            "gap": round(gap, 6),
        })
        barrier_terms.append(wi * p / 100.0)

    effective_barrier_value = (
        round(sum(barrier_terms) * 100.0, 2) if barrier_terms else None
    )

    group_gaps.sort(key=lambda x: x["gap"], reverse=True)

    return {
        "effective_barrier": effective_barrier_value,
        "group_weights": group_weights,
        "group_gaps": group_gaps,
        "weakest_groups": [g["age_group"] for g in group_gaps],
    }

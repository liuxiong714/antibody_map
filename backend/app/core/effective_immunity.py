"""有效免疫屏障计算：用年龄接触矩阵对人群阳性率加权。

替代「只看总阳性率」的粗糙评估：以接触矩阵的（Perron-Frobenius）主导
特征向量作为各年龄组在传播中的相对重要性权重 w，对年龄组阳性率加权得到
有效免疫屏障，并量化各年龄组对屏障的缺口，从而定位最薄弱年龄组。

新世代矩阵（NGM）残差法（R_eff）见 ``r_eff``：用 NGM 直接计算免疫后
基本再生数，更严格地回答"是否真的达到群体免疫"。

不引入新依赖：仅使用项目已有的 numpy。
"""

from __future__ import annotations

import json
import os
from warnings import deprecated

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
    with open(_CONTACT_MATRIX_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return np.asarray(data["matrix"], dtype=float)


def map_age_to_group(age_min: int | None, age_max: int | None) -> str | None:
    """把数据点的年龄区间 [age_min, age_max] 映射到 5 个接触矩阵年龄组之一。

    区间需完全落在某年龄组范围内才判定命中；无年龄信息（age_min 为 None）
    或区间跨多个年龄组时返回 None。
    """
    if age_min is None:
        return None
    for label, (lo, hi) in zip(AGE_GROUPS_CONTACT, _AGE_GROUP_RANGES, strict=False):
        if age_min >= lo and (age_max is not None and age_max <= hi):
            return label
    return None


@deprecated(
    "effective_barrier 仅做加权汇总，不能直接回答 R_eff < 1 的判据。"
    "新代码改用 r_eff()（新世代矩阵残差法）计算真正的有效再生数。",
    category=DeprecationWarning,
    stacklevel=2,
)
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
    w = np.ones(n) / n if total <= 0 else w / total

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


def r_eff(
    age_group_positivity: dict[str, float],
    contact_matrix: np.ndarray,
    r0: float,
    susceptibility: dict[str, float] | list[float] | np.ndarray | None = None,
) -> dict:
    """新世代矩阵（Next Generation Matrix, NGM）残差法计算有效再生数 R_eff。

    与 ``effective_barrier`` 的本质区别：effective_barrier 仅汇总阳性率，
    回答"抗体阳性率加权后是多少"；r_eff 直接把免疫衰减注入传播矩阵，
    回答"这种免疫分布下的基本再生数是多少"——R_eff < 1 才是真正的群体免疫。

    数学（per Diekmann & Heesterbeek 2000）：

      NGM_ij = C_ij · d_j
        i 年龄组感染 j 年龄组的预期传播贡献；d_j 为 j 的相对易感性/传染性
        （或双易感模型中 sqrt(d_i · d_j)，这里取单侧，默认 d=全 1）。

      p ∈ [0,1]^n ：各年龄组的有效保护（从阳性率 %% 转百分数）。

      K = NGM · diag(1 − p)                   # 免疫后的残差 NGM

      ρ(K) = max(Re(λ))                         # 谱半径（主导特征值实部）

      R_eff = r0 · ρ(K) / ρ(NGM)               # 归一化到传入的 r0

    归一化的必要性：传入 r0 通常是人群平均基本再生数（如文献/FOI 估计），
    而 ρ(NGM) 是数值谱半径，两者有标度差。除以 ρ(NGM) 后 R_eff 数值量级与
    传入 r0 对齐，便于判断 R_eff < 1。

    入参：
      age_group_positivity: {年龄组标签: 阳性率 %% (0-100)}
      contact_matrix:       n×n numpy array（C_ij = i→j 接触次数/强度）
      r0:                   参考基本再生数（人群平均，如文献 R0 或 FOI 估计的 R0）
      susceptibility:       各年龄组相对易感性 d_j，None 或默认全 1；
                            list/np.ndarray 按矩阵行顺序；dict 按标签匹配

    返回：{
        r_eff:                    有效再生数 (float, None 表示矩阵退化)
        herd_immunity_met:        bool —— R_eff < 1（残差谱半径下的真正群体免疫判据）
        required_extra_immunity_gap: float —— 让 R_eff 降至 1 还需提升多少平均保护
                                        （线性近似：gap ≈ (R_eff - 1) / R_eff）
        group_contributions:      [{age_group, positivity_percent,
                                    residual_weight 贡献到残差谱半径的比例, ...}]
        r0_input:                 回显传入 r0
        rho_ngm:                  无免疫 NGM 谱半径（诊断用）
        rho_k:                    免疫后残差 K 谱半径（诊断用）
      }
    """
    matrix = np.asarray(contact_matrix, dtype=float)
    n = matrix.shape[0]

    # 空矩阵
    if n == 0 or matrix.shape != (n, n):
        return {
            "r_eff": None,
            "herd_immunity_met": None,
            "required_extra_immunity_gap": None,
            "group_contributions": [],
            "r0_input": r0,
            "rho_ngm": None,
            "rho_k": None,
        }

    # 1) 易感性 d_j 转 ndarray
    if susceptibility is None:
        d_arr = np.ones(n)
    elif isinstance(susceptibility, dict):
        d_arr = np.array(
            [float(susceptibility.get(AGE_GROUPS_CONTACT[i], 1.0)) for i in range(n)],
            dtype=float,
        )
    else:
        d_arr = np.asarray(susceptibility, dtype=float)
        if d_arr.size != n:
            d_arr = np.ones(n)  # 长度不符 → 回退全 1

    # 钳位 d ≥ 0
    d_arr = np.clip(d_arr, 0.0, None)

    # 2) 年龄组阳性率 → 保护概率 p ∈ [0, 1]
    p_arr = np.zeros(n)
    for i, label in enumerate(AGE_GROUPS_CONTACT):
        pos = age_group_positivity.get(label)
        if pos is None:
            continue
        p_arr[i] = np.clip(float(pos) / 100.0, 0.0, 1.0)

    # 3) NGM = C · diag(d)
    ngm = matrix * d_arr[np.newaxis, :]            # broadcasting: matrix 的第 j 列乘 d_j

    # 4) 残差 K = NGM · diag(1-p)
    residual = ngm * (1.0 - p_arr)[np.newaxis, :]

    # 5) 谱半径
    eig_ngm = np.linalg.eigvals(ngm)
    rho_ngm = float(np.max(np.real(eig_ngm))) if eig_ngm.size > 0 else 0.0

    eig_k = np.linalg.eigvals(residual)
    rho_k = float(np.max(np.real(eig_k))) if eig_k.size > 0 else 0.0

    # 6) R_eff = r0 · ρ(K) / ρ(NGM)
    #    特殊：ρ(NGM) ≈ 0（接触矩阵全零）→ 无法归一化，返回 None
    if rho_ngm <= 1e-12 or r0 <= 0:
        r_eff_val: float | None = None
        met: bool | None = None
        gap: float | None = None
    else:
        r_eff_val = float(r0 * rho_k / rho_ngm)
        met = r_eff_val < 1.0
        # 平均保护需提升到 p_target，使 (1-p_target) · r0_norm < 1
        # 线性近似：gap ≈ R_eff - 1（当 R_eff > 1）
        if r_eff_val >= 1.0:
            gap = float((r_eff_val - 1.0) / max(r_eff_val, 1e-9))
        else:
            gap = 0.0

    # 7) 各组贡献：残差矩阵行和（传播源）归一化
    row_sums = residual.sum(axis=1)
    total_row = float(row_sums.sum())
    contribs = []
    for i, label in enumerate(AGE_GROUPS_CONTACT):
        if total_row > 1e-12:
            frac = float(row_sums[i] / total_row)
        else:
            frac = 0.0
        contribs.append({
            "age_group": label,
            "positivity_percent": round(float(p_arr[i] * 100.0), 2),
            "residual_weight": round(float(row_sums[i]), 6),
            "contribution_fraction": round(frac, 6),
        })

    return {
        "r_eff": round(r_eff_val, 4) if r_eff_val is not None else None,
        "herd_immunity_met": met,
        "required_extra_immunity_gap": round(gap, 6) if gap is not None else None,
        "group_contributions": contribs,
        "r0_input": float(r0),
        "rho_ngm": round(rho_ngm, 6),
        "rho_k": round(rho_k, 6),
    }

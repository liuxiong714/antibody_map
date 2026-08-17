"""
抗原制图引擎（antigenic cartography）

基于滴度矩阵的 metric MDS 降维，将抗原和血清映射到 2D 平面，
使欧氏距离逼近 log₂ 空间中的"表格距离"（column baseline − log₂ titer）。

参考：Smith et al. (2004) "Mapping the Antigenic and Genetic Evolution of Influenza Virus"
      Racmacs R package (https://github.com/acorg/racmacs)
"""

import logging
from typing import Any, Optional

import numpy as np
from sklearn.manifold import MDS
from scipy.spatial import procrustes

logger = logging.getLogger("uvicorn")  # 与 llm_extractor 保持一致


# ---------------------------------------------------------------------------
# 预处理
# ---------------------------------------------------------------------------

def preprocess_titers(
    titers_2d: list[list[Optional[float]]],
    log2_divisor: float = 10.0,
) -> dict:
    """预处理滴度矩阵，输出 log₂ 空间中的表格距离矩阵。

    Parameters
    ----------
    titers_2d : list[list[Optional[float]]]
        滴度矩阵，行为抗原（n_antigen），列为抗血清（n_serum）。
        None 表示缺失值（如未测、不可读）。
        0 表示低于检出限（如 <10）。
    log2_divisor : float
        log₂ 变换的分母，默认 10（HI 滴度通常以 1:10 为基）。

    Returns
    -------
    dict
        - log2_matrix : np.ndarray (n_antigen, n_serum)
            log₂(titer / log2_divisor)，缺失/0 处为 NaN。
        - distances : np.ndarray (n_antigen, n_serum)
            表格距离矩阵 d_ij = cb_j − log2_ij，NaN 处仍为 NaN。
        - column_baselines : np.ndarray (n_serum,)
            列基准 cb_j = max_i log2_ij（忽略 NaN）。
        - dropped_rows : list[int]
            被剔除的行索引（v1 策略：含检出限值或缺失过多）。
        - n_antigen : int
        - n_serum : int
        - grid_explanation : str
    """
    arr = np.array(titers_2d, dtype=float)
    n_antigen, n_serum = arr.shape

    # --- Step 1: log₂(titer / divisor) ---
    log2_arr = np.full_like(arr, np.nan)
    valid = (arr > 0) & (~np.isnan(arr))
    log2_arr[valid] = np.log2(arr[valid] / log2_divisor)

    # --- Step 1b: 剔除行（v1 简化）---
    # 行中若有 0（检出限）或缺失 > 50%，整个剔除
    dropped_rows = []
    kept_rows = []
    for i in range(n_antigen):
        row = log2_arr[i, :]
        n_zero_or_nan = np.sum(np.isnan(row) | (arr[i, :] == 0))
        if n_zero_or_nan > 0:  # 检出限或缺失归入 dropped
            dropped_rows.append(i)
        else:
            kept_rows.append(i)

    # 排除后的矩阵
    if not kept_rows:
        raise ValueError("剔除后无有效行，无法进行抗原制图")

    kept_log2 = log2_arr[kept_rows, :]
    n_kept = len(kept_rows)

    # --- Step 2: 列基准 cb_j = max_i log2_ij ---
    column_baselines = np.nanmax(kept_log2, axis=0)  # (n_serum,)

    # --- Step 3: 表格距离 d_ij = cb_j − log2_ij ---
    distances = np.full_like(kept_log2, np.nan)
    for j in range(n_serum):
        distances[:, j] = column_baselines[j] - kept_log2[:, j]

    if logger.isEnabledFor(logging.INFO):
        logger.info(
            f"预处理: {n_antigen}抗原×{n_serum}血清 → "
            f"{n_kept}抗原×{n_serum}血清 "
            f"(dropped {len(dropped_rows)} 行: {dropped_rows})"
        )

    return {
        "log2_matrix": kept_log2,
        "distances": distances,
        "column_baselines": column_baselines,
        "dropped_rows": dropped_rows,
        "kept_row_indices": kept_rows,
        "n_antigen": n_kept,
        "n_serum": n_serum,
        "grid_explanation": "1 网格 = 2 倍滴度差（log2 空间 1 单位）",
    }


# ---------------------------------------------------------------------------
# Metric MDS
# ---------------------------------------------------------------------------

def compute_mds(
    distances: np.ndarray,
    n_components: int = 2,
    n_init: int = 20,
    max_iter: int = 1000,
    random_state: Optional[int] = None,
) -> dict:
    """在距离矩阵上执行 metric MDS，多点初值取最优。

    Parameters
    ----------
    distances : np.ndarray (n_antigen + n_serum, n_antigen + n_serum)
        对称的"抗原-血清"联合距离矩阵（上三角+下三角填充）。
    n_components : int
        降维维度（默认 2D）。
    n_init : int
        随机初值次数（多点初值取最优）。
    max_iter : int
        每次初值的最大迭代数。
    random_state : int or None
        随机种子，设定后结果可复现。

    Returns
    -------
    dict
        - coordinates : np.ndarray (n_points, n_components)
            所有点的坐标。
        - stress_raw : float
            原始应力 Σ(d_ij − D_ij)²。
        - stress_normalized : float
            Kruskal 归一化应力（stress-1）。
        - stress_per_point : np.ndarray (n_points,)
            每一点的应力贡献（到所有其他点的距离平方和）。
        - n_iter : int
            实际迭代次数。
        - converged : bool
    """
    mds = MDS(
        n_components=n_components,
        metric_mds=True,
        metric="precomputed",
        init="random",
        n_init=n_init,
        max_iter=max_iter,
        random_state=random_state,
        normalized_stress=True,
        eps=1e-8,
    )
    coords = mds.fit_transform(distances)  # (n_points, n_components)

    # sklearn 的 stress_ 是归一化 stress-1 = sqrt(Σ(d-D)² / Σ(d²))
    s_norm = mds.stress_
    # 原始 stress
    n_points = distances.shape[0]
    # 从 embedding 计算配对的嵌入距离
    embed_dist = np.zeros_like(distances)
    for i in range(n_points):
        for j in range(i + 1, n_points):
            d = np.sqrt(np.sum((coords[i] - coords[j]) ** 2))
            embed_dist[i, j] = d
            embed_dist[j, i] = d

    sq_diff = (distances - embed_dist) ** 2
    # 只计算上三角（不包括对角线）
    triu = np.triu_indices(n_points, k=1)
    stress_raw = float(np.sum(sq_diff[triu]))
    # 去掉 mask 后的元素数
    n_valid = len(triu[0])
    # 每一点的应力（到其他点的距离平方和）
    stress_per_point = np.sum(sq_diff, axis=1)  # (n_points,)

    return {
        "coordinates": coords,
        "stress_raw": stress_raw,
        "stress_normalized": float(s_norm),
        "stress_per_point": stress_per_point.tolist(),
        "n_iter": mds.n_iter_,
        "converged": bool(mds.n_iter_ < max_iter),
    }


def _build_full_distance_matrix(
    distances: np.ndarray,
    n_antigen: int,
    n_serum: int,
) -> np.ndarray:
    """将抗原×血清距离矩阵扩展为对称的 (n_antigen+n_serum) 完全距离矩阵。

    采用"双中心化"策略：抗原之间距离 = 对应列距离向量差的欧氏距离，
    血清之间距离类似，抗原-血清距离直接取自原始矩阵。

    v1 简化：使用抗原-血清距离构造列联表方式的三角矩阵：
    - 抗原-血清距离 = 原始 d_ij
    - 抗原-抗原距离 = 通过列向量的欧氏距离
    - 血清-血清距离 = 通过行向量的欧氏距离
    """
    n_total = n_antigen + n_serum
    full = np.zeros((n_total, n_total), dtype=float)

    # 抗原-抗原距离：基于列向量（血清维）的欧氏距离
    for i in range(n_antigen):
        for j in range(i + 1, n_antigen):
            d = np.sqrt(np.sum((distances[i, :] - distances[j, :]) ** 2))
            full[i, j] = d
            full[j, i] = d

    # 血清-血清距离：基于行向量（抗原维）的欧氏距离
    for i in range(n_serum):
        for j in range(i + 1, n_serum):
            d = np.sqrt(np.sum((distances[:, i] - distances[:, j]) ** 2))
            full[n_antigen + i, n_antigen + j] = d
            full[n_antigen + j, n_antigen + i] = d

    # 抗原-血清距离
    for i in range(n_antigen):
        for j in range(n_serum):
            d = distances[i, j]
            full[i, n_antigen + j] = d
            full[n_antigen + j, i] = d

    return full


# ---------------------------------------------------------------------------
# 完整管线
# ---------------------------------------------------------------------------

def antigenic_map(
    titers_2d: list[list[Optional[float]]],
    antigen_names: Optional[list[str]] = None,
    serum_names: Optional[list[str]] = None,
    log2_divisor: float = 10.0,
    n_init: int = 20,
    max_iter: int = 1000,
    random_state: Optional[int] = None,
    return_raw: bool = False,
) -> dict:
    """完整抗原制图管线：预处理 → metric MDS → 输出。

    Parameters
    ----------
    titers_2d : list[list[Optional[float]]]
        n_antigen × n_serum 滴度矩阵。
    antigen_names : list[str] or None
        抗原名称（n_antigen 个，dropped 行会被自动排除）。
    serum_names : list[str] or None
        抗血清名称（n_serum 个）。
    log2_divisor : float
        log₂ 变换的基，默认 10（HI 滴度）。
    n_init : int
        MDS 随机初值次数。
    max_iter : int
        MDS 最大迭代次数。
    random_state : int or None
        随机种子。
    return_raw : bool
        如果为 True，返回包含预处理中间结果的完整字典。

    Returns
    -------
    dict
        - coordinates : list[dict]
            [{name, type: "antigen"|"serum", x, y}, ...]
        - stress_raw : float
        - stress_normalized : float
        - stress_per_point : list[float]
        - grid_explanation : str
        - n_antigen : int
        - n_serum : int
        - dropped_rows : list[int]
        - converged : bool
        - n_iter : int
    """
    pre = preprocess_titers(titers_2d, log2_divisor=log2_divisor)
    dist = pre["distances"]
    n_antigen = pre["n_antigen"]
    n_serum = pre["n_serum"]
    kept_indices = pre["kept_row_indices"]

    # 构建对称距离矩阵
    full_dist = _build_full_distance_matrix(dist, n_antigen, n_serum)

    # Metric MDS
    mds_result = compute_mds(
        full_dist,
        n_components=2,
        n_init=n_init,
        max_iter=max_iter,
        random_state=random_state,
    )
    coords = mds_result["coordinates"]

    # 组装输出坐标
    coordinates = []
    for i in range(n_antigen):
        orig_idx = kept_indices[i]
        name = antigen_names[orig_idx] if antigen_names and orig_idx < len(antigen_names) else f"Antigen_{orig_idx}"
        coordinates.append({
            "name": name,
            "type": "antigen",
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
        })
    for j in range(n_serum):
        name = serum_names[j] if serum_names and j < len(serum_names) else f"Serum_{j}"
        coordinates.append({
            "name": name,
            "type": "serum",
            "x": float(coords[n_antigen + j, 0]),
            "y": float(coords[n_antigen + j, 1]),
        })

    result = {
        "coordinates": coordinates,
        "stress_raw": mds_result["stress_raw"],
        "stress_normalized": mds_result["stress_normalized"],
        "stress_per_point": mds_result["stress_per_point"],
        "grid_explanation": pre["grid_explanation"],
        "n_antigen": n_antigen,
        "n_serum": n_serum,
        "dropped_rows": pre["dropped_rows"],
        "converged": mds_result["converged"],
        "n_iter": mds_result["n_iter"],
    }

    if return_raw:
        result["_preprocess"] = pre
        result["_mds"] = mds_result

    return result


# ---------------------------------------------------------------------------
# Procrustes 分析（验证用）
# ---------------------------------------------------------------------------

def procrustes_compare(
    coords_a: np.ndarray,
    coords_b: np.ndarray,
) -> dict:
    """Procrustes 分析：对齐两组坐标并计算相关性。

    用于验证自实现结果与 Racmacs 参考结果的一致性。

    Parameters
    ----------
    coords_a : np.ndarray (n, 2)
        第一组坐标（如自实现结果）。
    coords_b : np.ndarray (n, 2)
        第二组坐标（如 Racmacs 参考结果）。

    Returns
    -------
    dict
        - disparity : float
            Procrustes 不相似度（越小越好）。
        - correlation : float
            Procrustes 相关系数（>0.95 表示形态高度一致）。
        - aligned_a : np.ndarray (n, 2)
            对齐后的第一组坐标。
        - rotation : np.ndarray (2, 2)
            旋转矩阵。
        - scale : float
            缩放因子。
        - translation : np.ndarray (2,)
            平移向量。
    """
    mtx1, mtx2, disparity = procrustes(coords_a, coords_b)
    # 相关系数 = 1 - disparity²（标准 Procrustes）
    correlation = 1.0 - disparity ** 2
    return {
        "disparity": float(disparity),
        "correlation": float(correlation),
        "aligned_a": mtx1,
        "aligned_b": mtx2,
    }


# ---------------------------------------------------------------------------
# 公开的 HI 表参考数据（Racmacs 文档示例风格）
# ---------------------------------------------------------------------------

# 8 抗原 × 10 血清的合成 HI 表（类似 Racmacs hi_2007 数据集结构）
# 抗原按循环模式排列，应产生一个环形 2D 布局
RACMACS_STYLE_HI_TABLE: list[list[int]] = [
    [640, 1280, 40,   80,   160,  320,  640,  1280, 80,   40],
    [80,  160,  640,  1280, 40,   80,   160,  320,  640,  1280],
    [1280, 640, 160,  80,   40,   1280, 640,  160,  80,   40],
    [40,  80,   1280, 640,  160,  40,   80,   1280, 640,  160],
    [160, 40,   80,   1280, 640,  160,  40,   80,   1280, 640],
    [320, 640,  1280, 40,   80,   160,  320,  640,  1280, 80],
    [80,  160,  320,  640,  1280, 40,   80,   160,  320,  640],
    [640, 1280, 80,   160,  320,  640,  1280, 40,   80,   160],
]

RACMACS_STYLE_ANTIGEN_NAMES = [
    "A/Cal/07/09", "A/Perth/16/09", "A/Bris/59/07",
    "A/Uruguay/716/07", "A/Solomon/3/06", "A/NC/20/99",
    "A/Syd/5/97", "A/Beijing/262/95",
]

RACMACS_STYLE_SERUM_NAMES = [
    "Anti-A/Cal", "Anti-A/Perth", "Anti-A/Bris",
    "Anti-A/Uruguay", "Anti-A/Solomon", "Anti-A/NC",
    "Anti-A/Syd", "Anti-A/Beijing", "Anti-A/NewCaled", "Anti-A/Wisconsin",
]
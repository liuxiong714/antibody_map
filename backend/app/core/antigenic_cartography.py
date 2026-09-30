"""
抗原制图引擎（antigenic cartography）

基于滴度矩阵的 metric MDS 降维，将抗原和血清映射到 2D 平面，
使欧氏距离逼近 log₂ 空间中的"表格距离"（column baseline − log₂ titer）。

参考：Smith et al. (2004) "Mapping the Antigenic and Genetic Evolution of Influenza Virus"
      Racmacs R package (https://github.com/acorg/racmacs)
"""

import logging

import numpy as np
from scipy.spatial import procrustes
from sklearn.manifold import MDS

logger = logging.getLogger("uvicorn")  # 与 llm_extractor 保持一致


# ---------------------------------------------------------------------------
# 预处理
# ---------------------------------------------------------------------------

def preprocess_titers(
    titers_2d: list[list[float | None]],
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
            表格距离矩阵 d_ij = cb_j − log2_ij；缺失/检出限单元格以检出限水平
            （log2 = 0，距离 = 列基准）填充，矩阵无 NaN。
        - column_baselines : np.ndarray (n_serum,)
            列基准 cb_j = max_i log2_ij（忽略 NaN；全缺列回退 0）。
        - dropped_rows : list[int]
            被剔除的行索引（行内零/缺失占比 > 50% 时整行剔除）。
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

    # --- Step 1b: 剔除行（仅当零/缺失占比 > 50% 才整行剔除）---
    # 与验收要求对齐：单个零（检出限）或零星缺失不再导致整行被丢弃，
    # 只有行内零/缺失占比超过 50% 时该抗原行才被剔除。
    missing_ratio_threshold = 0.5
    dropped_rows = []
    kept_rows = []
    for i in range(n_antigen):
        n_zero_or_nan = int(np.sum(np.isnan(log2_arr[i, :]) | (arr[i, :] == 0)))
        ratio = n_zero_or_nan / n_serum if n_serum else 0.0
        if ratio > missing_ratio_threshold:
            dropped_rows.append(i)
        else:
            kept_rows.append(i)

    # 排除后的矩阵
    if not kept_rows:
        raise ValueError("剔除后无有效行，无法进行抗原制图")

    kept_log2 = log2_arr[kept_rows, :]
    n_kept = len(kept_rows)

    # --- Step 2: 列基准 cb_j = max_i log2_ij（忽略 NaN；全缺列回退 0）---
    column_baselines = np.nanmax(kept_log2, axis=0)  # (n_serum,)
    column_baselines = np.where(np.isnan(column_baselines), 0.0, column_baselines)

    # --- Step 3: 表格距离 d_ij = cb_j − log2_ij ---
    # 保留行内的缺失/检出限值以"检出限水平（log2 = 0，距离 = 列基准）"填充，
    # 保证距离矩阵完整，可顺利进入 MDS（sklearn 要求矩阵无 NaN）。
    distances = np.full_like(kept_log2, np.nan)
    for j in range(n_serum):
        col_filled = np.where(np.isnan(kept_log2[:, j]), 0.0, kept_log2[:, j])
        distances[:, j] = column_baselines[j] - col_filled

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
    random_state: int | None = None,
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
# Bootstrap 置信椭圆（验证坐标稳定性）
# ---------------------------------------------------------------------------

# 二维正态 95% 置信椭圆系数：sqrt(χ²₂, 0.95) = sqrt(5.991)
_ELLIPSE_CHI2 = 5.991
_ELLIPSE_MIN_BOOT = 30


def _make_distances_from_log2(log2_mat: np.ndarray) -> np.ndarray:
    """由 log₂ 矩阵重算表格距离（列基准 − log2），缺失/检位以 0 填充。

    与 preprocess_titers 第 2/3 步的口径完全一致，用于 bootstrap 重采样感染矩阵。
    """
    col_base = np.nanmax(log2_mat, axis=0)
    col_base = np.where(np.isnan(col_base), 0.0, col_base)
    filled = np.where(np.isnan(log2_mat), 0.0, log2_mat)
    return col_base[None, :] - filled


def mds_bootstrap_ellipses(
    kept_log2: np.ndarray,
    n_antigen: int,
    main_coords: np.ndarray,
    n_boot: int = 100,
    seed: int | None = None,
) -> list[dict] | None:
    """对 MDS 坐标做血清 bootstrap 并在每次重采样上用 Procrustes 对齐主解。

    Parameters
    ----------
    kept_log2 : np.ndarray (n_antigen, n_serum)
        剔除坏行后的 log₂ 变换矩阵（即 preprocess_titers 的 ``log2_matrix``）。
    n_antigen : int
        抗原数量（用于重排完全距离矩阵的维度划分）。
    main_coords : np.ndarray (n_total, 2)
        主 MDS 解坐标（作为 Procrustes 对齐基准）。
    n_boot : int
        重采样次数（默认 100）。
    seed : int or None
        随机种子，保证结果可复现。

    Returns
    -------
    list[dict] or None
        与 ``main_coords`` 逐点对应的椭圆参数 ``{cx, cy, rx, ry, angle_deg, n_boot}``；
        ``rx/ry`` 为 95% 置信椭圆半轴长，``angle_deg`` 为主轴倾角。
        有效重采样不足时返回 None（不输出误导性椭圆）。
    """
    n_serum = kept_log2.shape[1]
    n_total = int(main_coords.shape[0])
    rng = np.random.RandomState(seed)

    boots = np.empty((n_boot, n_total, 2), dtype=float)
    ok = 0
    for _b in range(n_boot):
        cols = rng.choice(n_serum, size=n_serum, replace=True)
        sub = kept_log2[:, cols]
        dist = _make_distances_from_log2(sub)
        full = _build_full_distance_matrix(dist, n_antigen, n_serum)
        try:
            boot = compute_mds(
                full, n_components=2, n_init=1, max_iter=1000,
                random_state=int(rng.randint(0, 2 ** 31 - 1)),
            )["coordinates"]
            aligned, _, _ = procrustes(boot, main_coords)
        except (ValueError, FloatingPointError):
            continue
        boots[ok] = aligned
        ok += 1

    if ok < _ELLIPSE_MIN_BOOT:
        return None
    boots = boots[:ok]

    factor = float(np.sqrt(_ELLIPSE_CHI2))
    ellipses = []
    for i in range(n_total):
        pts = boots[:, i, :]
        d = pts - pts.mean(axis=0)
        cov = (d.T @ d) / (ok - 1) if ok > 1 else np.zeros((2, 2))
        # 协方差的特征分解（eigh 升序：λ0<=λ1）
        lam, vec = np.linalg.eigh(cov)
        lam = np.maximum(lam, 0.0)
        rx = factor * float(np.sqrt(lam[1]))  # 主轴（最大方差方向）半长
        ry = factor * float(np.sqrt(lam[0]))
        # 主轴倾角：最大特征值对应特征向量的方向角
        angle = float(np.degrees(np.arctan2(vec[1, 1], vec[0, 1])))
        ellipses.append({
            "cx": float(main_coords[i, 0]),
            "cy": float(main_coords[i, 1]),
            "rx": rx,
            "ry": ry,
            "angle_deg": round(angle, 2),
            "n_boot": ok,
        })
    return ellipses


# ---------------------------------------------------------------------------
# 完整管线
# ---------------------------------------------------------------------------

def antigenic_map(
    titers_2d: list[list[float | None]],
    antigen_names: list[str] | None = None,
    serum_names: list[str] | None = None,
    log2_divisor: float = 10.0,
    n_init: int = 20,
    max_iter: int = 1000,
    random_state: int | None = None,
    bootstrap: bool = True,
    n_boot: int = 100,
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
    bootstrap : bool
        是否计算血清 bootstrap 置信椭圆（默认开启）。
    n_boot : int
        bootstrap 重采样次数。
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
        - confidence_ellipses : list[dict] | None
            与 coordinates 逐点对应的 95% bootstrap 置信椭圆（bootstrap=True 时计算）。
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

    # Bootstrap 置信椭圆（血清重采样 + Procrustes 对齐主解）
    if bootstrap:
        try:
            result["confidence_ellipses"] = mds_bootstrap_ellipses(
                pre["log2_matrix"], n_antigen, coords,
                n_boot=n_boot, seed=random_state,
            )
        except Exception as e:  # 兜底：bootstrap 失败不影响主制图结果
            logger.warning("[抗原制图] bootstrap 置信椭圆计算失败: %s", e)
            result["confidence_ellipses"] = None
    else:
        result["confidence_ellipses"] = None

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
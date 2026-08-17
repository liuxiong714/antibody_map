"""antigenic_cartography.py 单元测试：预处理 + metric MDS + Procrustes 验收。

覆盖验收点：
- 预处理：log₂(titer/10)、列基准 cb_j = max_i t_ij、表格距离 d_ij = cb_j − t_ij、
  检出限(<10) 行剔除并记录 dropped
- metric MDS：多点初值取最优、输出 2D 坐标 / stress / stress_per_point、收敛标志
- 验收：Racmacs 风格 8×10 HI 表对照 —— 两实现（sklearn MDS vs scipy.optimize 参考实现）
  stress 同数量级、Procrustes 相关性 > 0.95
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import minimize
from scipy.spatial import procrustes

from app.core.antigenic_cartography import (
    preprocess_titers,
    compute_mds,
    _build_full_distance_matrix,
    antigenic_map,
    procrustes_compare,
    RACMACS_STYLE_HI_TABLE,
    RACMACS_STYLE_ANTIGEN_NAMES,
    RACMACS_STYLE_SERUM_NAMES,
)


# ---------------------------------------------------------------------------
# 参考实现：独立的 metric MDS（scipy.optimize 最小化原始 stress）
# ---------------------------------------------------------------------------

def _pairwise_dist(coords: np.ndarray) -> np.ndarray:
    n = coords.shape[0]
    diff = coords[:, None, :] - coords[None, :, :]
    return np.sqrt(np.sum(diff ** 2, axis=2))


def _raw_stress(coords: np.ndarray, distances: np.ndarray) -> float:
    triu = np.triu_indices(distances.shape[0], k=1)
    embed = _pairwise_dist(coords)
    return float(np.sum((distances[triu] - embed[triu]) ** 2))


def reference_metric_mds(
    distances: np.ndarray,
    n_components: int = 2,
    n_init: int = 5,
    max_iter: int = 1000,
    seed: int = 42,
) -> tuple[np.ndarray, float]:
    """独立的 metric MDS 参考实现（scipy.optimize.minimize 最小化原始 stress）。

    以经典 MDS（Torgerson）结果为初值，再叠加随机初值多点择优。
    """
    n = distances.shape[0]

    # 经典 MDS 初值（双中心化 + 特征分解）
    def classical_mds_init() -> np.ndarray:
        J = np.eye(n) - np.ones((n, n)) / n
        B = -0.5 * J @ distances ** 2 @ J
        eigvals, eigvecs = np.linalg.eigh(B)
        idx = np.argsort(eigvals)[::-1][:n_components]
        return eigvecs[:, idx] @ np.diag(np.sqrt(np.maximum(eigvals[idx], 0.0)))

    rng = np.random.RandomState(seed)
    best_x, best_f = None, np.inf
    inits = [classical_mds_init()] + [rng.randn(n, n_components) * 2 for _ in range(n_init - 1)]
    for x0 in inits:
        res = minimize(
            lambda x: _raw_stress(x.reshape(n, n_components), distances),
            x0.ravel(),
            method="BFGS",
            options={"maxiter": max_iter},
        )
        if res.fun < best_f:
            best_f = res.fun
            best_x = res.x.reshape(n, n_components)
    return best_x, best_f


class TestPreprocessTiters:
    def test_log2_transform(self):
        # titer=10 → log2(1)=0；titer=640 → log2(64)=6
        pre = preprocess_titers([[10, 640, 40], [320, 20, 80]])
        log2 = pre["log2_matrix"]
        assert log2[0, 0] == pytest.approx(0.0)
        assert log2[0, 1] == pytest.approx(6.0)
        assert log2[1, 0] == pytest.approx(5.0)
        assert log2[1, 2] == pytest.approx(3.0)

    def test_column_baseline_and_distance(self):
        # 列基准 cb_j = max_i log2_ij；表格距离 d_ij = cb_j − log2_ij
        # 行0: [640, 320] → log2 [6,5]；行1: [80, 640] → log2 [3,6]
        pre = preprocess_titers([[640, 320], [80, 640]])
        assert pre["column_baselines"][0] == pytest.approx(6.0)
        assert pre["column_baselines"][1] == pytest.approx(6.0)
        assert pre["distances"][0, 0] == pytest.approx(0.0)  # 6-6
        assert pre["distances"][0, 1] == pytest.approx(1.0)  # 6-5
        assert pre["distances"][1, 0] == pytest.approx(3.0)  # 6-3
        assert pre["distances"][1, 1] == pytest.approx(0.0)  # 6-6

    def test_below_detection_limit_row_dropped(self):
        # 含 <10（记 0）的行被剔除并记录 dropped
        pre = preprocess_titers([[640, 320], [0, 640], [80, 160]])
        assert pre["dropped_rows"] == [1]
        assert pre["n_antigen"] == 2
        assert 1 not in pre["kept_row_indices"]

    def test_all_rows_dropped_raises(self):
        with pytest.raises(ValueError):
            preprocess_titers([[0, 0], [0, 640]])

    def test_nan_treated_as_dropped(self):
        # None（NaN）也触发行剔除
        pre = preprocess_titers([[640, None], [80, 320]])
        assert 0 in pre["dropped_rows"]

    def test_grid_explanation(self):
        pre = preprocess_titers([[640, 320], [80, 640]])
        assert "2 倍滴度差" in pre["grid_explanation"]


class TestComputeMDS:
    def test_output_structure(self):
        # 5×5 对称距离矩阵（3 点 + 2 点）
        dist = np.array([
            [0, 1, 2, 2, 3],
            [1, 0, 2, 1, 3],
            [2, 2, 0, 3, 1],
            [2, 1, 3, 0, 2],
            [3, 3, 1, 2, 0],
        ], dtype=float)
        res = compute_mds(dist, random_state=0)
        assert res["coordinates"].shape == (5, 2)
        assert res["stress_raw"] >= 0
        assert len(res["stress_per_point"]) == 5
        assert isinstance(res["converged"], bool)
        assert res["n_iter"] > 0

    def test_random_state_reproducible(self):
        dist = np.random.RandomState(1).rand(6, 6)
        dist = (dist + dist.T) / 2
        np.fill_diagonal(dist, 0)
        a = compute_mds(dist, random_state=7)
        b = compute_mds(dist, random_state=7)
        np.testing.assert_allclose(a["coordinates"], b["coordinates"], atol=1e-6)


class TestAntigenicMap:
    def test_racmacs_table_structure(self):
        res = antigenic_map(
            RACMACS_STYLE_HI_TABLE,
            antigen_names=RACMACS_STYLE_ANTIGEN_NAMES,
            serum_names=RACMACS_STYLE_SERUM_NAMES,
            random_state=42,
        )
        coords = res["coordinates"]
        assert len(coords) == 18  # 8 抗原 + 10 血清
        types = {c["type"] for c in coords}
        assert types == {"antigen", "serum"}
        # 前 8 个是抗原，后 10 个是血清
        assert coords[0]["type"] == "antigen"
        assert coords[0]["name"] == "A/Cal/07/09"
        assert coords[8]["type"] == "serum"
        assert coords[8]["name"] == "Anti-A/Cal"
        for c in coords:
            assert set(c.keys()) == {"name", "type", "x", "y"}
            assert isinstance(c["x"], float) and isinstance(c["y"], float)
        assert res["stress_raw"] >= 0
        assert "2 倍滴度差" in res["grid_explanation"]
        assert res["n_antigen"] == 8
        assert res["n_serum"] == 10
        assert res["dropped_rows"] == []

    def test_names_after_dropped_row(self):
        # 第 2 行含检出限(0) → 被剔除；坐标中抗原名仍与原始索引对齐
        table = [[640, 1280, 40], [0, 320, 640], [160, 40, 1280]]
        names = ["Ag0", "Ag1_drop", "Ag2"]
        res = antigenic_map(table, antigen_names=names, random_state=42)
        coord_names = [c["name"] for c in res["coordinates"] if c["type"] == "antigen"]
        assert coord_names == ["Ag0", "Ag2"]
        assert res["dropped_rows"] == [1]
        assert res["n_antigen"] == 2


class TestProcrustesCompare:
    def test_identical_coords(self):
        rng = np.random.RandomState(0)
        a = rng.randn(10, 2)
        pc = procrustes_compare(a, a)
        assert pc["correlation"] == pytest.approx(1.0, abs=1e-9)
        assert pc["disparity"] == pytest.approx(0.0, abs=1e-9)

    def test_rotation_scale_translation(self):
        rng = np.random.RandomState(1)
        a = rng.randn(12, 2)
        theta = 0.7
        R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        b = (a @ R) * 2.0 + np.array([5.0, -3.0])
        pc = procrustes_compare(a, b)
        assert pc["correlation"] > 0.999

    def test_reflection_invariant(self):
        # 镜像（翻转 x 轴）也可被 Procrustes 对齐
        rng = np.random.RandomState(2)
        a = rng.randn(8, 2)
        b = a.copy()
        b[:, 0] *= -1
        pc = procrustes_compare(a, b)
        assert pc["correlation"] > 0.999


class TestAcceptanceRacmacsTwoImplementations:
    """验收：Racmacs 风格 8×10 HI 表，两实现 stress 同数量级 + Procrustes 相关性 > 0.95。"""

    def test_stress_same_order_of_magnitude(self):
        ours = antigenic_map(RACMACS_STYLE_HI_TABLE, random_state=42)
        pre = preprocess_titers(RACMACS_STYLE_HI_TABLE)
        full = _build_full_distance_matrix(pre["distances"], pre["n_antigen"], pre["n_serum"])
        _, ref_stress = reference_metric_mds(full, seed=42)

        ratio = ours["stress_raw"] / ref_stress
        assert 0.1 < ratio < 10, f"stress 数量级不一致: ours={ours['stress_raw']:.4f}, ref={ref_stress:.4f}"

    def test_procrustes_correlation_above_095(self):
        ours = antigenic_map(RACMACS_STYLE_HI_TABLE, random_state=42)
        pre = preprocess_titers(RACMACS_STYLE_HI_TABLE)
        full = _build_full_distance_matrix(pre["distances"], pre["n_antigen"], pre["n_serum"])
        ref_coords, _ = reference_metric_mds(full, seed=42)

        ours_coords = np.array([[c["x"], c["y"]] for c in ours["coordinates"]])
        pc = procrustes_compare(ours_coords, ref_coords)
        assert pc["correlation"] > 0.95, f"Procrustes 相关性过低: {pc['correlation']:.4f}"

    def test_shape_after_rotation_reflection(self):
        # 参考结果整体旋转+镜像后，Procrustes 相关性仍 > 0.95
        ours = antigenic_map(RACMACS_STYLE_HI_TABLE, random_state=42)
        pre = preprocess_titers(RACMACS_STYLE_HI_TABLE)
        full = _build_full_distance_matrix(pre["distances"], pre["n_antigen"], pre["n_serum"])
        ref_coords, _ = reference_metric_mds(full, seed=42)
        theta = 1.1
        R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        transformed = ref_coords @ R
        transformed[:, 0] *= -1  # 镜像
        ours_coords = np.array([[c["x"], c["y"]] for c in ours["coordinates"]])
        pc = procrustes_compare(ours_coords, transformed)
        assert pc["correlation"] > 0.95


class TestReferenceMDSVsSciPyProcrustes:
    """直接验证 scipy.spatial.procrustes 的 API 调用（保证测试代码自身正确）。"""

    def test_scipy_procrustes(self):
        rng = np.random.RandomState(5)
        a = rng.randn(9, 2)
        theta = 0.5
        R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        b = (a @ R) * 1.5 + np.array([2.0, 1.0])
        _, _, disparity = procrustes(a, b)
        correlation = 1.0 - disparity ** 2
        assert correlation > 0.95

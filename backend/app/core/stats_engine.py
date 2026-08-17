"""全局置信区间（CI）引擎：趋势 / 区域 / 年龄 / 汇总端点的统一统计计算。

约定：
- 全部为无副作用纯函数，不访问数据库；service 层负责取数（_build_base_query）
  → 调用本模块 → 组装响应。
- 比例相关返回 0-1 区间，调用方自行 ×100 转百分数；GMC 为对数域计算后指数还原。
- 边界约定：n == 0 / 空输入 → None；无副作用，不抛异常。

对外导出（__all__）：
- binomial_ci:        单比例二项分布 95% CI（Wilson score / Clopper-Pearson 精确法）
- weighted_rate_ci:   样本量加权阳性率 + 正态近似 95% CI
- gmc_ci:             几何均数（GMC）+ 对数域正态近似 95% CI（支持样本量加权）
- proportion_test_ci: 双比例之差的近似 95% CI（Wald）
- fit_age_curve:      血清阳性率-年龄曲线：惩罚样条平滑 P(a) + 95% 置信带（delta 法）
- foi_from_curve:     年龄别 FOI：λ(a) = P′(a)/(1−P(a))，P′ 用样条解析导数
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence, Tuple, Union

import numpy as np
import scipy.stats as sps
from scipy.interpolate import BSpline
from scipy.optimize import brentq, minimize
from statsmodels.stats.proportion import proportion_confint

__all__ = [
    "binomial_ci",
    "weighted_rate_ci",
    "gmc_ci",
    "proportion_test_ci",
    "fit_age_curve",
    "foi_from_curve",
    "meta_proportion",
    "fit_catalytic_models",
    "cochran_armitage_trend",
    "two_proportion_test",
    "direct_standardize",
    "morans_i",
    "g_star",
    "classify_hotspot_cluster",
    "birth_year_from_age",
    "decade_band",
    "birth_cohort_analysis",
]


# ============================================================
# 工具
# ============================================================

def _get(row: Any, key: str) -> Any:
    """兼容对象属性（ORM/SimpleNamespace）与 dict 两种行结构取字段。"""
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _as_percent(p: Any) -> Optional[float]:
    """把可能为百分数（>1）或 0-1 比例的输入归一为 0-1 比例；非法返回 None。"""
    if p is None:
        return None
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    if p > 1.0:
        p = p / 100.0
    if p < 0.0 or p > 1.0:
        return None
    return p


# ============================================================
# 1. 单比例二项分布 95% CI
# ============================================================

def binomial_ci(x: Any, n: Any, alpha: float = 0.05, method: str = "auto") -> Tuple[Optional[float], Optional[float]]:
    """单比例二项分布的 (1-alpha) 置信区间，返回 (ci_lower, ci_upper)（0-1 比例）。

    - x: 阳性数（整数）。调用方换算：x = round(seroprevalence/100 * sample_size)。
    - n: 样本量。n 缺失或 n == 0 → 返回 (None, None)。
    - method: ``auto``（默认）按 n 分流——n >= 30 用 Wilson score，n < 30 用
      Clopper-Pearson 精确法（beta 分布）；也可显式指定 ``wilson`` 或 ``beta``。
    - 底层直接调用 statsmodels.stats.proportion.proportion_confint。
    """
    if n is None:
        return (None, None)
    try:
        n = int(n)
    except (TypeError, ValueError):
        return (None, None)
    if n <= 0:
        return (None, None)
    if x is None:
        x = 0
    x = min(max(int(x), 0), n)

    if method == "auto":
        resolved = "wilson" if n >= 30 else "beta"
    elif method in ("wilson", "beta"):
        resolved = method
    else:
        raise ValueError(f"未知 binomial_ci method: {method!r}（可选 auto/wilson/beta）")

    lo, hi = proportion_confint(count=x, nobs=n, alpha=alpha, method=resolved)
    return (float(lo), float(hi))


# ============================================================
# 2. 样本量加权阳性率 + 正态近似 95% CI
# ============================================================

def weighted_rate_ci(rows: Sequence[Any], z: float = 1.96) -> dict:
    """样本量加权阳性率及正态近似 (1-alpha≈95%) CI。

    p̂_w = Σ nᵢ·pᵢ / Σ nᵢ
    SE   = √( Σ nᵢ²·pᵢ(1−pᵢ)/nᵢ ) / Σ nᵢ = √( Σ nᵢ·pᵢ(1−pᵢ) ) / Σ nᵢ
    CI   = p̂_w ± z·SE，clamp 到 [0, 1]

    - rows: 每行须含 value（阳性率，0-1 或百分数均可）与 sample_size。
    - 保守起见：任一行 sample_size 缺失或 ≤0 → 该行剔除并计入 ``n_dropped``。
    - 返回 ``{weighted_positivity, ci_lower, ci_upper, n_total, n_dropped, method}``，
      三个比例字段均为百分数（×100，保留 2 位小数）；无有效行时均为 None。
    """
    pairs: list[Tuple[float, float]] = []  # (p, n)
    dropped = 0
    for row in rows:
        p = _as_percent(_get(row, "value"))
        if p is None:
            continue
        n = _get(row, "sample_size")
        if n is None:
            dropped += 1
            continue
        try:
            n = float(n)
        except (TypeError, ValueError):
            dropped += 1
            continue
        if n <= 0:
            dropped += 1
            continue
        pairs.append((p, n))

    if not pairs:
        return {
            "weighted_positivity": None,
            "ci_lower": None,
            "ci_upper": None,
            "n_total": 0,
            "n_dropped": dropped,
            "method": "normal_approx",
        }

    w_sum = sum(n for _, n in pairs)
    p_hat = sum(n * p for p, n in pairs) / w_sum
    var_sum = sum(n * p * (1.0 - p) for p, n in pairs)  # n²·p(1−p)/n = n·p(1−p)
    se = math.sqrt(var_sum) / w_sum if var_sum > 0 else 0.0
    lo = max(0.0, p_hat - z * se)
    hi = min(1.0, p_hat + z * se)

    return {
        "weighted_positivity": round(p_hat * 100, 2),
        "ci_lower": round(lo * 100, 2),
        "ci_upper": round(hi * 100, 2),
        "n_total": int(round(w_sum)),
        "n_dropped": dropped,
        "method": "normal_approx",
    }


# ============================================================
# 3. GMC 几何均数 + 对数域正态近似 95% CI
# ============================================================

def gmc_ci(titers: Sequence[Any], weights: Optional[Sequence[Any]] = None, z: float = 1.96) -> dict:
    """几何均数（GMC）及对数域正态近似 95% CI。

    数据点存的是已计算好的 GMC 值（非原始滴度），对 k 个数据点取对数平均：
      gmc      = exp( mean(ln vᵢ) )            # weights 提供时按样本量加权
      mean_ln  = Σ wᵢ·ln vᵢ / Σ wᵢ
      var_ln   = Σ wᵢ·(ln vᵢ − mean_ln)² / (k−1)   # 频率权重归一后等价样本方差
      CI       = exp( mean_ln ± z·√(var_ln/k) )

    - 非正 / 缺失值剔除；weights 缺失或 ≤0 的行剔除并计入 ``n_dropped``。
    - k < 2 时 CI 为 (None, None)（无法估计标准差）。
    - 返回 ``{gmc, ci_lower, ci_upper, n, n_total, n_dropped, method}``；
      ``n`` 为参与计算的数据点数，``n_total`` 为样本量权重之和；空输入时均为 None。
    """
    if weights is None:
        weights = [1.0] * len(titers)

    vals: list[float] = []  # ln v
    ws: list[float] = []
    dropped = 0
    for v, w in zip(titers, weights):
        if v is None or v <= 0:
            continue
        if w is None or w <= 0:
            dropped += 1
            continue
        try:
            vals.append(math.log(float(v)))
            ws.append(float(w))
        except (TypeError, ValueError):
            continue

    k = len(vals)
    if k == 0:
        return {"gmc": None, "ci_lower": None, "ci_upper": None,
                "n": 0, "n_total": 0, "n_dropped": dropped, "method": "lognormal"}

    w_sum = sum(ws)
    mean_ln = sum(w * l for w, l in zip(ws, vals)) / w_sum
    gmc = math.exp(mean_ln)

    if k < 2:
        return {"gmc": round(gmc, 4), "ci_lower": None, "ci_upper": None,
                "n": k, "n_total": int(round(w_sum)), "n_dropped": dropped, "method": "lognormal"}

    # 频率权重归一（均值权重 = 1），使 var_ln 与样本方差同量纲
    norm = k / w_sum
    var_ln = sum(norm * w * (l - mean_ln) ** 2 for w, l in zip(ws, vals)) / (k - 1)
    se = math.sqrt(var_ln / k)
    lo = math.exp(mean_ln - z * se)
    hi = math.exp(mean_ln + z * se)
    return {
        "gmc": round(gmc, 4),
        "ci_lower": round(lo, 4),
        "ci_upper": round(hi, 4),
        "n": k,
        "n_total": int(round(w_sum)),
        "n_dropped": dropped,
        "method": "lognormal",
    }


# ============================================================
# 4. 双比例之差的近似 95% CI（Wald，暂未接入端点）
# ============================================================

def proportion_test_ci(p1: Any, n1: Any, p2: Any, n2: Any, z: float = 1.96) -> dict:
    """两独立比例之差 d = p1 − p2 的 Wald 近似 95% CI。

    SE = √( p1(1−p1)/n1 + p2(1−p2)/n2 )，CI = d ± z·SE，clamp 到 [-1, 1]。
    任一比例/样本量缺失或 n ≤ 0 → 返回 None。当前无端点接入（预留）。
    """
    p1f, p2f = _as_percent(p1), _as_percent(p2)
    if p1f is None or p2f is None:
        return {"diff": None, "ci_lower": None, "ci_upper": None, "method": "normal_approx"}
    try:
        n1f, n2f = float(n1), float(n2)
    except (TypeError, ValueError):
        return {"diff": None, "ci_lower": None, "ci_upper": None, "method": "normal_approx"}
    if n1f <= 0 or n2f <= 0:
        return {"diff": None, "ci_lower": None, "ci_upper": None, "method": "normal_approx"}
    d = p1f - p2f
    se = math.sqrt(p1f * (1.0 - p1f) / n1f + p2f * (1.0 - p2f) / n2f)
    return {
        "diff": round(d, 4),
        "ci_lower": round(max(-1.0, d - z * se), 4),
        "ci_upper": round(min(1.0, d + z * se), 4),
        "method": "normal_approx",
    }


# ============================================================
# 5. 血清阳性率-年龄曲线：惩罚样条平滑 P(a) + 置信带
# ============================================================

def _logistic(eta):
    """logit 逆变换，数值安全钳制到 (0,1)。"""
    eta = np.clip(eta, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-eta))


def _second_diff_penalty(m: int) -> np.ndarray:
    """m×m 二阶差分惩罚矩阵 P = DᵀD（D 为 (m-2)×m 的二阶差分算子）。

    使 βᵀ·P·β = Σ(Δ²β)²，即对相邻系数二阶差分平方和施加惩罚。
    """
    D = np.zeros((max(m - 2, 1), m))
    for i in range(m - 2):
        D[i, i] = 1.0
        D[i, i + 1] = -2.0
        D[i, i + 2] = 1.0
    return D.T @ D


def fit_age_curve(records: Sequence[Tuple[Any, Any, Any]], z: float = 1.96) -> dict:
    """惩罚样条平滑拟合血清阳性率-年龄曲线 P(a)。

    输入 ``records``：[(age_mid, x, n), ...]——由 service 层按 age_mid 汇总
    （同中点合并 x、n）后的数据点；x 为阳性数，n 为样本量。

    方法：
    - 基函数：自然三次 B-spline（scipy.interpolate.BSpline，k=3），内部结点数
      ``k = min(8, max(3, n_records//3))``，等距放在数据年龄范围，边界 4 重钳制。
    - 目标：惩罚二项负对数似然 Σ[nᵢ·yᵢ·log pᵢ + nᵢ(1−yᵢ)·log(1−pᵢ)] 的负值
      + λp·Σ(Δ²β)²，logit(p) = Bβ，用 scipy.optimize.minimize(L-BFGS-B) 求解。
    - 平滑参数 λp 在 {1e-3..1e2 对数 12 点} 网格上用加权 GCV 自动选优。
    - 置信带：delta 法对拟合 logit 取 ±z·√(b·Cov·bᵀ)（Cov=(H+λP)⁻¹，H=Σn·p(1−p)BᵀB），
      再逆 logit 还原，输出 0.5 岁步长的 (age, p, lo, hi)。

    返回 dict（无副作用）：
    - ``spline``: 拟合好的 BSpline（**logit 尺度** η(a)，可调用），供 foi_from_curve
      求解析导数（λ(a) = logistic(η)·η′）
    - ``curve``:  [{age, prevalence, ci_lower, ci_upper}]（百分数，0.5 岁步长）
    - ``lambda_smooth``: 选优后的平滑参数
    - ``df``: 有效自由度
    - ``monotonic_violation``: 曲线在年龄方向是否出现下降段（True 供前端提示）
    - ``n_records`` / ``age_range``: 输入规模与年龄范围
    """
    n_records = len(records)
    if n_records == 0:
        return {
            "spline": None, "curve": [], "lambda_smooth": None, "df": 0.0,
            "monotonic_violation": False, "n_records": 0, "age_range": [None, None],
        }

    ages = np.array([float(r[0]) for r in records], dtype=float)
    xs = np.array([float(r[1]) for r in records], dtype=float)
    ns = np.array([float(r[2]) for r in records], dtype=float)
    # y 钳制避免 log(0)/log(1) 数值问题
    y = np.clip(xs / ns, 1e-4, 1.0 - 1e-4)

    a, b = float(ages.min()), float(ages.max())
    if b - a < 1e-9:
        b = a + 1.0

    # 内部结点数（自然三次 B-spline 基础配置）
    k = min(8, max(3, n_records // 3))
    interior = np.linspace(a, b, k + 2)[1:-1]
    t = np.concatenate(([a] * 4, interior, [b] * 4))  # 边界 4 重钳制（k=3）
    k_degree = 3

    B = BSpline.design_matrix(ages, t, k_degree).toarray()  # (n, m)
    m = B.shape[1]
    P = _second_diff_penalty(m)

    def penalized_nll(beta: np.ndarray, lam: float) -> float:
        p = _logistic(B @ beta)
        nll = -float(np.sum(ns * (y * np.log(p) + (1.0 - y) * np.log(1.0 - p))))
        pen = 0.5 * lam * float(beta @ P @ beta)
        return nll + pen

    def gcv_for(lam: float):
        """返回 (gcv, beta, df) 或 None（求解失败）。"""
        res = minimize(penalized_nll, x0=np.zeros(m), args=(lam,),
                       method="L-BFGS-B", options={"maxiter": 500})
        if not res.success and not np.all(np.isfinite(res.x)):
            return None
        beta = res.x
        p = _logistic(B @ beta)
        W = np.diag(ns * p * (1.0 - p))
        G = B.T @ W @ B
        Hp = G + lam * P
        try:
            df = float(np.trace(np.linalg.solve(Hp, G)))
        except np.linalg.LinAlgError:
            df = float(m)
        resid = float(np.sum(ns * (y - p) ** 2))
        denom = (1.0 - df / max(n_records, 1)) ** 2
        gcv = resid / denom if denom > 1e-12 else float("inf")
        return (gcv, beta, df)

    # λp 网格 {1e-3..1e2 对数 12 点} 加权 GCV 选优
    lam_grid = np.logspace(-3.0, 2.0, 12)
    lam_opt: Optional[float] = None
    beta_opt: Optional[np.ndarray] = None
    df_opt = float(m)
    best_gcv = float("inf")
    for lam in lam_grid:
        cand = gcv_for(float(lam))
        if cand is None:
            continue
        if cand[0] < best_gcv:
            best_gcv = cand[0]
            lam_opt = float(lam)
            beta_opt = cand[1]
            df_opt = cand[2]
    if beta_opt is None:  # 全部求解失败 → 退化为 λ=0 直接拟合
        cand = gcv_for(0.0)
        if cand is None:
            return {"spline": None, "curve": [], "lambda_smooth": None, "df": 0.0,
                    "monotonic_violation": False, "n_records": n_records,
                    "age_range": [a, b]}
        beta_opt = cand[1]
        df_opt = cand[2]
        lam_opt = 0.0

    spline = BSpline(t, beta_opt, k_degree)

    # 0.5 岁步长预测网格（对齐到 0.5 的整数倍，覆盖 [a, b]）
    start = math.ceil(a * 2) / 2.0
    end = math.floor(b * 2) / 2.0
    grid = np.arange(start, end + 1e-9, 0.5)
    if grid.size == 0 or grid[-1] < b - 1e-9:
        grid = np.append(grid, b)

    Bg = BSpline.design_matrix(grid, t, k_degree).toarray()
    eta_g = Bg @ beta_opt
    p_g = _logistic(eta_g)

    # delta 法置信带：Var(η) = b·Cov·bᵀ
    p_dat = _logistic(B @ beta_opt)
    W = np.diag(ns * p_dat * (1.0 - p_dat))
    G = B.T @ W @ B
    try:
        Cov = np.linalg.inv(G + (lam_opt or 0.0) * P)
    except np.linalg.LinAlgError:
        Cov = np.linalg.pinv(G + (lam_opt or 0.0) * P)
    se_g = np.sqrt(np.maximum(np.sum((Bg @ Cov) * Bg, axis=1), 0.0))
    lo_g = _logistic(eta_g - z * se_g)
    hi_g = _logistic(eta_g + z * se_g)

    # 单调性检查：阳性率-年龄曲线预期非减，出现明显下降段视为违规
    monotonic_violation = bool(np.any(np.diff(p_g) < -0.005)) if len(p_g) > 1 else False

    curve = [
        {
            "age": round(float(ag), 1),
            "prevalence": round(float(pv) * 100.0, 2),
            "ci_lower": round(float(lo) * 100.0, 2),
            "ci_upper": round(float(hi) * 100.0, 2),
        }
        for ag, pv, lo, hi in zip(grid, p_g, lo_g, hi_g)
    ]

    return {
        "spline": spline,
        "curve": curve,
        "lambda_smooth": lam_opt,
        "df": float(df_opt),
        "monotonic_violation": monotonic_violation,
        "n_records": n_records,
        "age_range": [float(a), float(b)],
    }


# ============================================================
# 6. 年龄别 FOI：λ(a) = P′(a)/(1−P(a))
# ============================================================

def foi_from_curve(ages: Sequence[Any], p_hat: Any) -> List[dict]:
    """由拟合的阳性率曲线 P(a) 计算年龄别 FOI。

    λ(a) = P′(a) / (1 − P(a))。

    - ``p_hat`` 为 fit_age_curve 返回的 BSpline（logit 尺度 η(a)）时，用解析导数：
      P = logistic(η)，P′ = P(1−P)·η′，故 λ = P·η′（与 P′/(1−P) 数学等价）。
    - 若 ``p_hat`` 为普通可调用对象（0-1 尺度概率函数），退化为中心差分数值微分
      λ = P′/(1−P)。
    数值安全：P(a) ≥ 0.999 时 λ 置 None（分母过小不稳定）。

    返回 [{age, foi}]；foi 单位为 /年，None 表示数值不安全。
    """
    ages_f = [float(x) for x in ages]
    arr = np.array(ages_f, dtype=float)

    if isinstance(p_hat, BSpline):
        # logit 尺度样条：η(a)，解析导数 η′(a)
        deriv = p_hat.derivative()
        eta = np.asarray(p_hat(arr), dtype=float)
        p = _logistic(eta)
        deta = np.asarray(deriv(arr), dtype=float)
        lam = p * deta  # P(1−P)·η′/(1−P) = P·η′
    else:
        # 概率尺度可调用对象：数值微分 λ = P′/(1−P)
        h = 1e-4
        p = np.clip(np.asarray([float(p_hat(x)) for x in arr], dtype=float), 0.0, 1.0)
        dp = np.asarray(
            [(float(p_hat(x + h)) - float(p_hat(x - h))) / (2.0 * h) for x in arr],
            dtype=float,
        )
        lam = np.where(p < 1.0, dp / np.maximum(1.0 - p, 1e-9), 0.0)

    out: List[dict] = []
    for ag, pv, lamv in zip(ages_f, p, lam):
        if pv >= 0.999:
            out.append({"age": round(ag, 1), "foi": None})
        else:
            out.append({"age": round(ag, 1), "foi": round(float(max(lamv, 0.0)), 4)})
    return out


# ============================================================
# 7. 多研究血清阳性率 Meta 分析（Freeman-Tukey 双反正弦变换）
# ============================================================

_FT_TOL = 1e-6  # 逆变换数值容差


def _ft_transform(x: float, n: float) -> float:
    """Freeman-Tukey 双反正弦变换（适用于比例，包括 0 和 1）。
    
    t = arcsin(√(x/(n+1))) + arcsin(√((x+1)/(n+1)))
    v = 1/(n+0.5)
    
    Reference: Freeman & Tukey (1950), Miller (1978).
    """
    n1 = n + 1.0
    p_lo = x / n1
    p_hi = (x + 1.0) / n1
    return math.asin(math.sqrt(p_lo)) + math.asin(math.sqrt(p_hi))


def _ft_variance(n: float) -> float:
    """FT 变换的近似方差。"""
    return 1.0 / (n + 0.5)


def _ft_inverse(t: float, n: float = 1e6) -> float:
    """FT 双反正弦变换的数值逆变换：搜索 p ∈ [0,1] 使正变换等于 t。

    用 scipy.optimize.brentq 在 p ∈ [0,1] 上求解：
        FT(p·n, n) = arcsin(√(p·n/(n+1))) + arcsin(√((p·n+1)/(n+1))) = t

    - t 定义域 [0, π]（任务规格）。n 为代表性样本量：pooled 逆变换取各研究
      样本量的调和均值（与 Miller 1978 / Barendregt 2013 口径一致），
      per-study 逆变换取该研究自身 n。
    - 对给定 n，可逆 t 范围是 [asin(√(1/(n+1))), asin(√(n/(n+1)))+π/2]，
      越界钳制到 0/1；否则 brentq 精确求解。
    """
    t = max(0.0, min(float(t), math.pi))
    n1 = n + 1.0
    t0 = math.asin(math.sqrt(1.0 / n1))                  # p=0 时的 t
    t1 = math.asin(math.sqrt(n / n1)) + math.pi / 2.0    # p=1 时的 t
    if t <= t0:
        return 0.0
    if t >= t1:
        return 1.0

    def _f(p):
        return _ft_transform(p * n, n) - t

    try:
        p = brentq(_f, 0.0, 1.0, xtol=_FT_TOL)
        return max(0.0, min(1.0, p))
    except ValueError:
        # brentq 未找到根（理论不应发生）：按边界钳制
        return 0.0 if t < (t0 + t1) / 2.0 else 1.0


def _egger_test(studies: list) -> dict:
    """简化版 Egger 检验：对 t 对 √n 的加权线性回归显著性。
    
    Reference: Egger et al. (1997) BMJ 315:629-634.
    简化版：以 SE=√(1/n) 为精度权重，对 tᵢ 对 √nᵢ 做加权 OLS，
    检验截距是否显著偏离 0（不对称指示）。
    """
    k = len(studies)
    if k < 10:
        return {"intercept": None, "p_value": None, "note": "k<10, 未计算 Egger 检验"}
    
    sqrt_n = np.array([s["sqrt_n"] for s in studies], dtype=float)
    t = np.array([s["t"] for s in studies], dtype=float)
    se = np.array([s["se"] for s in studies], dtype=float)
    
    # 精度权重 w = 1/se
    w = 1.0 / np.maximum(se, 1e-12)
    
    # 加权回归：t = a + b * sqrt_n，权重 w
    # 加权均值
    w_sum = np.sum(w)
    w_mean_t = np.sum(w * t) / w_sum
    w_mean_sn = np.sum(w * sqrt_n) / w_sum
    
    # 加权协方差/方差
    w_cov = np.sum(w * (t - w_mean_t) * (sqrt_n - w_mean_sn)) / w_sum
    w_var_sn = np.sum(w * (sqrt_n - w_mean_sn) ** 2) / w_sum
    
    if w_var_sn < 1e-15:
        return {"intercept": None, "p_value": None, "note": "方差过小，无法计算回归"}
    
    b = w_cov / w_var_sn  # 斜率
    a = w_mean_t - b * w_mean_sn  # 截距
    
    # 残差标准误
    residuals = t - (a + b * sqrt_n)
    mse = np.sum(w * residuals ** 2) / (k - 2) if k > 2 else 0.0
    if mse <= 0 or k <= 2:
        return {"intercept": round(float(a), 4), "p_value": None, "note": "自由度不足，无法计算 p 值"}
    
    # 截距的标准误
    se_a = math.sqrt(mse * (1.0 / w_sum + w_mean_sn ** 2 / (w_sum * w_var_sn)))
    if se_a < 1e-12:
        return {"intercept": round(float(a), 4), "p_value": None, "note": "截距 SE 过小"}
    
    t_stat = a / se_a
    df = k - 2
    p_value = 2.0 * (1.0 - sps.t.cdf(abs(t_stat), df))
    
    return {
        "intercept": round(float(a), 4),
        "p_value": round(float(p_value), 6),
        "note": "Egger 简化版：加权回归截距检验",
    }


def meta_proportion(
    studies: Sequence[Tuple[float, float, Optional[str]]],
    alpha: float = 0.05,
) -> dict:
    """多研究血清阳性率的随机效应 Meta 合并（Freeman-Tukey 双反正弦变换）。
    
    Parameters
    ----------
    studies : Sequence[Tuple[x, n, label]]
        每项研究为 (x, n, label)，x=阳性数，n=样本量，label=研究标签（可选）。
    alpha : float
        显著性水平，默认 0.05（95% CI）。
    
    Returns
    -------
    dict 含：
        - per_study: [{"label","x","n","p","t","se","weight_fe","weight_re","sqrt_n"}, ...]
        - pooled: {rate, ci_lower, ci_upper, model, tau2, tau2_se, Q, Q_p, I2, k, se, z}
        - funnel: [{"t","sqrt_n"}, ...] 或 None（k<10）
        - egger: {intercept, p_value, note} 或 None（k<10）
        - primary_model: "fixed" | "random"
        - notes: [str]
    
    Algorithm
    ---------
    1. Freeman-Tukey 双反正弦变换: tᵢ = arcsin√(x/(n+1)) + arcsin√((x+1)/(n+1))
       vᵢ = 1/(n+0.5)
    2. 固定效应: wᵢ=1/vᵢ → t_pool = Σwᵢtᵢ/Σwᵢ
       Q = Σwᵢ(tᵢ−t_pool)², df=k−1, p via chi2.sf(Q, df)
       I² = max(0, (Q−df)/Q)·100%
    3. τ² (DerSimonian-Laird): C = Σwᵢ − Σwᵢ²/Σwᵢ
       τ² = max(0, (Q−df)/C)
    4. 随机效应: wᵢ* = 1/(vᵢ+τ²) → t_pool*
       SE = √(1/Σwᵢ*), CI = t* ± z·SE
    5. 逆变换: 对合并 t 用 brentq 解出比例 p
    6. 模型选择: Q 检验 p<0.10 或 I²>50% → 随机效应为主结果，否则固定效应
    7. k==1: 直接返回二项 CI
    8. k>=10: 附带漏斗图数据与简化版 Egger 检验
    
    Reference
    ---------
    - Freeman & Tukey (1950) Ann Math Stat 21:607-611
    - Miller (1978) JASA 73:87-95
    - DerSimonian & Laird (1986) Control Clin Trials 7:177-188
    - Egger et al. (1997) BMJ 315:629-634
    """
    # ── 解析输入 ────────────────────────────────────────────
    parsed: list[dict] = []
    for x, n, label in studies:
        if n is None or n <= 0:
            continue
        try:
            xf = float(x)
            nf = float(n)
        except (TypeError, ValueError):
            continue
        xf = max(0.0, min(xf, nf))
        lbl = str(label) if label else f"研究{len(parsed)+1}"
        parsed.append({"x": xf, "n": nf, "label": lbl})
    
    k = len(parsed)
    z = sps.norm.ppf(1.0 - alpha / 2.0)
    
    # ── k=0 ────────────────────────────────────────────────
    if k == 0:
        return {
            "per_study": [],
            "pooled": {"rate": None, "ci_lower": None, "ci_upper": None,
                       "model": None, "tau2": 0.0, "tau2_se": None,
                       "Q": 0.0, "Q_p": None, "I2": 0.0, "k": 0, "se": None, "z": z},
            "funnel": None,
            "egger": None,
            "primary_model": None,
            "notes": ["无有效研究，无法合并"],
        }
    
    # ── k=1：直接返回二项 CI ───────────────────────────────
    if k == 1:
        s = parsed[0]
        x, n = s["x"], s["n"]
        lo, hi = binomial_ci(x=int(round(x)), n=int(round(n)))
        p = x / n if n > 0 else 0.0
        ci_lower = lo * 100.0 if lo is not None else None
        ci_upper = hi * 100.0 if hi is not None else None
        return {
            "per_study": [{
                "label": s["label"],
                "x": int(round(x)),
                "n": int(round(n)),
                "p": round(p, 6),
                "weight": 100.0,                          # 主模型权重(%)
                "transformed": round(_ft_transform(x, n), 6),  # FT 变换值 t
                "t": round(_ft_transform(x, n), 6),
                "se": round(_ft_variance(n) ** 0.5, 6),
                "weight_fe": 100.0,
                "weight_re": 100.0,
                "sqrt_n": round(math.sqrt(n), 2),
            }],
            "pooled": {
                "rate": round(p * 100.0, 2),
                "ci_lower": round(ci_lower, 2) if ci_lower is not None else None,
                "ci_upper": round(ci_upper, 2) if ci_upper is not None else None,
                "model": "single_study",
                "tau2": 0.0,
                "tau2_se": None,
                "Q": 0.0,
                "Q_p": None,
                "I2": 0.0,
                "k": 1,
                "se": round(p * (1.0 - p) / n, 6) if n > 0 else None,
                "z": z,
            },
            "funnel": None,
            "egger": None,
            "primary_model": "single_study",
            "notes": ["仅 1 项研究，直接返回二项 CI"],
        }
    
    # ── FT 变换 ─────────────────────────────────────────────
    for s in parsed:
        s["t"] = _ft_transform(s["x"], s["n"])
        s["v"] = _ft_variance(s["n"])
        s["w_fe"] = 1.0 / s["v"]
        s["sqrt_n"] = math.sqrt(s["n"])
        s["se"] = math.sqrt(s["v"])
    
    # ── 固定效应 ────────────────────────────────────────────
    w_sum = sum(s["w_fe"] for s in parsed)
    t_fe = sum(s["w_fe"] * s["t"] for s in parsed) / w_sum
    
    Q = sum(s["w_fe"] * (s["t"] - t_fe) ** 2 for s in parsed)
    df = k - 1
    Q_p = float(sps.chi2.sf(Q, df))
    I2 = max(0.0, (Q - df) / Q) * 100.0 if Q > 0 else 0.0
    
    # ── DerSimonian-Laird τ² ────────────────────────────────
    w2_sum = sum(s["w_fe"] ** 2 for s in parsed)
    C = w_sum - w2_sum / w_sum
    tau2 = max(0.0, (Q - df) / C) if C > 0 and Q > df else 0.0
    
    # ── 随机效应 ────────────────────────────────────────────
    for s in parsed:
        s["w_re"] = 1.0 / (s["v"] + tau2)
    w_re_sum = sum(s["w_re"] for s in parsed)
    t_re = sum(s["w_re"] * s["t"] for s in parsed) / w_re_sum
    se_re = math.sqrt(1.0 / w_re_sum)
    ci_lo_re = t_re - z * se_re
    ci_hi_re = t_re + z * se_re
    
    # 固定效应 SE
    se_fe = math.sqrt(1.0 / w_sum)
    ci_lo_fe = t_fe - z * se_fe
    ci_hi_fe = t_fe + z * se_fe
    
    # ── 权重百分数 ──────────────────────────────────────────
    for s in parsed:
        s["pct_fe"] = s["w_fe"] / w_sum * 100.0 if w_sum > 0 else 0.0
        s["pct_re"] = s["w_re"] / w_re_sum * 100.0 if w_re_sum > 0 else 0.0
    
    # ── 模型选择 ────────────────────────────────────────────
    use_random = (Q_p < 0.10) or (I2 > 50.0)
    primary_model = "random" if use_random else "fixed"
    
    # ── 逆变换 ──────────────────────────────────────────────
    # 代表性样本量 = 调和均值（Miller 1978 口径，小样本校正）
    n_rep = k / sum(1.0 / s["n"] for s in parsed) if k else 0.0

    def _pool_result(t_pool, ci_lo, ci_hi, se, model_name):
        p_pool = _ft_inverse(t_pool, n_rep)
        p_lo = _ft_inverse(max(ci_lo, 0.0), n_rep)
        p_hi = _ft_inverse(min(ci_hi, math.pi), n_rep)
        return {
            "rate": round(p_pool * 100.0, 2),
            "ci_lower": round(p_lo * 100.0, 2),
            "ci_upper": round(p_hi * 100.0, 2),
            "model": model_name,
            "tau2": round(tau2, 8),
            "tau2_se": None,
            "Q": round(Q, 6),
            "Q_p": round(Q_p, 6),
            "I2": round(I2, 2),
            "k": k,
            "se": round(se, 6),
            "z": z,
            "n_rep": round(n_rep, 1),
        }
    
    if use_random:
        pooled = _pool_result(t_re, ci_lo_re, ci_hi_re, se_re, "random")
        # 同时返回固定效应供参考
        pooled_fe = _pool_result(t_fe, ci_lo_fe, ci_hi_fe, se_fe, "fixed")
    else:
        pooled = _pool_result(t_fe, ci_lo_fe, ci_hi_fe, se_fe, "fixed")
        pooled_fe = None
    
    # ── per_study 输出 ──────────────────────────────────────
    primary_pct = "pct_re" if use_random else "pct_fe"
    per_study = [
        {
            "label": s["label"],
            "x": int(round(s["x"])),
            "n": int(round(s["n"])),
            "p": round(s["x"] / s["n"] if s["n"] > 0 else 0.0, 6),
            "weight": round(s[primary_pct], 2),          # 主模型权重(%)
            "transformed": round(s["t"], 6),              # FT 变换值 t
            "t": round(s["t"], 6),
            "se": round(s["se"], 6),
            "weight_fe": round(s["pct_fe"], 2),
            "weight_re": round(s["pct_re"], 2),
            "sqrt_n": round(s["sqrt_n"], 2),
        }
        for s in parsed
    ]
    
    # ── 漏斗图 + Egger ─────────────────────────────────────
    funnel = [{"t": s["t"], "sqrt_n": s["sqrt_n"]} for s in parsed] if k >= 10 else None
    egger = _egger_test(parsed) if k >= 10 else None
    
    notes = []
    if use_random:
        notes.append(
            f"异质性检验 Q={Q:.2f}, p={Q_p:.4f}, I²={I2:.1f}% → 选用随机效应模型"
        )
    else:
        notes.append(
            f"异质性检验 Q={Q:.2f}, p={Q_p:.4f}, I²={I2:.1f}% → 选用固定效应模型"
        )
    if k >= 10:
        notes.append(f"漏斗图可用（k={k}≥10），附带 Egger 检验")
    if tau2 > 0:
        notes.append(f"DerSimonian-Laird τ²={tau2:.6f}")
    
    resp = {
        "per_study": per_study,
        "pooled": pooled,
        "funnel": funnel,
        "egger": egger,
        "primary_model": primary_model,
        "notes": notes,
    }
    
    if pooled_fe is not None:
        resp["pooled_fixed"] = pooled_fe
    
    return resp


# ============================================================
# 8. 催化模型族 MLE 拟合与模型比较（M1 constant / M2 seroreversion / M3 two_phase）
# ============================================================

# M3 分段点 c 的剖面扫描集合（岁）
_CATALYTIC_C_POINTS = (2, 3, 5, 8, 12, 18, 25, 35)

# 模型展示名
_CATALYTIC_MODEL_NAMES = {
    "M1_constant": "恒定感染率（constant）",
    "M2_seroreversion": "血清转阴校正（seroreversion）",
    "M3_two_phase": "疫苗时代两阶段（two-phase）",
}


def _catalytic_p_m1(a: np.ndarray, lam: float) -> np.ndarray:
    """M1 constant：P(a) = 1 − exp(−λa)。"""
    return 1.0 - np.exp(-lam * np.maximum(a, 0.0))


def _catalytic_p_m2(a: np.ndarray, lam: float, mu: float) -> np.ndarray:
    """M2 seroreversion：P(a) = λ/(λ+μ)·(1 − exp(−(λ+μ)a))。

    渐近阳性率 λ/(λ+μ) < 1，刻画血清转阴（抗体衰减）。
    """
    s = lam + mu
    if s <= 1e-12:
        return _catalytic_p_m1(a, 1e-9)
    return (lam / s) * (1.0 - np.exp(-s * np.maximum(a, 0.0)))


def _catalytic_p_m3(a: np.ndarray, lam1: float, lam2: float, c: float) -> np.ndarray:
    """M3 two_phase：P(a) = 1 − exp(−(λ1·min(a,c) + λ2·max(0,a−c)))。"""
    z = lam1 * np.minimum(a, c) + lam2 * np.maximum(0.0, a - c)
    return 1.0 - np.exp(-z)


def _catalytic_nll(y: np.ndarray, n: np.ndarray, p: np.ndarray) -> float:
    """二项负对数似然（数值安全钳制 p ∈ [1e-6, 1-1e-6]）。"""
    p = np.clip(p, 1e-6, 1.0 - 1e-6)
    return -float(np.sum(n * (y * np.log(p) + (1.0 - y) * np.log(1.0 - p))))


def _catalytic_grad_m2(a: float, lam: float, mu: float) -> np.ndarray:
    """M2 在给定年龄处的 p 对 (λ, μ) 梯度向量。

    s = λ+μ，r = λ/s：
      ∂p/∂λ = (μ/s²)·(1−e^{−sa}) + r·a·e^{−sa}
      ∂p/∂μ = −(λ/s²)·(1−e^{−sa}) + r·a·e^{−sa}
    """
    s = lam + mu
    if s <= 1e-12:
        return np.array([0.0, 0.0])
    e = np.exp(-s * a)
    r = lam / s
    dlam = (mu / s ** 2) * (1.0 - e) + r * a * e
    dmu = -(lam / s ** 2) * (1.0 - e) + r * a * e
    return np.array([dlam, dmu])


def _catalytic_fisher(ages, ns, p_model, grad_func) -> Optional[np.ndarray]:
    """期望 Fisher 信息矩阵 I = Σ nᵢ/(pᵢ(1−pᵢ))·gᵢgᵢᵀ。

    - ``p_model(a)``：返回 p(a)。
    - ``grad_func(a)``：返回 ∂p/∂θ 梯度向量。
    非正定 / 数值异常 → 返回 None（奇异退化）。
    """
    dim = len(grad_func(float(ages[0])))
    I = np.zeros((dim, dim))
    for a, n in zip(ages, ns):
        p = float(np.clip(p_model(a), 1e-6, 1.0 - 1e-6))
        g = np.asarray(grad_func(a), dtype=float)
        I += (n / (p * (1.0 - p))) * np.outer(g, g)
    if not np.all(np.isfinite(I)):
        return None
    try:
        np.linalg.cholesky(I)  # 要求正定
    except np.linalg.LinAlgError:
        return None
    return I


def _catalytic_ci(theta: np.ndarray, I: Optional[np.ndarray], alpha: float,
                  lower_clamp: float = 0.0) -> Optional[dict]:
    """由 Fisher 信息逆求参数 95%CI。

    - ``I`` 为 None（奇异）→ 返回 None（退化）。
    - 各参数 SE = √(diag(I⁻¹))；CI 下界 clamp 到 ``lower_clamp``（参数非负约束）。
    返回 {<pname>: {"estimate", "ci_lower", "ci_upper"}} 结构由调用方拼接。
    """
    if I is None:
        return None
    try:
        cov = np.linalg.inv(I)
    except np.linalg.LinAlgError:
        return None
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    z = sps.norm.ppf(1.0 - alpha / 2.0)
    out = {}
    for i, (th, s) in enumerate(zip(theta, se)):
        lo = th - z * s
        hi = th + z * s
        if not (np.isfinite(lo) and np.isfinite(hi)):
            return None
        out[f"p{i}"] = {
            "estimate": float(th),
            "ci_lower": float(max(lo, lower_clamp)),
            "ci_upper": float(max(hi, lower_clamp)),
        }
    return out


def _catalytic_fit_m1(ages, y, n) -> dict:
    """M1 constant：P(a) = 1 − exp(−λa)，λ ≥ 0。"""
    def pfun(lam):
        return _catalytic_p_m1(ages, lam)

    overall = float(np.sum(n * y) / max(np.sum(n), 1.0))
    mean_age = float(np.mean(ages))
    lam0 = -math.log(max(1.0 - overall, 1e-6)) / max(mean_age, 1.0)
    starts = [max(lam0, 1e-6), max(lam0 * 0.5, 1e-6), max(lam0 * 2.0, 1e-6),
              0.05, 0.2]

    def nll_of(lam):
        # scipy 传入 1 元素数组，需先转为标量（兼容 numpy 2.x）
        lam_s = float(np.asarray(lam).reshape(-1)[0])
        return _catalytic_nll(y, n, pfun(lam_s))

    best: Optional[dict] = None
    for x0 in starts:
        res = minimize(nll_of, x0=[x0], method="L-BFGS-B",
                       bounds=[(1e-9, None)], options={"maxiter": 500})
        if not res.success or not np.all(np.isfinite(res.x)):
            continue
        if best is None or res.fun < best["nll"]:
            lam = float(res.x[0])
            best = {
                "nll": res.fun,
                "theta": np.array([lam]),
                "names": ["lambda"],
            }
    if best is None:
        return {"converged": False, "nll": None, "theta": None, "names": ["lambda"]}

    lam = best["theta"][0]
    ll = -best["nll"]

    def grad(a):
        p = float(_catalytic_p_m1(a, lam))
        return np.array([a * (1.0 - p)])

    I = _catalytic_fisher(ages, n, lambda a: _catalytic_p_m1(a, lam), grad)
    ci = _catalytic_ci(best["theta"], I, alpha=0.05)
    params = {
        "lambda": round(lam, 6),
        "lambda_ci_lower": round(ci["p0"]["ci_lower"], 6) if ci else None,
        "lambda_ci_upper": round(ci["p0"]["ci_upper"], 6) if ci else None,
    }
    return {"converged": True, "nll": best["nll"], "ll": ll, "params": params,
            "theta": best["theta"], "names": best["names"], "ci_ok": ci is not None}


def _catalytic_fit_m2(ages, y, n, m1_fit: dict) -> dict:
    """M2 seroreversion：P(a) = λ/(λ+μ)·(1 − exp(−(λ+μ)a))，λ,μ ≥ 0。

    初值 (M1λ, 0.01)；多个起点防局部极小。
    """
    lam1 = m1_fit["theta"][0] if m1_fit["converged"] and m1_fit["theta"] is not None else 0.05
    starts = [
        [lam1, 0.01],
        [max(lam1 * 1.5, 1e-6), 0.001],
        [max(lam1 * 0.7, 1e-6), 0.05],
        [0.05, 0.02],
    ]

    def nll_of(x):
        lam, mu = float(x[0]), float(x[1])
        return _catalytic_nll(y, n, _catalytic_p_m2(ages, lam, mu))

    best: Optional[dict] = None
    for x0 in starts:
        res = minimize(nll_of, x0=x0, method="L-BFGS-B",
                       bounds=[(1e-9, None), (1e-9, None)],
                       options={"maxiter": 500})
        if not res.success or not np.all(np.isfinite(res.x)):
            continue
        if best is None or res.fun < best["nll"]:
            best = {"nll": res.fun, "theta": np.asarray(res.x, dtype=float),
                    "names": ["lambda", "mu"]}
    if best is None:
        return {"converged": False, "nll": None, "theta": None, "names": ["lambda", "mu"]}

    lam, mu = float(best["theta"][0]), float(best["theta"][1])
    ll = -best["nll"]

    def grad(a):
        return _catalytic_grad_m2(a, lam, mu)

    I = _catalytic_fisher(ages, n, lambda a: _catalytic_p_m2(a, lam, mu), grad)
    ci = _catalytic_ci(best["theta"], I, alpha=0.05)
    params = {
        "lambda": round(lam, 6),
        "lambda_ci_lower": round(ci["p0"]["ci_lower"], 6) if ci else None,
        "lambda_ci_upper": round(ci["p0"]["ci_upper"], 6) if ci else None,
        "mu": round(mu, 6),
        "mu_ci_lower": round(ci["p1"]["ci_lower"], 6) if ci else None,
        "mu_ci_upper": round(ci["p1"]["ci_upper"], 6) if ci else None,
    }
    return {"converged": True, "nll": best["nll"], "ll": ll, "params": params,
            "theta": best["theta"], "names": best["names"], "ci_ok": ci is not None}


def _catalytic_fit_m2_fixed(ages, y, n, mu: float, m1_fit: dict) -> dict:
    """M2 seroreversion 固定 μ：P(a) = λ/(λ+μ)·(1 − exp(−(λ+μ)a))，仅 λ 自由。

    用于假设面板「血清转阴率」参数：μ 由用户指定（0.01/0.02 等），只估 λ。
    """
    mu = float(mu)
    lam1 = m1_fit["theta"][0] if m1_fit["converged"] and m1_fit["theta"] is not None else 0.05
    starts = [
        [max(lam1, 1e-6)],
        [max(lam1 * 1.5, 1e-6)],
        [max(lam1 * 0.7, 1e-6)],
        [0.05],
    ]

    def nll_of(x):
        lam = float(x[0])
        return _catalytic_nll(y, n, _catalytic_p_m2(ages, lam, mu))

    best: Optional[dict] = None
    for x0 in starts:
        res = minimize(nll_of, x0=x0, method="L-BFGS-B",
                       bounds=[(1e-9, None)],
                       options={"maxiter": 500})
        if not res.success or not np.all(np.isfinite(res.x)):
            continue
        if best is None or res.fun < best["nll"]:
            best = {"nll": res.fun, "theta": np.asarray(res.x, dtype=float),
                    "names": ["lambda"]}
    if best is None:
        return {"converged": False, "nll": None, "theta": None, "names": ["lambda"]}

    lam = float(best["theta"][0])
    ll = -best["nll"]

    def grad(a):
        return _catalytic_grad_m2(a, lam, mu)

    I = _catalytic_fisher(ages, n, lambda a: _catalytic_p_m2(a, lam, mu), grad)
    ci = _catalytic_ci(best["theta"], I, alpha=0.05)
    params = {
        "lambda": round(lam, 6),
        "lambda_ci_lower": round(ci["p0"]["ci_lower"], 6) if ci else None,
        "lambda_ci_upper": round(ci["p0"]["ci_upper"], 6) if ci else None,
        "mu": round(mu, 6),
        "mu_ci_lower": None,  # μ 为用户指定，非估计值
        "mu_ci_upper": None,
        "mu_fixed": True,
    }
    return {"converged": True, "nll": best["nll"], "ll": ll, "params": params,
            "theta": best["theta"], "names": best["names"], "ci_ok": ci is not None}


def _catalytic_fit_m3(ages, y, n, m1_fit: dict) -> dict:
    """M3 two_phase：分段 FOI（疫苗时代），c 在预设集合剖面扫描取最优。

    P(a) = 1 − exp(−(λ1·min(a,c) + λ2·max(0,a−c)))，λ1,λ2 ≥ 0。
    c 为超参数（无 CI），λ1/λ2 为待估参数。
    """
    lam1 = m1_fit["theta"][0] if m1_fit["converged"] and m1_fit["theta"] is not None else 0.05
    best_overall: Optional[dict] = None
    for c in _CATALYTIC_C_POINTS:
        starts = [
            [lam1, max(lam1 * 0.5, 1e-6)],
            [max(lam1 * 0.6, 1e-6), max(lam1 * 1.2, 1e-6)],
            [0.05, 0.05],
        ]

        def nll_of(x):
            l1, l2 = float(x[0]), float(x[1])
            return _catalytic_nll(y, n, _catalytic_p_m3(ages, l1, l2, c))

        for x0 in starts:
            res = minimize(nll_of, x0=x0, method="L-BFGS-B",
                           bounds=[(1e-9, None), (1e-9, None)],
                           options={"maxiter": 500})
            if not res.success or not np.all(np.isfinite(res.x)):
                continue
            if best_overall is None or res.fun < best_overall["nll"]:
                best_overall = {"nll": res.fun, "theta": np.asarray(res.x, dtype=float),
                                "c": c, "names": ["lambda1", "lambda2"]}
    if best_overall is None:
        return {"converged": False, "nll": None, "theta": None, "names": ["lambda1", "lambda2"]}

    l1, l2 = float(best_overall["theta"][0]), float(best_overall["theta"][1])
    c = float(best_overall["c"])
    ll = -best_overall["nll"]

    def grad(a):
        p = float(_catalytic_p_m3(a, l1, l2, c))
        a1 = float(np.minimum(a, c))
        a2 = float(np.maximum(0.0, a - c))
        return np.array([a1 * (1.0 - p), a2 * (1.0 - p)])

    I = _catalytic_fisher(ages, n, lambda a: _catalytic_p_m3(a, l1, l2, c), grad)
    ci = _catalytic_ci(best_overall["theta"], I, alpha=0.05)
    params = {
        "lambda1": round(l1, 6),
        "lambda1_ci_lower": round(ci["p0"]["ci_lower"], 6) if ci else None,
        "lambda1_ci_upper": round(ci["p0"]["ci_upper"], 6) if ci else None,
        "lambda2": round(l2, 6),
        "lambda2_ci_lower": round(ci["p1"]["ci_lower"], 6) if ci else None,
        "lambda2_ci_upper": round(ci["p1"]["ci_upper"], 6) if ci else None,
        "change_point": int(c),
    }
    return {"converged": True, "nll": best_overall["nll"], "ll": ll, "params": params,
            "theta": best_overall["theta"], "names": best_overall["names"], "ci_ok": ci is not None}


def _catalytic_predict(name: str, params: dict, ages: np.ndarray) -> np.ndarray:
    """按模型名与参数预测阳性率 P(a)。"""
    if name == "M1_constant":
        return _catalytic_p_m1(ages, params["lambda"])
    if name == "M2_seroreversion":
        return _catalytic_p_m2(ages, params["lambda"], params["mu"])
    if name == "M3_two_phase":
        return _catalytic_p_m3(ages, params["lambda1"], params["lambda2"], float(params["change_point"]))
    raise ValueError(f"未知催化模型: {name}")


def _catalytic_avg_foi(name: str, params: dict, max_age: float) -> float:
    """推荐模型在 [0, max_age] 上的平均 FOI（/年），用于回填旧字段 foi_avg。

    - M1：λ（恒定）
    - M2：λ（每易感者感染率）
    - M3：H(T)/T = (λ1·min(T,c) + λ2·max(0,T−c))/T
    """
    if name == "M1_constant":
        return float(params["lambda"])
    if name == "M2_seroreversion":
        return float(params["lambda"])
    if name == "M3_two_phase":
        c = float(params["change_point"])
        T = max(max_age, 1.0)
        return (params["lambda1"] * min(T, c) + params["lambda2"] * max(0.0, T - c)) / T
    raise ValueError(f"未知催化模型: {name}")


def _fit_catalytic_fixed_mu(ages, y, n, m1, mu: float, n_records: int,
                            a_min: float, a_max: float) -> dict:
    """按用户指定血清转阴率 μ 拟合 M2（仅估 λ），返回与 fit_catalytic_models 同构的结果。

    用于免疫屏障/FOI 假设面板的「血清转阴率」参数：μ>0 时只估 λ，
    ``recommended_model`` 固定为 M2_seroreversion，FOI 均值取 λ。
    """
    if m1 is None:
        m1 = _catalytic_fit_m1(ages, y, n)
    m2f = _catalytic_fit_m2_fixed(ages, y, n, mu, m1)

    models_out: list[dict] = []
    if m2f["converged"] and m2f["nll"] is not None:
        ll = -m2f["nll"]
        # μ 固定：仅 λ 一个自由参数
        k = 1
        aic = 2.0 * k - 2.0 * ll
        bic = k * math.log(max(n_records, 2.0)) - 2.0 * ll
        models_out.append({
            "name": "M2_seroreversion",
            "label": _CATALYTIC_MODEL_NAMES["M2_seroreversion"],
            "k_params": k,
            "params": m2f["params"],
            "loglik": round(ll, 6),
            "aic": round(aic, 3),
            "bic": round(bic, 3),
            "delta_aic": 0.0,
            "akaike_weight": 1.0,
            "converged": True,
        })

    if not models_out:
        return {
            "models": [], "recommended_model": None, "recommended_params": None,
            "recommended_foi_avg": None, "fitted_curve": [],
            "comparison": {"sorted_by_aic": [], "lrt": None},
            "modeling_notes": [f"M2（血清转阴率固定 μ={mu}/年）拟合失败"],
            "n_records": n_records, "age_range": [a_min, a_max],
        }

    recommended = "M2_seroreversion"
    rec_params = models_out[0]["params"]
    recommended_foi_avg = round(_catalytic_avg_foi("M2_seroreversion", rec_params, a_max), 6)

    fitted_curve: list[dict] = []
    start = math.ceil(a_min)
    grid = np.arange(start, a_max + 1e-9, 1.0)
    p_vals = np.clip(_catalytic_predict("M2_seroreversion", rec_params, grid), 0.0, 1.0)
    fitted_curve = [
        {"age": round(float(ag), 1), "prevalence": round(float(pv) * 100.0, 2)}
        for ag, pv in zip(grid, p_vals)
    ]

    modeling_notes = [
        f"按用户指定血清转阴率 μ={mu}/年 拟合 M2 催化模型（仅估 λ），λ={rec_params.get('lambda')}"
    ]
    if len(y) < 8:
        modeling_notes.append(f"仅 {n_records} 个有效年龄点，模型拟合置信度有限（建议 ≥8 个）")

    return {
        "models": models_out,
        "recommended_model": recommended,
        "recommended_params": rec_params,
        "recommended_foi_avg": recommended_foi_avg,
        "fitted_curve": fitted_curve,
        "comparison": {"sorted_by_aic": [m["name"] for m in models_out], "lrt": None},
        "modeling_notes": modeling_notes,
        "n_records": n_records,
        "age_range": [a_min, a_max],
    }


def fit_catalytic_models(records: Sequence[Tuple[Any, Any, Any]], alpha: float = 0.05,
                         mu_fixed: Optional[float] = None) -> dict:
    """催化模型族 MLE 拟合与模型比较（M1 / M2 / M3）。

    输入 ``records``：[(age_mid, x, n), ...]，age_mid 须 > 0，n > 0；非法记录剔除。

    三个模型均为二项负对数似然 + L-BFGS-B 求解：
    - M1 constant：P(a) = 1 − exp(−λa)，λ ≥ 0。
    - M2 seroreversion：P(a) = λ/(λ+μ)·(1 − exp(−(λ+μ)a))，λ,μ ≥ 0，初值 (M1λ, 0.01)。
    - M3 two_phase：分段 FOI，P(a) = 1 − exp(−(λ1·min(a,c) + λ2·max(0,a−c)))，
      c ∈ {2,3,5,8,12,18,25,35} 剖面扫描取最优。

    每个模型：参数 MLE + 95%CI（期望 Fisher 信息逆；奇异退化 None）、logLik、AIC=2k−2ll、BIC。
    模型比较：按 AIC 升序排序，给出 ΔAIC 与 Akaike 权重 w=exp(−Δ/2)/Σ；
    相邻嵌套模型做 LRT（M1 vs M2，df=1）。

    返回 dict（无副作用）：
    - ``models``:  [{name, label, k_params, params, loglik, aic, bic, delta_aic,
      akaike_weight, converged}]（按 AIC 升序）
    - ``recommended_model``: 推荐模型名（AIC 最小）
    - ``recommended_params``: 推荐模型参数字典
    - ``recommended_foi_avg``: 推荐模型平均 FOI（/年）
    - ``fitted_curve``: [{age, prevalence}]——推荐模型 P(a) 曲线（1 岁步长，百分数）
    - ``comparison``: {sorted_by_aic, lrt:{pair,chisq,df,p_value} | None}
    - ``modeling_notes``: [str] 中文说明
    - ``n_records`` / ``age_range``
    """
    # ── 数据清洗 ───────────────────────────────────────────
    parsed: list[Tuple[float, float, float]] = []
    for r in records:
        try:
            a = float(r[0])
            x = float(r[1])
            n = float(r[2])
        except (TypeError, ValueError):
            continue
        if a <= 0 or n <= 0:
            continue
        x = max(0.0, min(x, n))
        parsed.append((a, x, n))
    if not parsed:
        return {
            "models": [], "recommended_model": None, "recommended_params": None,
            "recommended_foi_avg": None, "fitted_curve": [],
            "comparison": {"sorted_by_aic": [], "lrt": None},
            "modeling_notes": ["无有效记录（需要 age>0 且 n>0 的 (age_mid, x, n)），无法拟合催化模型"],
            "n_records": 0, "age_range": [None, None],
        }

    ages = np.array([p[0] for p in parsed], dtype=float)
    xs = np.array([p[1] for p in parsed], dtype=float)
    ns = np.array([p[2] for p in parsed], dtype=float)
    y = np.clip(xs / ns, 1e-4, 1.0 - 1e-4)
    n_records = len(parsed)
    a_min, a_max = float(ages.min()), float(ages.max())

    # ── 显式血清转阴率假设：仅拟合 M2（μ 固定）────────────────
    if mu_fixed is not None and mu_fixed > 0:
        return _fit_catalytic_fixed_mu(ages, y, ns, m1=None, mu=mu_fixed,
                                       n_records=n_records, a_min=a_min, a_max=a_max)

    # ── 三个模型拟合 ───────────────────────────────────────
    m1 = _catalytic_fit_m1(ages, y, ns)
    m2 = _catalytic_fit_m2(ages, y, ns, m1)
    m3 = _catalytic_fit_m3(ages, y, ns, m1)

    models_fit = [
        ("M1_constant", 1, m1),
        ("M2_seroreversion", 2, m2),
        ("M3_two_phase", 3, m3),
    ]

    models_out: list[dict] = []
    for name, k, fit in models_fit:
        if not fit["converged"] or fit["nll"] is None:
            models_out.append({
                "name": name,
                "label": _CATALYTIC_MODEL_NAMES[name],
                "k_params": k,
                "params": {p: None for p in fit["names"]},
                "loglik": None, "aic": None, "bic": None,
                "delta_aic": None, "akaike_weight": None,
                "converged": False,
            })
            continue
        ll = -fit["nll"]
        aic = 2.0 * k - 2.0 * ll
        bic = k * math.log(max(n_records, 2.0)) - 2.0 * ll
        models_out.append({
            "name": name,
            "label": _CATALYTIC_MODEL_NAMES[name],
            "k_params": k,
            "params": fit["params"],
            "loglik": round(ll, 6),
            "aic": round(aic, 3),
            "bic": round(bic, 3),
            "delta_aic": None,
            "akaike_weight": None,
            "converged": True,
        })

    converged = [m for m in models_out if m["converged"]]

    # ── 模型比较：按 AIC 升序 + ΔAIC + Akaike 权重 ───────
    models_out.sort(key=lambda m: (m["aic"] if m["aic"] is not None else float("inf")))
    # 排序后重新计算 converged（AIC 最小的为推荐）
    converged_sorted = [m for m in models_out if m["converged"]]
    if converged_sorted:
        min_aic = min(m["aic"] for m in converged_sorted)
        for m in models_out:
            if m["aic"] is not None:
                m["delta_aic"] = round(m["aic"] - min_aic, 3)
            else:
                m["delta_aic"] = None
        deltas = np.array([(m["delta_aic"] if m["delta_aic"] is not None else float("inf"))
                           for m in models_out], dtype=float)
        exp_neg = np.exp(-deltas / 2.0)
        w_sum = float(np.sum(exp_neg[np.isfinite(exp_neg)]))
        for m, d in zip(models_out, deltas):
            if np.isfinite(d) and w_sum > 0:
                m["akaike_weight"] = round(float(np.exp(-d / 2.0)) / w_sum, 6)
            else:
                m["akaike_weight"] = None

    recommended = converged_sorted[0]["name"] if converged_sorted else None
    recommended_block = next((m for m in models_out if m["name"] == recommended), None) if recommended else None

    # ── 相邻嵌套模型 LRT（M1 vs M2，df=1）────────────────
    lrt = None
    if m1["converged"] and m2["converged"] and m1["nll"] is not None and m2["nll"] is not None:
        chisq = 2.0 * (m2["ll"] - m1["ll"])  # M2 ⊇ M1，故 ≥ 0
        chisq = max(chisq, 0.0)
        p_value = float(sps.chi2.sf(chisq, df=1))
        lrt = {
            "pair": "M1_vs_M2",
            "chisq": round(chisq, 4),
            "df": 1,
            "p_value": round(p_value, 6),
        }

    # ── 推荐模型拟合曲线 + 平均 FOI ─────────────────────
    fitted_curve: list[dict] = []
    recommended_foi_avg = None
    if recommended_block and recommended_block["params"]:
        rec_params = recommended_block["params"]
        rec_name = recommended_block["name"]
        recommended_foi_avg = round(_catalytic_avg_foi(rec_name, rec_params, a_max), 6)
        start = math.ceil(a_min)
        grid = np.arange(start, a_max + 1e-9, 1.0)
        p_vals = np.clip(_catalytic_predict(rec_name, rec_params, grid), 0.0, 1.0)
        fitted_curve = [
            {"age": round(float(ag), 1), "prevalence": round(float(pv) * 100.0, 2)}
            for ag, pv in zip(grid, p_vals)
        ]

    # ── 说明文案 ─────────────────────────────────────────
    modeling_notes: list[str] = []
    if recommended:
        modeling_notes.append(
            f"按 AIC 选出推荐模型 {recommended}（{_CATALYTIC_MODEL_NAMES[recommended]}，"
            f"ΔAIC=0.000，Akaike 权重={recommended_block['akaike_weight']}）"
        )
    if m2["converged"] and m2["nll"] is not None and m1["converged"] and m1["nll"] is not None:
        if m2["ll"] - m1["ll"] > 1.92:  # LRT p<0.05 的 χ² 阈值(1 df)≈3.84，2ll 差阈值≈3.84/2
            modeling_notes.append(
                "M2（seroreversion）显著优于 M1（constant），提示存在血清转阴/抗体衰减"
            )
    if m3["converged"] and m3["nll"] is not None and m1["converged"] and m1["nll"] is not None:
        if m3["ll"] - m1["ll"] > 1.92:
            modeling_notes.append(
                "M3（two-phase）显著优于 M1（constant），提示存在随年龄变化的感染率结构（如疫苗时代）"
            )
    if len(parsed) < 8:
        modeling_notes.append(f"仅 {len(parsed)} 个有效年龄点，模型比较置信度有限（建议 ≥8 个）")
    if recommended == "M1_constant":
        modeling_notes.append(
            "R0=λ·L 仅对恒定 FOI 模型（M1）且疾病满足「地方性 + 终生免疫」时适用；"
            "对新冠/流感/手足口/轮状病毒/百日咳等非终生免疫疾病不适用"
        )

    return {
        "models": models_out,
        "recommended_model": recommended,
        "recommended_params": recommended_block["params"] if recommended_block else None,
        "recommended_foi_avg": recommended_foi_avg,
        "fitted_curve": fitted_curve,
        "comparison": {"sorted_by_aic": [m["name"] for m in models_out], "lrt": lrt},
        "modeling_notes": modeling_notes,
        "n_records": n_records,
        "age_range": [a_min, a_max],
    }


# ============================================================
# 统计检验与标准化率
# ============================================================

def cochran_armitage_trend(groups: Sequence[Any]) -> Optional[dict]:
    """Cochran-Armitage 趋势检验（用于有序分组，如逐年阳性率）。

    ``groups``：[(score, x, n), ...]，score 为有序分值（如年份），x 为阳性数，n 为总数。
    Z = Σsᵢ(xᵢ−nᵢ·p̄) / √(p̄·(1−p̄)·Σnᵢ(sᵢ−s̄)²)，p̄ = Σxᵢ/Σnᵢ，s̄ 为样本量加权分值均值。
    双侧 p = 2·norm.sf(|Z|)。

    返回 ``{z, p_value, direction, direction_label}``：
    - direction: 'increasing' | 'decreasing' | 'flat'（由 Z 符号决定）；
    - direction_label: '上升' / '下降' / '不显著'（结合 p 值判断）。
    有效分组 < 3 时返回 None。
    """
    parsed: list[tuple[float, float, float]] = []
    for g in groups:
        try:
            s = float(g[0])
            x = float(g[1])
            n = float(g[2])
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        x = max(0.0, min(x, n))
        parsed.append((s, x, n))
    if len(parsed) < 3:
        return None

    total_x = sum(x for _, x, _ in parsed)
    total_n = sum(n for _, _, n in parsed)
    if total_n <= 0 or total_x <= 0 or total_x >= total_n:
        # 全 0 或全阳性时 p̄ 退化，无检验意义
        return None
    p_bar = total_x / total_n

    s_bar = sum(s * n for s, _, n in parsed) / total_n
    numerator = sum(s * (x - n * p_bar) for s, x, n in parsed)
    denom_sq = p_bar * (1.0 - p_bar) * sum(n * (s - s_bar) ** 2 for s, _, n in parsed)
    if denom_sq <= 0:
        return None
    z = numerator / math.sqrt(denom_sq)
    p_value = 2.0 * sps.norm.sf(abs(z))

    if z > 0 and p_value < 0.05:
        direction = "increasing"
        direction_label = "上升"
    elif z < 0 and p_value < 0.05:
        direction = "decreasing"
        direction_label = "下降"
    else:
        direction = "flat"
        direction_label = "不显著"

    return {
        "z": round(z, 6),
        "p_value": round(p_value, 6),
        "direction": direction,
        "direction_label": direction_label,
    }


def two_proportion_test(
    x1: Any, n1: Any, x2: Any, n2: Any, alpha: float = 0.05
) -> dict:
    """两样本率比较：z 检验 + 率差(RD) 与率比(RR) 及 95%CI。

    - z 检验：z = (p1−p2)/√(p̂·(1−p̂)·(1/n1+1/n2))，p̂ 为合并率；双侧 p。
    - RD = p1−p2，95%CI：RD ± z·√(p1(1−p1)/n1 + p2(1−p2)/n2)。
    - RR = p1/p2，95%CI 用 log 法：exp(ln RR ± z·√(1/x1−1/n1+1/x2−1/n2))。
    - 任一分母 n≤0 或出现 0 格时做 0.5 校正（Haldane-Anscombe）。
    返回 ``{p1, p2, rd, rd_ci_lower, rd_ci_upper, rr, rr_ci_lower, rr_ci_upper,
    z, p_value, significant, conclusion}``（conclusion 为中文结论文案）。
    """
    try:
        x1 = float(x1); n1 = float(n1); x2 = float(x2); n2 = float(n2)
    except (TypeError, ValueError):
        return {"error": "输入无效"}

    def _correct(x: float, n: float) -> tuple[float, float]:
        if n <= 0:
            return (0.5, 1.0)
        if x == 0 or x == n:
            # 0 格（或全阳性）加 0.5 校正
            return (x + 0.5, n + 1.0)
        return (x, n)

    x1c, n1c = _correct(x1, n1)
    x2c, n2c = _correct(x2, n2)
    p1 = x1c / n1c
    p2 = x2c / n2c

    p_hat = (x1c + x2c) / (n1c + n2c)
    se_diff = math.sqrt(p_hat * (1.0 - p_hat) * (1.0 / n1c + 1.0 / n2c))
    z = (p1 - p2) / se_diff if se_diff > 0 else 0.0
    p_value = 2.0 * sps.norm.sf(abs(z))

    z_crit = sps.norm.ppf(1.0 - alpha / 2.0)
    rd = p1 - p2
    se_rd = math.sqrt(p1 * (1.0 - p1) / n1c + p2 * (1.0 - p2) / n2c)
    rd_lo = rd - z_crit * se_rd
    rd_hi = rd + z_crit * se_rd

    rr = (p1 / p2) if p2 > 0 else None
    rr_lo = rr_hi = None
    if rr is not None and p1 > 0 and p2 > 0:
        se_ln_rr = math.sqrt(1.0 / x1c - 1.0 / n1c + 1.0 / x2c - 1.0 / n2c)
        ln_rr = math.log(rr)
        rr_lo = math.exp(ln_rr - z_crit * se_ln_rr)
        rr_hi = math.exp(ln_rr + z_crit * se_ln_rr)

    significant = bool(p_value < alpha)
    if p1 > p2:
        direction_cn = "高于"
    elif p1 < p2:
        direction_cn = "低于"
    else:
        direction_cn = "无差异"
    conclusion = (
        f"两组阳性率分别为 {p1*100:.1f}% 与 {p2*100:.1f}%"
        f"（n={n1:.0f} vs n={n2:.0f}），率差 RD={rd*100:+.1f}%"
        f"（95%CI {rd_lo*100:.1f}% ~ {rd_hi*100:.1f}%），"
        f"率比 RR={rr:.2f}" + (f"（95%CI {rr_lo:.2f} ~ {rr_hi:.2f}）" if rr_lo is not None else "（无法计算）")
        + f"，z={z:.3f}，p={p_value:.4f}，"
        + ("差异具有统计学意义" if significant else "差异无统计学意义")
        + f"，第一组阳性率{direction_cn}第二组"
    )

    return {
        "p1": round(p1, 6),
        "p2": round(p2, 6),
        "n1": n1,
        "n2": n2,
        "rd": round(rd, 6),
        "rd_ci_lower": round(rd_lo, 6),
        "rd_ci_upper": round(rd_hi, 6),
        "rr": round(rr, 6) if rr is not None else None,
        "rr_ci_lower": round(rr_lo, 6) if rr_lo is not None else None,
        "rr_ci_upper": round(rr_hi, 6) if rr_hi is not None else None,
        "z": round(z, 6),
        "p_value": round(p_value, 6),
        "significant": significant,
        "conclusion": conclusion,
    }


def direct_standardize(
    strata: Sequence[Any],
    standard: Optional[Sequence[Any]] = None,
    alpha: float = 0.05,
) -> dict:
    """直接法标准化率（年龄标准化阳性率 ASR）。

    - ``strata``：[(年龄组, rate, n)]，rate 为 0-1 比例（或百分数，内部统一），n 为样本量。
      年龄组字符串需与 standard 的 age_groups 中 group 一致（如 "0"、"1-4"、"85+"）。
    - ``standard``：标准人口构成，元素为 ``{"group": str, "weight": float, "range": [lo, hi]}``
      （如 reference_data/china_pop_2020.json 的 age_groups）；缺省自动读该文件。
    - 仅纳入 standard 中存在且 n>0 的分层；不足 3 组时返回 asr=None（并注明原因）。
    - ASR = Σ(std_wᵢ·rᵢ)；SE = √Σ(std_wᵢ²·rᵢ(1−rᵢ)/nᵢ)。
    返回 ``{crude, asr, asr_ci_lower, asr_ci_upper, se, n_strata, used_groups,
    standard_version, note}``（crude = 加权粗率）。
    """
    import json as _json
    import os as _os

    if standard is None:
        _p = _os.path.join(_os.path.dirname(__file__), "reference_data", "china_pop_2020.json")
        with open(_p, "r", encoding="utf-8") as _f:
            _data = _json.load(_f)
        standard = _data.get("age_groups", [])
        standard_version = _data.get("version", "unknown")
    else:
        standard_version = "provided"

    std_map: dict[str, float] = {}
    for s in standard:
        g = s.get("group") if isinstance(s, dict) else None
        w = s.get("weight") if isinstance(s, dict) else None
        if g is not None and w is not None:
            std_map[str(g)] = float(w)
    total_w = sum(std_map.values())
    if total_w <= 0:
        total_w = 1.0

    parsed: list[tuple[str, float, float]] = []
    for st in strata:
        try:
            g = str(st[0])
            rate = float(st[1])
            n = float(st[2])
        except (TypeError, ValueError, IndexError):
            continue
        if rate > 1.0:
            rate /= 100.0
        rate = min(max(rate, 0.0), 1.0)
        if g not in std_map or n <= 0:
            continue
        parsed.append((g, rate, n))
    if len(parsed) < 3:
        return {
            "crude": None, "asr": None, "asr_ci_lower": None, "asr_ci_upper": None,
            "se": None, "n_strata": len(parsed), "used_groups": [p[0] for p in parsed],
            "standard_version": standard_version,
            "note": "有效年龄分层不足 3 组，无法计算标准化率",
        }

    crude_num = sum(rate * n for _, rate, n in parsed)
    crude_den = sum(n for _, _, n in parsed)
    crude = crude_num / crude_den if crude_den > 0 else None

    asr_num = sum(std_map[g] / total_w * rate for g, rate, _ in parsed)
    se_sq = sum(
        (std_map[g] / total_w) ** 2 * rate * (1.0 - rate) / n
        for g, rate, n in parsed
    )
    se = math.sqrt(se_sq)
    z_crit = sps.norm.ppf(1.0 - alpha / 2.0)
    asr = asr_num
    return {
        "crude": round(crude * 100, 4) if crude is not None else None,
        "asr": round(asr * 100, 4),
        "asr_ci_lower": round((asr - z_crit * se) * 100, 4),
        "asr_ci_upper": round((asr + z_crit * se) * 100, 4),
        "se": round(se * 100, 4),
        "n_strata": len(parsed),
        "used_groups": [p[0] for p in parsed],
        "standard_version": standard_version,
        "note": None,
    }


# ============================================================
# 空间统计：Moran's I 全局自相关 + Getis-Ord Gi* 局部热点
# ============================================================

def morans_i(rates: Sequence[Any], w: Any, permutations: int = 999) -> Optional[dict]:
    """全局 Moran's I 空间自相关检验（esda.Moran，permutation 检验）。

    - ``rates``：与 ``w`` 观测顺序一致的率数组（省级加权阳性率，0-100 或 0-1 均可；
      线性单调变换不改变 I 与检验方向）。非法值被剔除。
    - ``w``：libpysal 权重对象（服务层已按有数据省份过滤、对称化并做行标准化）。
    - 有效观测 < 8 或与 w 观测数不一致 → 返回 None（由 service 层转 422 中文提示）。

    返回 ``{I, p_sim, z, conclusion}``：conclusion 为中文解读文案。
    """
    import esda

    vals: list[float] = []
    for r in rates:
        try:
            v = float(r)
        except (TypeError, ValueError):
            continue
        if math.isnan(v):
            continue
        vals.append(v)
    if len(vals) < 8 or len(vals) != w.n:
        return None

    mi = esda.Moran(vals, w, permutations=permutations)
    I = float(mi.I)
    p = float(mi.p_sim)
    z = float(mi.z_sim)

    if p < 0.05:
        if I > 0:
            direction = "正向显著聚集"
            interp = "高阳性率省份呈空间聚集"
        else:
            direction = "负向显著分散"
            interp = "高值与低值呈棋盘式相间分布"
    else:
        direction = "未检测到显著空间自相关"
        interp = "阳性率空间分布接近随机"
    conclusion = f"{direction}（I={I:.3f}, p={p:.3f}）：{interp}"

    return {
        "I": round(I, 6),
        "p_sim": round(p, 6),
        "z": round(z, 6),
        "conclusion": conclusion,
    }


def g_star(rates: Sequence[Any], w: Any, permutations: int = 999) -> Optional[list[dict]]:
    """Getis-Ord Gi* 局部空间关联（esda.G_Local，star=True，含焦点单元自身）。

    - ``rates``：与 ``w`` 观测顺序一致的率数组；非法值剔除。
    - ``w``：libpysal 权重对象（对称化 + 行标准化，与 morans_i 口径一致）。
    - 有效观测 < 8 或与 w 观测数不一致 → 返回 None。

    返回与输入顺序一致的每省 ``{gi_z, p}``（Gi* z 得分与置换 p 值）。
    """
    import esda

    vals: list[float] = []
    for r in rates:
        try:
            v = float(r)
        except (TypeError, ValueError):
            continue
        if math.isnan(v):
            continue
        vals.append(v)
    if len(vals) < 8 or len(vals) != w.n:
        return None

    g = esda.G_Local(vals, w, star=True, permutations=permutations)
    return [
        {"gi_z": round(float(zz), 6), "p": round(float(pp), 6)}
        for zz, pp in zip(g.Zs, g.p_sim)
    ]


def classify_hotspot_cluster(gi_z: Optional[Any]) -> str:
    """把 Gi* z 得分映射为热点/冷点分类标签。

    - z ≥ 2.576 → hot_99；≥ 1.96 → hot_95；≥ 1.645 → hot_90；
    - z ≤ -2.576 → cold_99；≤ -1.96 → cold_95；≤ -1.645 → cold_90；
    - 其余 → ns（不显著）；非法/缺失 → ns。
    """
    try:
        z = float(gi_z)
    except (TypeError, ValueError):
        return "ns"
    if z >= 2.576:
        return "hot_99"
    if z >= 1.96:
        return "hot_95"
    if z >= 1.645:
        return "hot_90"
    if z <= -2.576:
        return "cold_99"
    if z <= -1.96:
        return "cold_95"
    if z <= -1.645:
        return "cold_90"
    return "ns"


# ============================================================
# 出生队列（birth cohort）分析
# ============================================================

def birth_year_from_age(collection_year: Any, age_mid: Any) -> Optional[int]:
    """出生年份推算：birth_year = collection_year − age_mid。

    - collection_year / age_mid 任一缺失或非法（非数值、年龄为负、年份越界）→ None。
    - 返回整数（四舍五入）。
    """
    try:
        cy = float(collection_year)
    except (TypeError, ValueError):
        return None
    try:
        am = float(age_mid)
    except (TypeError, ValueError):
        return None
    if am < 0 or cy < 1900 or cy > 2200:
        return None
    return int(round(cy - am))


def decade_band(birth_year: Any) -> Optional[str]:
    """出生年份 → 十年段标签（1985 → "1980-1989"）；非法 → None。"""
    try:
        y = int(birth_year)
    except (TypeError, ValueError):
        return None
    if y < 1900 or y > 2200:
        return None
    start = (y // 10) * 10
    return f"{start}-{start + 9}"


def birth_cohort_analysis(
    records: Sequence[Any],
    min_cell_points: int = 2,
) -> dict:
    """出生队列分析的纯函数核心（无副作用）。

    ``records``: 每条为 ``(collection_year, age_mid, value, sample_size)``：
    - value: 血清阳性率（0-1 比例或 0-100 百分数均可，加权引擎内部归一）；
    - sample_size: 样本量（正整数）；collection_year / age_mid 用于推算出生年份。

    流程：
    1. birth_year = collection_year − age_mid；缺失/非法剔除并计数 ``dropped``；
    2. 出生年份按十年段分桶（decade_band）；
    3. 按 ``(十年段, collection_year)`` 聚合 cell → 复用 ``weighted_rate_ci``
       （样本量加权阳性率 + 95% CI）；
    4. 不足 ``min_cell_points`` 个点的 cell → rate/CI 置 None（heatmap 留空）。

    返回 ``{cohorts, matrix, x_years, y_bands, dropped, n_records}``：
    - cohorts: [{birth_year_band, series: [{year, rate, ci_lower, ci_upper, n}]}]
      （按十年段升序；rate/CI 为百分数 0-100，无数据 cell 为 None）
    - matrix: y_bands × x_years 的率矩阵（[[rate|null]]）
    - x_years / y_bands: 调查年 / 出生年代（升序）
    """
    cells: dict[tuple[str, int], list[tuple[float, int]]] = {}
    dropped = 0
    n_records = 0
    for rec in records:
        n_records += 1
        if len(rec) < 4:
            dropped += 1
            continue
        cy, am, value, n = rec[0], rec[1], rec[2], rec[3]
        by = birth_year_from_age(cy, am)
        if by is None:
            dropped += 1
            continue
        band = decade_band(by)
        if band is None:
            dropped += 1
            continue
        try:
            v = float(value)
            ss = int(n)
        except (TypeError, ValueError):
            dropped += 1
            continue
        if ss <= 0 or v < 0.0 or v > 100.0:
            dropped += 1
            continue
        try:
            year = int(cy)
        except (TypeError, ValueError):
            dropped += 1
            continue
        cells.setdefault((band, year), []).append((v, ss))

    x_years = sorted({cy for (_, cy) in cells.keys()})
    y_bands = sorted({band for (band, _) in cells.keys()})

    cohorts: list[dict] = []
    matrix: list[list[Optional[float]]] = []
    for band in y_bands:
        series: list[dict] = []
        row: list[Optional[float]] = []
        for year in x_years:
            cell = cells.get((band, year), [])
            if len(cell) < min_cell_points:
                series.append({
                    "year": year, "rate": None,
                    "ci_lower": None, "ci_upper": None, "n": 0,
                })
                row.append(None)
                continue
            merged = weighted_rate_ci([
                {"value": v, "sample_size": ss} for v, ss in cell
            ])
            rate = merged["weighted_positivity"]
            series.append({
                "year": year,
                "rate": rate,
                "ci_lower": merged["ci_lower"],
                "ci_upper": merged["ci_upper"],
                "n": merged["n_total"],
            })
            row.append(rate)
        cohorts.append({"birth_year_band": band, "series": series})
        matrix.append(row)

    return {
        "cohorts": cohorts,
        "matrix": matrix,
        "x_years": x_years,
        "y_bands": y_bands,
        "dropped": dropped,
        "n_records": n_records,
    }

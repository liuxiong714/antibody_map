"""统计工具模块：抗体数据常用的纯函数统计分析（仅依赖标准库，无需 numpy/scipy）。

提供以下函数：
- geometric_mean_with_ci: 几何均数（GMC）+ 对数域 t 分布 95% CI
- weighted_proportion_with_ci: 逆方差加权合并阳性率 + Wilson 95% CI
- weighted_linear_trend: 加权线性回归趋势（斜率 / p 值 / R² / 方向）
- gini: 基尼系数
- coefficient_of_variation: 变异系数
- lowess: 简化 LOWESS（局部加权线性回归）平滑
- inverse_variance_meta: 逆方差固定/随机效应 meta 合并 + I²
- reliability_grade: 证据可靠性分级 A/B/C/D

边界约定：空列表返回 None 或 0；p=0 或 1 采用连续性校正兜底，不抛异常。
"""

import math
from collections.abc import Sequence
from typing import Literal

__all__ = [
    "coefficient_of_variation",
    "geometric_mean_with_ci",
    "gini",
    "inverse_variance_meta",
    "lowess",
    "reliability_grade",
    "weighted_linear_trend",
    "weighted_proportion_with_ci",
]


# ============================================================
# 内部数值工具（t 分布 / 正态分布 / 不完全 Beta / Wilson 区间）
# ============================================================

# 95% 置信水平、双侧 t 分布临界值（df = 1..30）；df > 30 用正态近似 z=1.96
_T_CRIT_95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080,
    22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048,
    29: 2.045, 30: 2.042,
}


def _erf(x: float) -> float:
    """误差函数 erf(x)，Abramowitz-Stegun 7.1.26 近似（精度 ~1.5e-7）。"""
    sign = 1.0 if x >= 0 else -1.0
    ax = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * ax)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * math.exp(-ax * ax)
    return sign * y


def _normal_cdf(z: float) -> float:
    """标准正态分布 CDF Φ(z)。"""
    return 0.5 * (1.0 + _erf(z / math.sqrt(2.0)))


def _betacf(a: float, b: float, x: float) -> float:
    """不完全 Beta 函数继续分式求值（Numerical Recipes betacf）。"""
    maxit = 200
    eps = 3.0e-12
    fpmin = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lnbt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
            + a * math.log(x) + b * math.log1p(-x))
    bt = math.exp(lnbt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_two_sided_p(t: float, df: float) -> float | None:
    """t 分布双侧 p 值：P(|T| >= |t|)。df 很大时退化为正态近似。"""
    if df <= 0 or t is None or not math.isfinite(t):
        return None
    if df > 300:
        return 2.0 * (1.0 - _normal_cdf(abs(t)))
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def _t_critical_two_sided(df: int) -> float:
    """95% 双侧 t 临界值；df 超出表范围用 z=1.96 近似。"""
    if df in _T_CRIT_95:
        return _T_CRIT_95[df]
    return 1.96


def _wilson_interval(p: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 区间（p ∈ [0,1]，n > 0）。返回 (lower, upper)。"""
    if n <= 0:
        return (p, p)
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


# ============================================================
# 1. 几何均数 + 对数域 t 分布 CI
# ============================================================

def geometric_mean_with_ci(values: Sequence[float | None]) -> dict:
    """几何均数（GMC）及其 95% 置信区间（对数域 t 分布近似）。

    对 ln(v) 求均值与样本标准差，以 df=n-1 的 t 临界值在对数域构建 95% CI 后指数还原。
    GMC 数据必须为正；非正 / 缺失值被剔除。

    边界：空列表或无可取值 → ``{gmc: None, ci_lower: None, ci_upper: None, n: 0}``；
    单元素 → 三个值均为该元素本身。
    """
    vals = [float(v) for v in values if v is not None and v > 0]
    if not vals:
        return {"gmc": None, "ci_lower": None, "ci_upper": None, "n": 0}
    n = len(vals)
    logs = [math.log(v) for v in vals]
    mean_log = sum(logs) / n
    gmc = math.exp(mean_log)
    if n == 1:
        return {"gmc": round(gmc, 4), "ci_lower": round(gmc, 4), "ci_upper": round(gmc, 4), "n": n}
    var = sum((v - mean_log) ** 2 for v in logs) / (n - 1)
    se = math.sqrt(var / n)
    tcrit = _t_critical_two_sided(n - 1)
    lo = math.exp(mean_log - tcrit * se)
    hi = math.exp(mean_log + tcrit * se)
    return {"gmc": round(gmc, 4), "ci_lower": round(lo, 4), "ci_upper": round(hi, 4), "n": n}


# ============================================================
# 2. 逆方差加权合并阳性率 + Wilson 95% CI
# ============================================================

def weighted_proportion_with_ci(p_list: Sequence[float | None],
                                n_list: Sequence[float | None]) -> dict:
    """逆方差加权合并阳性率 + Wilson 95% CI。

    - 权重 w_i = n_i / (p_i·(1-p_i))，即二项方差 p(1-p)/n 的倒数；
    - p=0 或 1 的边界研究采用连续性校正（x+0.5, n+1）避免方差为 0 / 权重无穷大；
    - 合并率 pooled = Σ(w·p) / Σw，95% CI 采用 Wilson score 区间（n 取合并总样本量）；
    - p > 1 的输入按百分数处理（除以 100）。

    边界：空列表 / 无有效研究 → ``pooled_proportion: None, n: 0, n_studies: 0``。
    """
    pairs: list[tuple[float, float, float]] = []  # (p_adj, n_adj, var)
    for p, n in zip(p_list, n_list, strict=False):
        if p is None or n is None:
            continue
        p = float(p)
        n = float(n)
        if n <= 0:
            continue
        if p > 1.0:
            p = p / 100.0
        if p < 0.0 or p > 1.0:
            continue
        x = p * n
        n_adj = n
        if p == 0.0 or p == 1.0:
            x = x + 0.5
            n_adj = n + 1.0
        p_adj = x / n_adj
        var = p_adj * (1.0 - p_adj) / n_adj
        if var <= 0:
            continue
        pairs.append((p_adj, n_adj, var))

    if not pairs:
        return {"pooled_proportion": None, "ci_lower": None, "ci_upper": None, "n": 0, "n_studies": 0}

    total_w = sum(1.0 / var for _, _, var in pairs)
    num = sum(p_adj / var for p_adj, _, var in pairs)
    total_n = sum(n_adj for _, n_adj, _ in pairs)
    pooled = num / total_w
    lo, hi = _wilson_interval(pooled, total_n)
    return {
        "pooled_proportion": round(pooled, 6),
        "ci_lower": round(lo, 6),
        "ci_upper": round(hi, 6),
        "n": round(total_n),
        "n_studies": len(pairs),
    }


# ============================================================
# 3. 加权线性回归趋势
# ============================================================

def weighted_linear_trend(years: Sequence[float | None],
                          values: Sequence[float | None],
                          weights: Sequence[float | None] | None = None) -> dict:
    """加权线性回归趋势 y = a + b·year。

    采用加权最小二乘；slope = Sxy / Sxx，R² 为加权决定系数，p 值来自对斜率的标准误
    t 检验（自由度 n-2）。

    返回：``{slope_per_year, p_value, r_squared, direction, n}``，
    direction ∈ {'increasing', 'decreasing', 'flat'}。
    数据点 < 2 或 x 无方差 → 各统计量为 None / direction=None。
    """
    xs: list[float] = []
    ys: list[float] = []
    ws: list[float] = []
    if weights is None:
        weights = [1.0] * len(years)
    for x, y, w in zip(years, values, weights, strict=False):
        if x is None or y is None or w is None:
            continue
        x = float(x)
        y = float(y)
        w = float(w)
        if w <= 0:
            continue
        xs.append(x)
        ys.append(y)
        ws.append(w)
    n = len(xs)
    if n < 2:
        return {"slope_per_year": None, "p_value": None, "r_squared": None, "direction": None, "n": n}

    w_sum = sum(ws)
    x_bar = sum(w * x for w, x in zip(ws, xs, strict=False)) / w_sum
    y_bar = sum(w * y for w, y in zip(ws, ys, strict=False)) / w_sum
    sxx = sum(w * (x - x_bar) ** 2 for w, x in zip(ws, xs, strict=False))
    sxy = sum(w * (x - x_bar) * (y - y_bar) for w, x, y in zip(ws, xs, ys, strict=False))
    if sxx <= 1e-12:
        return {"slope_per_year": 0.0, "p_value": None, "r_squared": 0.0, "direction": "flat", "n": n}

    slope = sxy / sxx
    intercept = y_bar - slope * x_bar
    ss_res = sum(w * (y - (intercept + slope * x)) ** 2 for w, x, y in zip(ws, xs, ys, strict=False))
    ss_tot = sum(w * (y - y_bar) ** 2 for w, y in zip(ws, ys, strict=False))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 1.0

    dof = n - 2
    if dof <= 0:
        p_value = None
    elif ss_res <= 1e-12:
        p_value = 0.0  # 完美拟合
    else:
        mse = ss_res / dof
        se_slope = math.sqrt(mse / sxx)
        t = slope / se_slope if se_slope > 0 else 0.0
        p_value = _t_two_sided_p(t, dof)

    if slope > 1e-9:
        direction = "increasing"
    elif slope < -1e-9:
        direction = "decreasing"
    else:
        direction = "flat"

    return {
        "slope_per_year": round(slope, 6),
        "p_value": round(p_value, 6) if p_value is not None else None,
        "r_squared": round(r2, 6),
        "direction": direction,
        "n": n,
    }


# ============================================================
# 4. 基尼系数
# ============================================================

def gini(coefs_or_values: Sequence[float | None]) -> float:
    """基尼系数（取值 0-1，0 = 完全均等）。

    对排序后的非负序列用公式 G = (2·Σ(i+1)·x_i) / (n·Σx) - (n+1)/n（i 从 0 起）。
    负值被忽略；空列表 / 全零 / 单元素 → 0.0。
    """
    vals = sorted(float(v) for v in coefs_or_values if v is not None and v >= 0)
    n = len(vals)
    if n == 0:
        return 0.0
    total = sum(vals)
    if total <= 0:
        return 0.0
    cum = sum((i + 1) * v for i, v in enumerate(vals))
    g = (2.0 * cum) / (n * total) - (n + 1.0) / n
    return round(min(1.0, max(0.0, g)), 6)


# ============================================================
# 5. 变异系数
# ============================================================

def coefficient_of_variation(values: Sequence[float | None]) -> float:
    """变异系数 CV = 样本标准差 / |均值|（无量纲比值）。

    空列表 / 均值 = 0 / 单元素 → 0.0（无法计算）。
    """
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    if mean == 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    return round(math.sqrt(var) / abs(mean), 6)


# ============================================================
# 6. 简化 LOWESS 平滑
# ============================================================

def lowess(x: Sequence[float | None], y: Sequence[float | None],
           frac: float = 0.6) -> tuple[list, list]:
    """简化 LOWESS（局部加权线性回归）平滑。

    对每个点取最近的 k = max(2, ceil(frac·n)) 个邻居，按 tricube 核权重
    w = (1 - u³)³（u = 距离/最大距离）做局部加权线性拟合，输出该点拟合值。
    返回 (xs, ys)，二者均按 x 升序。

    边界：n < 2 或输入长度不一致 → ([], [])。
    """
    xs_raw: list[float] = []
    ys_raw: list[float] = []
    for xi, yi in zip(x, y, strict=False):
        if xi is None or yi is None:
            continue
        xs_raw.append(float(xi))
        ys_raw.append(float(yi))
    n = len(xs_raw)
    if n < 2 or n != len(ys_raw):
        return [], []

    pairs = sorted(zip(xs_raw, ys_raw, strict=False))
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]

    k = max(2, min(n, math.ceil(frac * n)))
    fitted: list[float] = []
    for i in range(n):
        xi = xs[i]
        dists = sorted((abs(xs[j] - xi), j) for j in range(n))
        maxd = dists[k - 1][0]
        if maxd <= 1e-12:
            fitted.append(ys[i])
            continue
        ws: list[float] = []
        xw: list[float] = []
        yw: list[float] = []
        for _, j in dists[:k]:
            u = abs(xs[j] - xi) / maxd
            w = (1.0 - u ** 3) ** 3 if u < 1.0 else 0.0
            if w <= 0:
                continue
            ws.append(w)
            xw.append(xs[j])
            yw.append(ys[j])
        w_sum = sum(ws)
        if w_sum <= 0:
            fitted.append(ys[i])
            continue
        xb = sum(w * v for w, v in zip(ws, xw, strict=False)) / w_sum
        yb = sum(w * v for w, v in zip(ws, yw, strict=False)) / w_sum
        sxx = sum(w * (v - xb) ** 2 for w, v in zip(ws, xw, strict=False))
        if sxx <= 1e-12:
            fitted.append(yb)
        else:
            sxy = sum(w * (v - xb) * (yv - yb) for w, v, yv in zip(ws, xw, yw, strict=False))
            b = sxy / sxx
            a = yb - b * xb
            fitted.append(a + b * xi)

    return xs, fitted


# ============================================================
# 7. 逆方差 meta 合并（固定/随机效应）+ I²
# ============================================================

def inverse_variance_meta(p_list: Sequence[float | None],
                          n_list: Sequence[float | None],
                          ci_lower: Sequence[float | None],
                          ci_upper: Sequence[float | None]) -> dict:
    """逆方差加权 meta 分析（固定/随机效应）+ 异质性 I²。

    - 每项研究方差优先由 95% CI 推导：var = ((upper-lower)/(2·1.96))²；
      CI 若 >1（百分数）会与 p 同样除以 100 归一为比例，避免单位不一致导致方差虚高、I² 被低估；
      若 CI 缺失，退化为二项方差 p(1-p)/n（p=0/1 采用连续性校正 x+0.5, n+1）；
    - 固定效应 pooled_fe = Σ(w·p)/Σw, w = 1/var；
    - Q = Σ w·(p - pooled_fe)²；I² = max(0, (Q - df)/Q)·100%，df = k-1；
    - 随机效应（DerSimonian-Laird）：τ² = max(0, (Q-df)/(Σw - Σw²/Σw))，
      pooled_re = Σ(w*·p)/Σw*, w* = 1/(var + τ²)。

    边界：空列表 / 无有效研究 → pooled 均为 None, I² = 0, Q = 0, k = 0。
    """
    studies: list[tuple[float, float, float]] = []  # (p, n, var)
    for p, n, lo, hi in zip(p_list, n_list, ci_lower, ci_upper, strict=False):
        if p is None or n is None or n <= 0:
            continue
        p = float(p)
        if p > 1.0:
            p = p / 100.0
        if p < 0.0 or p > 1.0:
            continue
        n = float(n)
        if lo is not None and hi is not None:
            lo_f, hi_f = float(lo), float(hi)
            # 与 p 一致：CI 若以百分数给出（>1）则归一为比例，保持方差量纲一致
            if lo_f > 1.0 and hi_f > 1.0:
                lo_f /= 100.0
                hi_f /= 100.0
            var = ((hi_f - lo_f) / (2.0 * 1.96)) ** 2
        else:
            x = p * n
            n_adj = n
            p_adj = p
            if p == 0.0 or p == 1.0:
                x = x + 0.5
                n_adj = n + 1.0
                p_adj = x / n_adj
            var = p_adj * (1.0 - p_adj) / n_adj
        if var <= 0:
            continue
        studies.append((p, n, var))

    k = len(studies)
    if k == 0:
        return {
            "pooled_fixed": None,
            "pooled_random": None,
            "i_squared_percent": 0.0,
            "tau_squared": 0.0,
            "q_statistic": 0.0,
            "k": 0,
        }

    inv_vars = [1.0 / var for _, _, var in studies]
    w_sum = sum(inv_vars)
    pooled_fe = sum(p * w for (p, _, _), w in zip(studies, inv_vars, strict=False)) / w_sum

    q = sum((p - pooled_fe) ** 2 / var for p, _, var in studies)
    df = k - 1
    i2 = max(0.0, (q - df) / q) * 100.0 if q > 0 else 0.0

    # DerSimonian-Laird 随机效应
    w2_sum = sum(w * w for w in inv_vars)
    tau2 = max(0.0, (q - df) / (w_sum - w2_sum / w_sum)) if (q - df) > 0 and (w_sum - w2_sum / w_sum) > 0 else 0.0
    wstar = [1.0 / (var + tau2) for _, _, var in studies]
    wstar_sum = sum(wstar)
    pooled_re = sum(p * w for (p, _, _), w in zip(studies, wstar, strict=False)) / wstar_sum if wstar_sum > 0 else None

    return {
        "pooled_fixed": round(pooled_fe, 6),
        "pooled_random": round(pooled_re, 6) if pooled_re is not None else None,
        "i_squared_percent": round(i2, 2),
        "tau_squared": round(tau2, 8),
        "q_statistic": round(q, 6),
        "k": k,
    }


# ============================================================
# 8. 证据可靠性分级
# ============================================================

def reliability_grade(sample_size: int | None,
                      has_ci: bool,
                      confidence: str | None,
                      is_grounded: bool,
                      n_studies: int | None) -> Literal['A', 'B', 'C', 'D']:
    """证据可靠性分级（A/B/C/D）。

    计分规则（满分 12）：
      - 样本量:  ≥1000 +4 / ≥300 +3 / ≥100 +2 / ≥30 +1 / 其余 0
      - 是否报告 CI: +2
      - 置信度:  high +2 / medium +1 / low 或未知 0
      - 原文可溯源(is_grounded): +2
      - 研究数:  ≥5 +2 / ≥2 +1 / 其余 0
    等级: ≥9 → A；≥6 → B；≥3 → C；<3 → D。
    """
    score = 0
    ss = sample_size or 0
    if ss >= 1000:
        score += 4
    elif ss >= 300:
        score += 3
    elif ss >= 100:
        score += 2
    elif ss >= 30:
        score += 1

    if has_ci:
        score += 2

    conf = (confidence or "").lower()
    if conf == "high":
        score += 2
    elif conf == "medium":
        score += 1

    if is_grounded:
        score += 2

    ns = n_studies or 0
    if ns >= 5:
        score += 2
    elif ns >= 2:
        score += 1

    if score >= 9:
        return "A"
    if score >= 6:
        return "B"
    if score >= 3:
        return "C"
    return "D"

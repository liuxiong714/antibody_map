"""方法学脚注统一生成。

服务层与报告生成共用：``build_methodology_note(module, params, meta)``
生成一段中文方法学段落，挂到所有 /analysis/* 响应的 ``meta.methodology_note``。

``meta`` 承载事实性统计信息（纳入估计数、文献数、合并模型、I²、CI 方法、
生效假设、快照日期等）；``params`` 为请求筛选参数；``module`` 为模块标识，
用于默认文案兜底。
"""

from datetime import date
from typing import Any

# 模块显示名（中文）
MODULE_NAMES = {
    "trend": "逐年趋势分析",
    "region_compare": "区域对比分析",
    "age_stratify": "年龄分层分析",
    "summary": "汇总统计",
    "equity": "省间公平性分析",
    "quality": "数据质量评估",
    "goal_tracking": "目标达成追踪",
    "age_curve": "血清阳性率-年龄曲线",
    "birth_cohort": "出生队列分析",
    "meta_merge": "同省多研究 Meta 合并",
    "meta_analysis": "多文献 Meta 分析",
    "spatial_hotspots": "空间热点/冷点分析",
    "assay_heterogeneity": "检测方法异质性分析",
    "simulate": "免疫屏障模拟",
    "immune_barrier": "免疫屏障评估",
    "foi": "FOI 与群体免疫分析",
    "vaccine": "疫苗效果与接种率分析",
    "data_gaps": "数据覆盖度分析",
    "coverage_review": "审核状态统计",
    "approved_data_points": "数据点列表",
    "report": "报告生成",
    "antigenic_map": "抗原图谱（滴度矩阵制图）",
}

# 合并模型显示名（英文内部值 → 中文）
MODEL_NAMES = {
    "random": "随机效应模型(DerSimonian-Laird)",
    "random_effects": "随机效应模型(DerSimonian-Laird)",
    "dl": "随机效应模型(DerSimonian-Laird)",
    "dersimonian-laird": "随机效应模型(DerSimonian-Laird)",
    "fixed": "固定效应模型",
    "fixed_effects": "固定效应模型",
}

# CI 方法显示名
CI_NAMES = {
    "wilson": "Wilson 法",
    "wilson_ci": "Wilson 法",
    "clopper_pearson": "Clopper-Pearson 精确法",
    "normal_approx": "正态近似法",
    "delta": "Delta 法",
    "meta": "Meta 合并(Freeman-Tukey 变换)",
    "meta_ft": "Meta 合并(Freeman-Tukey 变换)",
}

# 催化模型显示名
CATALYTIC_MODEL_NAMES = {
    "M1_constant": "M1 恒定FOI",
    "M2_seroreversion": "M2 血清转阴",
    "M3_two_phase": "M3 两阶段",
}

# 统计检验显示名（内部值 → 中文）
TEST_NAMES = {
    "cochran_armitage": "Cochran-Armitage 趋势检验",
    "two_proportion": "两率差异检验",
}


def _today() -> str:
    return date.today().isoformat()


def _fmt_assumption(key: str, value: Any) -> str | None:
    """把假设键值转成可读中文片段；无法展示的值返回 None。"""
    if value is None or value == "" or value is False:
        return None
    if key == "life_expectancy":
        return f"期望寿命 {value} 年"
    if key == "seroreversion_mu":
        return f"血清转阴率 μ={value}/年"
    if key == "hit_source_override":
        return f"HIT 来源强制: {value}"
    if key == "hit_source":
        return f"HIT 来源: {value}"
    if key == "catalytic_model":
        return f"催化模型 {value}"
    return f"{key}={value}"


def build_methodology_note(module: str, params: dict, meta: dict) -> str:
    """生成中文方法学段落。

    参数
    ----
    module : str
        分析模块标识（见 ``MODULE_NAMES``）。
    params : dict
        请求筛选参数（disease/province/year_start 等），用于兜底文案。
    meta : dict
        事实性统计信息，可含：
        - ``n_estimates``: 纳入估计数
        - ``n_literatures``: 纳入文献数
        - ``quality_grades``: 真值表示仅纳入 A/B 级估计
        - ``model``: 合并模型内部值
        - ``I2``: 异质性 I²（百分数）
        - ``ci_method``: CI 方法内部值
        - ``test``: 统计检验内部值
        - ``catalytic_model``: 催化模型名
        - ``catalytic_mu``: 固定血清转阴率
        - ``standard_population``: 标准化人口版本
        - ``assumptions``: dict，生效假设
        - ``snapshot_date``: 数据快照日期（缺省为今天）
    """
    parts: list[str] = []

    # 1) 数据纳入
    n_est = meta.get("n_estimates")
    if n_est is not None:
        head = "共纳入 "
        if meta.get("quality_grades"):
            head += "A/B 级"
        head += f"估计 {n_est} 个"
        n_lit = meta.get("n_literatures")
        if n_lit is not None:
            head += f"（{n_lit} 篇文献）"
        parts.append(head)

    # 2) 合并模型 + 异质性
    model = meta.get("model")
    i2 = meta.get("I2")
    if model:
        model_txt = MODEL_NAMES.get(str(model).lower(), str(model))
        if i2 is not None:
            parts.append(f"合并采用{model_txt}，I²={i2}%")
        else:
            parts.append(f"合并采用{model_txt}")

    # 3) 统计检验
    test = meta.get("test")
    if test:
        parts.append(f"检验采用{TEST_NAMES.get(str(test), str(test))}")

    # 4) CI 方法
    ci = meta.get("ci_method")
    if ci:
        parts.append(f"CI 为 {CI_NAMES.get(str(ci).lower(), str(ci))}")

    # 5) 催化模型假设
    cat_model = meta.get("catalytic_model")
    if cat_model:
        cat_txt = CATALYTIC_MODEL_NAMES.get(str(cat_model), str(cat_model))
        mu = meta.get("catalytic_mu")
        if mu:
            parts.append(f"催化模型{cat_txt}拟合（血清转阴率固定 μ={mu}/年）")
        else:
            parts.append(f"催化模型{cat_txt}拟合")

    # 6) 标准化人口
    std_pop = meta.get("standard_population")
    if std_pop:
        parts.append(f"年龄标准化采用{std_pop}")

    # 7) 生效假设
    assumptions = meta.get("assumptions")
    if assumptions:
        a_parts = [_fmt_assumption(k, v) for k, v in assumptions.items()]
        a_parts = [a for a in a_parts if a]
        if a_parts:
            parts.append("假设：" + "；".join(a_parts))

    # 8) 快照日期
    snap = meta.get("snapshot_date") or _today()

    text = "; ".join(parts)
    if not text:
        # 兜底：无任何事实信息时给出模块级通用说明（数据纳入等事实缺失场景）
        module_name = MODULE_NAMES.get(module, module)
        disease = (params or {}).get("disease")
        prov = (params or {}).get("province")
        scope = []
        if disease:
            scope.append(f"疾病={disease}")
        if prov:
            scope.append(f"省份={prov}")
        scope_txt = f"（{'、'.join(scope)}）" if scope else ""
        text = f"基于已审核血清学估计进行{module_name}{scope_txt}"
    return text + f"；{snap} 数据快照。"

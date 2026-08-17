"""数据点质量评分服务（0-100 分 + A/B/C 三级）。

全部打分规则为数据驱动 dict + 单元可测纯函数，不依赖数据库/IO，
便于在前端 Tooltip 中展开六项得分明细，并在审核通过后异步重算。

评分信号（满分 100）：
1. 样本量（30）
2. 抽样方式（25）
3. 检测方法（15）
4. 人群代表性（15）
5. 调查级别（10，并写入 estimate_grade）
6. 溯源置信度（5）

分级：A≥75；B 50–74；C<50。
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

from app.core.term_normalizer import METHOD_MAP

# ── 分级阈值（数据驱动）──────────────────────────────
GRADE_RULES: list[dict] = [
    {"min_score": 75, "grade": "A", "label": "高质量"},
    {"min_score": 50, "grade": "B", "label": "中质量"},
    {"min_score": 0, "grade": "C", "label": "低质量"},
]

# ── 信号 1：样本量分档（30 分）──────────────────────
SAMPLE_SIZE_RULES: list[dict] = [
    {"min_n": 2001, "score": 30, "label": "样本量>2000"},
    {"min_n": 500, "score": 24, "label": "样本量 500–2000"},
    {"min_n": 100, "score": 16, "label": "样本量 100–500"},
    {"min_n": 1, "score": 8, "label": "样本量<100"},
    {"min_n": 0, "score": 0, "label": "样本量缺失"},
]
SAMPLE_SIZE_MAX = 30

# ── 信号 2：抽样方式（25 分）────────────────────────
SAMPLING_RULES: list[dict] = [
    {
        "score": 25,
        "label": "随机/多阶段/分层整群抽样",
        "pattern": r"随机|多阶段|分层整群|分层抽樣|probability\s*sampling|multi[- ]stage|stratified|cluster\s*sampling",
        "flags": re.IGNORECASE,
    },
    {
        "score": 6,
        "label": "便利抽样",
        "pattern": r"便利|convenience",
        "flags": re.IGNORECASE,
    },
    {"score": 12, "label": "抽样方式未注明"},
]
SAMPLING_MAX = 25

# ── 信号 3：检测方法（15 分）────────────────────────
DETECTION_METHOD_MAX = 15
# 非空但不在标准字典表内 → 8 分；空 → 0 分

# ── 信号 4：人群代表性（15 分）──────────────────────
POPULATION_RULES: list[dict] = [
    {
        "score": 15,
        "label": "一般/全人群/社区/学校人群",
        "pattern": r"general|全人群|一般人群|社区|school[- ]based|在校|学生",
        "flags": re.IGNORECASE,
    },
    {
        "score": 5,
        "label": "门诊/医院/患者人群",
        "pattern": r"门诊|医院|hospital|患者|病例",
        "flags": re.IGNORECASE,
    },
    {"score": 8, "label": "其他/未明确人群"},
]
POPULATION_MAX = 15

# ── 信号 5：调查级别（10 分，写入 estimate_grade）───
ESTIMATE_GRADE_MAX = 10
# 覆盖全国≥10省 → national(10)；单省多市/大样本单省 → provincial(8)；其他 → local(5)
NATIONAL_PROVINCE_THRESHOLD = 10
PROVINCIAL_SAMPLE_THRESHOLD = 2000

# ── 信号 6：溯源置信度（5 分）────────────────────────
CONFIDENCE_RULES: dict[str, dict] = {
    "high": {"score": 5, "label": "高置信"},
    "medium": {"score": 3, "label": "中置信"},
    "low": {"score": 1, "label": "低置信"},
}
CONFIDENCE_MAX = 5


def _get(dp: Any, name: str, default: Any = None) -> Any:
    """同时兼容 SQLAlchemy 模型实例与 dict/Mapping 两种数据点表示。"""
    if isinstance(dp, Mapping):
        return dp.get(name, default)
    return getattr(dp, name, default)


def _split_multi(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in re.split(r"[;,；、，]", str(value)) if v.strip()]


def score_sample_size(n: Optional[int]) -> dict:
    """信号 1：样本量分档（0-30 分）。"""
    n = n if isinstance(n, (int, float)) and n > 0 else 0
    for rule in SAMPLE_SIZE_RULES:
        if n >= rule["min_n"]:
            return {"score": rule["score"], "label": rule["label"], "max": SAMPLE_SIZE_MAX}
    return {"score": 0, "label": SAMPLE_SIZE_RULES[-1]["label"], "max": SAMPLE_SIZE_MAX}


def score_sampling(text: Optional[str]) -> dict:
    """信号 2：抽样方式（0-25 分）。

    输入为文献摘要/全文（无全文缓存时仅 title+journal），按正则命中判断：
    随机/多阶段/分层整群 → 25；便利 → 6；未命中 → 12。
    """
    if text:
        for rule in SAMPLING_RULES:
            pattern = rule.get("pattern")
            if pattern and re.search(pattern, str(text)):
                return {"score": rule["score"], "label": rule["label"], "max": SAMPLING_MAX}
    return {"score": 12, "label": "抽样方式未注明", "max": SAMPLING_MAX}


def score_detection_method(method: Optional[str]) -> dict:
    """信号 3：检测方法（0-15 分）。非空且在标准字典表内 → 15；非空不在表 → 8；空 → 0。"""
    if not method:
        return {"score": 0, "label": "未注明检测方法", "max": DETECTION_METHOD_MAX}
    method = str(method).strip()
    if not method:
        return {"score": 0, "label": "未注明检测方法", "max": DETECTION_METHOD_MAX}
    # 在标准字典表内：METHOD_MAP 键或其规范化后的标准值
    known = method in METHOD_MAP or method.upper() in {v.upper() for v in METHOD_MAP.values()}
    if known:
        return {"score": 15, "label": f"标准检测方法（{method}）", "max": DETECTION_METHOD_MAX}
    return {"score": 8, "label": f"非标准检测方法（{method}）", "max": DETECTION_METHOD_MAX}


def score_population(population: Optional[str]) -> dict:
    """信号 4：人群代表性（0-15 分）。"""
    if population:
        text = str(population)
        for rule in POPULATION_RULES:
            pattern = rule.get("pattern")
            if pattern and re.search(pattern, text):
                return {"score": rule["score"], "label": rule["label"], "max": POPULATION_MAX}
    return {"score": 8, "label": "其他/未明确人群", "max": POPULATION_MAX}


def score_estimate_grade(province: Optional[str], city: Optional[str], sample_size: Optional[int]) -> dict:
    """信号 5：调查级别（0-10 分）+ estimate_grade（national/provincial/local）。

    启发规则：覆盖省份≥10 → national；单省多市或大样本(≥2000)单省 → provincial；其他 → local。
    """
    provinces = _split_multi(province)
    cities = _split_multi(city)
    n = sample_size if isinstance(sample_size, (int, float)) and sample_size > 0 else 0

    if len(provinces) >= NATIONAL_PROVINCE_THRESHOLD:
        return {"score": 10, "label": "覆盖全国（≥10省）", "max": ESTIMATE_GRADE_MAX, "estimate_grade": "national"}
    if len(provinces) == 1 and len(cities) >= 2:
        return {"score": 8, "label": "单省多市调查", "max": ESTIMATE_GRADE_MAX, "estimate_grade": "provincial"}
    if len(provinces) >= 1 and n >= PROVINCIAL_SAMPLE_THRESHOLD:
        return {"score": 8, "label": "单省大样本调查", "max": ESTIMATE_GRADE_MAX, "estimate_grade": "provincial"}
    return {"score": 5, "label": "局部/单点调查", "max": ESTIMATE_GRADE_MAX, "estimate_grade": "local"}


def score_confidence(confidence: Optional[str]) -> dict:
    """信号 6：溯源置信度（0-5 分）。high/medium/low → 5/3/1。"""
    rule = CONFIDENCE_RULES.get((confidence or "").strip().lower())
    if not rule:
        return {"score": 1, "label": "低置信", "max": CONFIDENCE_MAX}
    return {"score": rule["score"], "label": rule["label"], "max": CONFIDENCE_MAX}


def grade_for_score(score: int) -> str:
    """按总分给出 A/B/C 分级。"""
    for rule in sorted(GRADE_RULES, key=lambda r: r["min_score"], reverse=True):
        if score >= rule["min_score"]:
            return rule["grade"]
    return "C"


def score_data_point(dp: Any, literature_text: Optional[str] = None) -> dict:
    """数据点质量评分入口（纯函数）。

    参数：
      - dp: DataPoint 模型实例或 dict（含 sample_size/method/population/province/city/confidence 等字段）
      - literature_text: 文献摘要/全文（有缓存即复用；无缓存时仅用 title+journal 粗打）

    返回 ``{quality_score, quality_grade, estimate_grade, breakdown}``。
    """
    breakdown: dict[str, dict] = {}

    # 信号 1：样本量
    sample = score_sample_size(_get(dp, "sample_size"))
    breakdown["sample_size"] = sample

    # 信号 2：抽样方式（优先文献全文/摘要；无文本则退化为 title+journal 离线标注）
    if literature_text:
        sampling_text = str(literature_text)
    else:
        sampling_text = " ".join(
            str(x) for x in (_get(dp, "title"), _get(dp, "journal"))
            if x
        )
    breakdown["sampling"] = score_sampling(sampling_text)

    # 信号 3：检测方法（DataPoint 的 method 字段即检测方法；兼容 detection_method 键）
    method = _get(dp, "method")
    if method is None:
        method = _get(dp, "detection_method")
    breakdown["detection_method"] = score_detection_method(method)

    # 信号 4：人群代表性
    breakdown["population"] = score_population(_get(dp, "population"))

    # 信号 5：调查级别 + estimate_grade
    estimate = score_estimate_grade(
        _get(dp, "province"), _get(dp, "city"), _get(dp, "sample_size")
    )
    breakdown["estimate_grade"] = estimate

    # 信号 6：溯源置信度
    breakdown["confidence"] = score_confidence(_get(dp, "confidence"))

    total = sum(item["score"] for item in breakdown.values())
    return {
        "quality_score": total,
        "quality_grade": grade_for_score(total),
        "estimate_grade": estimate.get("estimate_grade", "local"),
        "breakdown": breakdown,
    }

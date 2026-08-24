"""Precise character-level grounding for LLM extractions (P0 feature) + Schema validation.

This module implements:
 1. LLM extraction result grounding: given a source text and an extraction item,
    try to locate the extraction in the original text and return a char interval.
 2. Enum and schema-level hard validation: province names, confidence, data_type,
    review_status, value ranges, etc. Items that fail validation are flagged as
    low-confidence so the reviewer can prioritize fixing them.
"""
from __future__ import annotations

import logging
import re
import difflib
from dataclasses import dataclass
from typing import Optional

from app.core.term_normalizer import CHINA_PROVINCE_NAMES

logger = logging.getLogger("uvicorn")

# P2-4：数值回验关注的 key 字段
_NUMERIC_GROUNDING_KEYS = ("positivity_rate", "gmc_value", "sample_size")

# A3：从配置读取模糊匹配阈值，默认 0.72
try:
    from app.config import settings as _settings
    _DEFAULT_FUZZY_THRESHOLD = getattr(_settings, "GROUNDING_FUZZY_THRESHOLD", 0.72)
except Exception:
    _DEFAULT_FUZZY_THRESHOLD = 0.72

_ALLOWED_DATA_TYPES = {"seroprevalence", "gmc"}
_ALLOWED_CONFIDENCE = {"high", "medium", "low"}
_ALLOWED_REVIEW_STATUS = {"pending", "approved", "rejected"}


# ---------------------------------------------------------------------------
# 1. Character-level grounding
# ---------------------------------------------------------------------------


@dataclass
class GroundingResult:
    """Result of trying to ground a piece of extracted context back to source."""
    is_grounded: bool = False
    source_char_start: Optional[int] = None
    source_char_end: Optional[int] = None
    matched_snippet: Optional[str] = None
    method: Optional[str] = None  # "exact" | "fuzzy" | "keyphrase" | None


def _normalize_for_match(s: str) -> str:
    """Collapse whitespace / CJK punct so matching is more robust to OCR noise."""
    if not s:
        return ""
    # strip common OCR / formatting noise
    s = re.sub(r"\s+", "", s)
    s = s.replace("\u3000", "")  # full-width space
    # normalize Chinese quotation marks
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return s


def _exact_match(text_norm: str, ctx_norm: str, ctx_raw: str) -> Optional[tuple[int, int, str]]:
    """Try exact match on normalized text, return (start, end) indices on ORIGINAL text.

    Because normalization removes characters, we map normalized-offset back to
    original offsets by maintaining a per-char index map.
    """
    if not ctx_norm or len(ctx_norm) < 4:
        return None

    # Build index map: norm_idx -> original_idx
    original_indices: list[int] = []
    norm_chars: list[str] = []
    for i, ch in enumerate(text_norm):
        # Re-run normalization logic: skip whitespace / full-width spaces
        if ch in (" ", "\t", "\n", "\r", "\u3000"):
            continue
        norm_chars.append(ch)
        original_indices.append(i)
    collapsed = "".join(norm_chars)

    pos = collapsed.find(ctx_norm)
    if pos == -1:
        # try a substring match (LLM often adds/removes a few chars at edges)
        for window in (len(ctx_norm), max(4, len(ctx_norm) - 2), max(4, len(ctx_norm) - 4)):
            for slide in range(0, max(1, len(ctx_norm) - window + 1), 2):
                sub = ctx_norm[slide:slide + window]
                if len(sub) < 4:
                    continue
                p = collapsed.find(sub)
                if p != -1:
                    pos = p
                    break
            if pos != -1:
                break
        if pos == -1:
            return None

    end = min(pos + len(ctx_norm), len(original_indices))
    orig_start = original_indices[pos]
    orig_end = original_indices[end - 1] + 1 if end - 1 < len(original_indices) else orig_start + len(ctx_raw)
    matched = text_norm[orig_start:orig_end]
    return orig_start, orig_end, matched


def _fuzzy_match(
    text_norm: str,
    ctx_norm: str,
    threshold: float = _DEFAULT_FUZZY_THRESHOLD,
) -> Optional[tuple[int, int, str]]:
    """Fuzzy match using LCS dynamic programming alignment (P0-2 upgrade).

    Replaces the previous difflib.SequenceMatcher sliding-window approach with an
    O(n*m) LCS-based alignment that:
    1. Finds the best matching window in text_norm for ctx_norm.
    2. Returns the char span with the highest LCS coverage of ctx_norm.

    A3：threshold 参数可从配置 GROUNDING_FUZZY_THRESHOLD 覆盖，默认 0.72。
    """
    if not ctx_norm or len(ctx_norm) < 6:
        return None

    n = len(text_norm)
    m = len(ctx_norm)
    # 限制 ctx 长度避免 DP 表过大
    if m > 200:
        ctx_norm = ctx_norm[:200]
        m = len(ctx_norm)

    best_ratio = 0.0
    best_span: Optional[tuple[int, int, str]] = None
    # 滑动窗口，窗口大小略大于 ctx 以容纳插入
    window = min(n, m + 20)
    step = max(1, m // 3)

    for i in range(0, max(1, n - window + 1), step):
        chunk = text_norm[i:i + window]
        ratio = _lcs_coverage(chunk, ctx_norm)
        if ratio > best_ratio:
            best_ratio = ratio
            if ratio >= threshold:
                best_span = (i, i + len(chunk), chunk)

    if best_ratio >= threshold:
        logger.debug(f"[grounding] LCS fuzzy match ratio={best_ratio:.2f} threshold={threshold} ctx[:30]={ctx_norm[:30]!r}")
        return best_span
    return None


def _lcs_len(a: str, b: str) -> int:
    """计算 a 与 b 的 LCS 长度。使用 O(n*m) 动态规划，滚动数组节省内存。"""
    if not a or not b:
        return 0
    la, lb = len(a), len(b)
    prev = [0] * (lb + 1)
    curr = [0] * (lb + 1)
    for i in range(1, la + 1):
        ai = a[i - 1]
        for j in range(1, lb + 1):
            if ai == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, prev
    return prev[lb]


def _lcs_ratio(a: str, b: str) -> float:
    """LCS 匹配率 = LCS_len / max(len_a, len_b)。用于衡量两串整体相似度。"""
    if not a or not b:
        return 0.0
    return _lcs_len(a, b) / max(len(a), len(b))


def _lcs_coverage(text_chunk: str, ctx: str) -> float:
    """ctx 在 text_chunk 中的 LCS 覆盖率 = LCS_len / len(ctx)。

    衡量 ctx 有多少字符被 text_chunk 按顺序匹配到，
    对 OCR 噪声（text 略长于 ctx）更合理。
    """
    if not ctx or not text_chunk:
        return 0.0
    return _lcs_len(text_chunk, ctx) / len(ctx)


def _keyphrase_match(text_norm: str, ctx_norm: str, extract: dict) -> Optional[tuple[int, int, str]]:
    """Last-resort: match by concatenated 'key phrases' from the extraction values.

    Keys used: positivity_rate, gmc_value, province, city, sample_size, age_min/max.
    """
    phrases: list[str] = []
    for key in ("positivity_rate", "gmc_value", "sample_size", "age_min", "age_max",
                "collection_year", "sample_year"):
        v = extract.get(key)
        if v is not None:
            phrases.append(str(v))
    for key in ("province", "city", "antibody_type", "population_type", "detection_method"):
        v = extract.get(key)
        if isinstance(v, str) and v.strip():
            phrases.append(v.strip())

    # try to find a region containing ALL phrases, longest-match first
    if not phrases:
        return None
    phrases_sorted = sorted(set(phrases), key=len, reverse=True)
    phrases_sorted = [p for p in phrases_sorted if len(p) >= 1][:8]
    if not phrases_sorted:
        return None

    # Collect candidate positions for every phrase, pick overlap region
    positions: list[tuple[int, int]] = []
    for p in phrases_sorted:
        idx = text_norm.find(p)
        if idx != -1:
            positions.append((idx, idx + len(p)))
    if len(positions) < 2:
        return None
    start = min(s for s, _ in positions)
    end = max(e for _, e in positions)
    if end - start > 800:
        # too spread out, skip
        return None
    # extend slightly to include context
    start = max(0, start - 10)
    end = min(len(text_norm), end + 30)
    return start, end, text_norm[start:end]


def _numeric_grounding_forms(value) -> list[str]:
    """把单个数值格式化为多种可定位的字符串形态（用于 in 匹配）。

    - 整数（如 sample_size=215）→ ["215"]
    - 小数（如 84.3）→ ["84.3", "84.3%", "84.3％", "84.3 %"]
    - 不可解析的非数值（None / 空 / 非数字）→ 返回空列表（视为无需回验）
    """
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        num = float(value)
        if num != int(num):
            s = f"{num}"
        else:
            s = str(int(num))
    else:
        text = str(value).strip()
        if not text:
            return []
        try:
            num = float(text)
        except (TypeError, ValueError):
            return []
        if num != int(num):
            s = f"{num}"
        else:
            s = str(int(num))

    forms = [s]
    # 若含小数点，补充百分比形态（英文半角 % / 中文全角 ％ / 带空格 %）
    if "." in s:
        forms += [f"{s}%", f"{s}％", f"{s} %"]
    return forms


def validate_numeric_grounding(dp: dict, text: str) -> bool:
    """数值回验：提取出的关键数值必须在原文中可定位。

    对 dp 中的 positivity_rate / gmc_value / sample_size 每个存在且非空的数值，
    格式化成多种形态（如 84.3 → ["84.3", "84.3%", "84.3％", "84.3 %"]），
    任一形态能在 dp 的 source_context 或全文 text 中被找到（简单 in 判断）即视为
    该数值 grounded。所有存在的关键数值都 grounded 才返回 True，否则 False。

    无任何待回验数值时返回 True（不因缺少数值而降级）。
    """
    if not dp:
        return True

    text = text or ""
    source_context = dp.get("source_context") or ""
    haystacks = [t for t in (source_context, text) if t]

    for key in _NUMERIC_GROUNDING_KEYS:
        forms = _numeric_grounding_forms(dp.get(key))
        if not forms:
            continue
        if not any(
            any(form in haystack for form in forms)
            for haystack in haystacks
        ):
            logger.warning(
                f"[grounding] 数值回验失败: {key}={dp.get(key)!r} 未能在原文中定位 "
                f"(forms={forms})"
            )
            return False
    return True


def ground_extraction(
    source_text: str,
    source_context: Optional[str],
    extract_item: dict,
    *,
    fuzzy_threshold: Optional[float] = None,
) -> GroundingResult:
    """Try to locate the extraction within the original source text.

    Parameters
    ----------
    source_text : str
        The full (preprocessed) source text.
    source_context : Optional[str]
        The snippet LLM claimed as evidence, e.g. 20-50 chars of original text.
    extract_item : dict
        The whole extraction record; used as fallback key-phrase anchors.
    fuzzy_threshold : Optional[float]
        A3：自定义模糊匹配阈值，None 时用全局默认 _DEFAULT_FUZZY_THRESHOLD。

    Returns
    -------
    GroundingResult with char interval over `source_text` (half-open, 0-based),
    and whether we consider it grounded.
    """
    res = GroundingResult()
    if not source_text:
        logger.warning("[grounding] source_text is empty")
        return res

    threshold = fuzzy_threshold if fuzzy_threshold is not None else _DEFAULT_FUZZY_THRESHOLD
    text_norm = _normalize_for_match(source_text)
    ctx_norm = _normalize_for_match(source_context or "")

    # Strategy 1: exact match on source_context
    exact = _exact_match(text_norm, ctx_norm, source_context or "")
    if exact is not None:
        s, e, matched = exact
        res.is_grounded = True
        res.source_char_start = s
        res.source_char_end = e
        res.matched_snippet = matched
        res.method = "exact"
        logger.info(f"[grounding] exact match @ [{s},{e}): {matched[:40]!r}")

    # Strategy 2: fuzzy match on source_context
    if not res.is_grounded:
        fuzzy = _fuzzy_match(text_norm, ctx_norm, threshold=threshold)
        if fuzzy is not None:
            s, e, matched = fuzzy
            res.is_grounded = True
            res.source_char_start = s
            res.source_char_end = e
            res.matched_snippet = matched
            res.method = "fuzzy"
            logger.info(f"[grounding] fuzzy match @ [{s},{e}): len={e-s}")

    # Strategy 3: key-phrase overlap match
    if not res.is_grounded:
        kp = _keyphrase_match(text_norm, ctx_norm, extract_item or {})
        if kp is not None:
            s, e, matched = kp
            res.is_grounded = True
            res.source_char_start = s
            res.source_char_end = e
            res.matched_snippet = matched
            res.method = "keyphrase"
            logger.info(f"[grounding] keyphrase match @ [{s},{e}): len={e-s}")

    if not res.is_grounded:
        logger.warning(
            f"[grounding] failed to locate evidence in source: "
            f"source_context[:40]={(source_context or '')[:40]!r}"
        )

    # P2-4：字符级 grounding 之后做数值回验——关键数值必须在原文中可定位。
    # 回验失败 → 标记为未 grounded + 低置信（即使字符级片段匹配上了）。
    item = extract_item if isinstance(extract_item, dict) else {}
    if not validate_numeric_grounding(item, source_text):
        res.is_grounded = False
        if isinstance(extract_item, dict):
            extract_item["is_grounded"] = False
            if "confidence" in extract_item:
                extract_item["confidence"] = "low"

    return res


# ---------------------------------------------------------------------------
# 2. Hard schema validation + province enum enforcement
# ---------------------------------------------------------------------------


@dataclass
class ValidationFlags:
    """Validation summary for a single extracted -> data_point pair.

    Used by extract_task to adjust confidence / priority in the review queue.
    """
    province_valid: bool = False
    data_type_valid: bool = False
    confidence_valid: bool = False
    review_status_valid: bool = False
    value_range_valid: bool = True
    grounded: bool = False  # not strictly schema, but used to downgrade

    @property
    def schema_issues(self) -> list[str]:
        issues: list[str] = []
        if not self.province_valid:
            issues.append("province_not_in_enum")
        if not self.data_type_valid:
            issues.append("data_type_invalid")
        if not self.confidence_valid:
            issues.append("confidence_invalid")
        if not self.review_status_valid:
            issues.append("review_status_invalid")
        if not self.value_range_valid:
            issues.append("value_out_of_range")
        return issues

    @property
    def ok(self) -> bool:
        return not self.schema_issues


def validate_province(value: Optional[str]) -> bool:
    """Hard province validation against the canonical enum list."""
    if value is None:
        # Missing is allowed (could be unknown), but we still flag
        return False
    if not isinstance(value, str):
        return False
    return value.strip() in CHINA_PROVINCE_NAMES


def validate_data_type(value: Optional[str]) -> bool:
    return value is None or (isinstance(value, str) and value in _ALLOWED_DATA_TYPES)


def validate_confidence(value: Optional[str]) -> bool:
    return value is None or (isinstance(value, str) and value in _ALLOWED_CONFIDENCE)


def validate_review_status(value: Optional[str]) -> bool:
    return value is None or (isinstance(value, str) and value in _ALLOWED_REVIEW_STATUS)


def validate_value_range(
    value: Optional[float],
    data_type: Optional[str],
    unit: Optional[str] = None,
) -> bool:
    """Range validation: positivity rates must be in [0, 100]."""
    if value is None:
        return True
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if data_type == "seroprevalence":
        return 0.0 <= v <= 100.0
    if data_type == "gmc":
        # GMC/GMT must be positive
        return v >= 0.0
    # unknown data_type: we don't know the range, trust it
    return True


def _sanitize_unreasonable_values(item: dict) -> list[str]:
    """S8：对提取数值做合理性净化，明显不可能的取值直接置 null。

    目标：即使 LLM 被恶意文献诱导输出虚假/离谱数值（如阳性率 9999%），
    也不让它进入数据库。返回检测到的问题列表（供置信度降级用）。

    处理字段：
    - positivity_rate：合理区间 [0, 100]（超出则置 null）
    - positivity_ci_lower/upper：必须是 [0, 100]，且 lower <= upper（否则置 null）
    - gmc_value：不能为负（负值无意义，置 null）
    - sample_size / age_min / age_max：不能为负（置 null）
    """
    issues: list[str] = []

    def _clamp_range(key: str, lo: float, hi: float) -> None:
        v = item.get(key)
        if v is None:
            return
        try:
            f = float(v)
        except (TypeError, ValueError):
            item[key] = None
            issues.append(f"{key}_non_numeric")
            return
        if not (lo <= f <= hi):
            item[key] = None
            issues.append(f"{key}_out_of_range")

    def _clamp_non_negative(key: str) -> None:
        v = item.get(key)
        if v is None:
            return
        try:
            f = float(v)
        except (TypeError, ValueError):
            item[key] = None
            issues.append(f"{key}_non_numeric")
            return
        if f < 0:
            item[key] = None
            issues.append(f"{key}_negative")

    _clamp_range("positivity_rate", 0.0, 100.0)
    _clamp_range("positivity_ci_lower", 0.0, 100.0)
    _clamp_range("positivity_ci_upper", 0.0, 100.0)
    _clamp_non_negative("gmc_value")
    _clamp_non_negative("sample_size")
    _clamp_non_negative("age_min")
    _clamp_non_negative("age_max")

    # CI 上下限顺序校验与净化
    lo, hi = item.get("positivity_ci_lower"), item.get("positivity_ci_upper")
    if lo is not None and hi is not None and hi < lo:
        item["positivity_ci_lower"] = None
        item["positivity_ci_upper"] = None
        issues.append("ci_lower_greater_than_upper")

    return issues


def validate_extraction_schema(
    extract_item: dict,
    grounded: bool,
) -> tuple[dict, ValidationFlags]:
    """Apply schema validation rules to one LLM extraction.

    Returns
    -------
    (cleaned_item, flags)
        cleaned_item: copy of extract_item with normalized enum values
        flags: summary of what passed / failed
    """
    item = dict(extract_item or {})
    flags = ValidationFlags(grounded=grounded)

    # --- province: hard enum, reject non-matching, keep raw in _raw_province for debug
    raw_province = item.get("province")
    item["_raw_province"] = raw_province
    flags.province_valid = validate_province(raw_province)
    if not flags.province_valid and raw_province is not None:
        # Keep normalized version if possible, but flag the issue
        from app.core.term_normalizer import normalize_province
        norm = normalize_province(raw_province)
        if norm in CHINA_PROVINCE_NAMES:
            item["province"] = norm
            flags.province_valid = True
            logger.info(
                f"[validation] province post-normalized from {raw_province!r} -> {norm!r}"
            )
        else:
            logger.warning(
                f"[validation] province {raw_province!r} not in enum; keeping raw but flagging low confidence"
            )

    # --- data_type: we don't actually get this from LLM (sero/gmc is decided
    #     later by which value is present). Skip direct check here, we check
    #     in the data_point level.
    flags.data_type_valid = True

    # --- value ranges + S8 合理性净化：明显不可能的值直接置 null，防止恶意文献诱导输出虚假数据
    pr_ok = validate_value_range(item.get("positivity_rate"), "seroprevalence")
    gmc_ok = validate_value_range(item.get("gmc_value"), "gmc")
    _issues = _sanitize_unreasonable_values(item)
    flags.value_range_valid = (pr_ok and gmc_ok and "value_out_of_range" not in _issues)
    if not flags.value_range_valid:
        logger.warning(
            f"[validation] value out of range / unreasonable: "
            f"positivity_rate={item.get('positivity_rate')!r} "
            f"gmc_value={item.get('gmc_value')!r} "
            f"sample_size={item.get('sample_size')!r} issues={_issues}"
        )

    # --- confidence / review_status: defaults are set at DataPoint level
    flags.confidence_valid = True
    flags.review_status_valid = True

    return item, flags

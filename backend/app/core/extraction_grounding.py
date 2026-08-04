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


def _fuzzy_match(text_norm: str, ctx_norm: str) -> Optional[tuple[int, int, str]]:
    """Fuzzy match using difflib.SequenceMatcher for OCR-like noisy differences."""
    if not ctx_norm or len(ctx_norm) < 6:
        return None
    # Sliding window over the text with ratio threshold
    window = max(len(ctx_norm) + 20, 30)
    step = max(1, len(ctx_norm) // 2)
    best_ratio = 0.0
    best_span: Optional[tuple[int, int, str]] = None
    for i in range(0, max(1, len(text_norm) - window + 1), step):
        chunk = text_norm[i:i + window]
        ratio = difflib.SequenceMatcher(None, chunk, ctx_norm).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            if ratio >= 0.78:
                best_span = (i, i + len(chunk), chunk)
    if best_ratio >= 0.78:
        logger.debug(f"[grounding] fuzzy match ratio={best_ratio:.2f} ctx[:30]={ctx_norm[:30]!r}")
        return best_span
    return None


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


def ground_extraction(
    source_text: str,
    source_context: Optional[str],
    extract_item: dict,
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

    Returns
    -------
    GroundingResult with char interval over `source_text` (half-open, 0-based),
    and whether we consider it grounded.
    """
    res = GroundingResult()
    if not source_text:
        logger.warning("[grounding] source_text is empty")
        return res

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
        return res

    # Strategy 2: fuzzy match on source_context
    fuzzy = _fuzzy_match(text_norm, ctx_norm)
    if fuzzy is not None:
        s, e, matched = fuzzy
        res.is_grounded = True
        res.source_char_start = s
        res.source_char_end = e
        res.matched_snippet = matched
        res.method = "fuzzy"
        logger.info(f"[grounding] fuzzy match @ [{s},{e}): len={e-s}")
        return res

    # Strategy 3: key-phrase overlap match
    kp = _keyphrase_match(text_norm, ctx_norm, extract_item or {})
    if kp is not None:
        s, e, matched = kp
        res.is_grounded = True
        res.source_char_start = s
        res.source_char_end = e
        res.matched_snippet = matched
        res.method = "keyphrase"
        logger.info(f"[grounding] keyphrase match @ [{s},{e}): len={e-s}")
        return res

    logger.warning(
        f"[grounding] failed to locate evidence in source: "
        f"source_context[:40]={(source_context or '')[:40]!r}"
    )
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

    # --- value ranges
    pr_ok = validate_value_range(item.get("positivity_rate"), "seroprevalence")
    gmc_ok = validate_value_range(item.get("gmc_value"), "gmc")
    flags.value_range_valid = pr_ok and gmc_ok
    if not flags.value_range_valid:
        logger.warning(
            f"[validation] value out of range: "
            f"positivity_rate={item.get('positivity_rate')!r} "
            f"gmc_value={item.get('gmc_value')!r}"
        )

    # --- confidence / review_status: defaults are set at DataPoint level
    flags.confidence_valid = True
    flags.review_status_valid = True

    return item, flags

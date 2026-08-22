"""兼容层：原 app.core.llm_extractor 已拆分为 app.core.extraction 包。

此处仅为向后兼容保留，所有实现已迁移至 app.core.extraction 子模块。
`from app.core.llm_extractor import LLMExtractor` 及模块级常量仍可用。
"""

from app.core.extraction import (  # noqa: F401
    EXTRACTION_JSON_SCHEMA,
    LLMExtractor,
    PROMPT_EN,
    PROMPT_ZH,
    PROVINCE_LIST_EN,
    PROVINCE_LIST_TIP,
    SYSTEM_PROMPT_ZH,
    _classify_llm_error,
    _is_connection_error,
    _parse_titer_cell,
)

__all__ = [
    "LLMExtractor",
    "EXTRACTION_JSON_SCHEMA",
    "PROMPT_EN",
    "PROMPT_ZH",
    "PROVINCE_LIST_EN",
    "PROVINCE_LIST_TIP",
    "SYSTEM_PROMPT_ZH",
    "_classify_llm_error",
    "_is_connection_error",
    "_parse_titer_cell",
]

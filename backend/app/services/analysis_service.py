"""兼容层：将所有公开符号 re-export 自 app.services.analysis，保持 `from app.services.analysis_service import ...` 语义不变。"""
from app.services.analysis import *  # noqa: F403

# 私有函数与常量 re-export（供测试文件直接导入，保持向后兼容）
from app.services.analysis._common import (  # noqa: F401
    DEFAULT_LIFE_EXPECTANCY,
    NIP_COVERAGE_REFERENCE,
    R0_REFERENCE,
    _build_base_query,
    _calc_foi_from_sp,
    _calc_hit_from_r0,
    _calc_r0_from_foi,
    _calc_ve_from_sp,
    _catalytic_r0_hit,
    _get_reference_coverage,
    _implied_coverage_from_hit,
    _midpoint_age,
    _resolve_hit_target,
    _split_vax_unvax,
)

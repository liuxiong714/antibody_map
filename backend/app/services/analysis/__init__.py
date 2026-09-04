"""app.services.analysis 分析服务子包。

包含七个分析子模块（basic / meta / infectious_disease / spatial /
equity_quality / data_management / export），公共常量与辅助函数集中
于 ``_common``。

同时把子模块的公开顶层函数 re-export 到包级，使兼容层
``app.services.analysis_service``（``from app.services.analysis import *``）
能直接暴露 ``get_summary``、``get_trend`` 等 API。
"""

from app.services.analysis import (
    basic,
    data_management,
    equity_quality,
    export,
    infectious_disease,
    meta,
    spatial,
)

# 公开 API 函数（供 app.api.v1.analysis 经 analysis_service 调用）
from app.services.analysis.basic import (
    get_age_curve,
    get_age_stratify,
    get_birth_cohort,
    get_region_compare,
    get_summary,
    get_trend,
)
from app.services.analysis.data_management import (
    get_approved_data_points,
    get_approved_data_points_for_snapshot,
    get_data_gap_analysis,
)
from app.services.analysis.equity_quality import (
    get_coverage_review_stats,
    get_equity_analysis,
    get_goal_tracking,
    get_quality_assessment,
)
from app.services.analysis.infectious_disease import (
    get_barrier_probability,
    get_effective_barrier,
    get_foi_analysis,
    get_immune_barrier_assessment,
    get_immunity_projection,
    get_simulation,
    get_vaccine_analysis,
)
from app.services.analysis.meta import (
    get_assay_heterogeneity,
    get_meta_analysis,
    get_meta_merge,
)
from app.services.analysis.spatial import (
    get_spatial_hotspots,
)

__all__ = [
    "basic",
    "data_management",
    "equity_quality",
    "export",
    "get_age_curve",
    "get_age_stratify",
    "get_approved_data_points",
    "get_approved_data_points_for_snapshot",
    "get_assay_heterogeneity",
    "get_barrier_probability",
    "get_birth_cohort",
    "get_coverage_review_stats",
    "get_data_gap_analysis",
    "get_effective_barrier",
    "get_equity_analysis",
    "get_foi_analysis",
    "get_goal_tracking",
    "get_immune_barrier_assessment",
    "get_immunity_projection",
    "get_meta_analysis",
    "get_meta_merge",
    "get_quality_assessment",
    "get_region_compare",
    "get_simulation",
    "get_spatial_hotspots",
    "get_summary",
    # 子模块公共函数
    "get_trend",
    "get_vaccine_analysis",
    "infectious_disease",
    "meta",
    "spatial",
]

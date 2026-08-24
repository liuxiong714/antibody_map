"""app.services.analysis 分析服务子包。

包含七个分析子模块（basic / meta / infectious_disease / spatial /
equity_quality / data_management / export），公共常量与辅助函数集中
于 ``_common``。

同时把子模块的公开顶层函数 re-export 到包级，使兼容层
``app.services.analysis_service``（``from app.services.analysis import *``）
能直接暴露 ``get_summary``、``get_trend`` 等 API。
"""

from app.services.analysis import (  # noqa: E402
    basic,
    meta,
    infectious_disease,
    spatial,
    equity_quality,
    data_management,
    export,
)

# 公开 API 函数（供 app.api.v1.analysis 经 analysis_service 调用）
from app.services.analysis.basic import (  # noqa: E402,F401
    get_trend,
    get_region_compare,
    get_age_curve,
    get_birth_cohort,
    get_age_stratify,
    get_summary,
)
from app.services.analysis.meta import (  # noqa: E402,F401
    get_meta_merge,
    get_meta_analysis,
    get_assay_heterogeneity,
)
from app.services.analysis.infectious_disease import (  # noqa: E402,F401
    get_simulation,
    get_immune_barrier_assessment,
    get_foi_analysis,
    get_vaccine_analysis,
)
from app.services.analysis.spatial import (  # noqa: E402,F401
    get_spatial_hotspots,
)
from app.services.analysis.equity_quality import (  # noqa: E402,F401
    get_equity_analysis,
    get_quality_assessment,
    get_goal_tracking,
    get_coverage_review_stats,
)
from app.services.analysis.data_management import (  # noqa: E402,F401
    get_approved_data_points,
    get_approved_data_points_for_snapshot,
    get_data_gap_analysis,
)

__all__ = [
    "basic",
    "meta",
    "infectious_disease",
    "spatial",
    "equity_quality",
    "data_management",
    "export",
    # 子模块公共函数
    "get_trend",
    "get_region_compare",
    "get_age_curve",
    "get_birth_cohort",
    "get_age_stratify",
    "get_summary",
    "get_meta_merge",
    "get_meta_analysis",
    "get_assay_heterogeneity",
    "get_simulation",
    "get_immune_barrier_assessment",
    "get_foi_analysis",
    "get_vaccine_analysis",
    "get_spatial_hotspots",
    "get_equity_analysis",
    "get_quality_assessment",
    "get_goal_tracking",
    "get_coverage_review_stats",
    "get_approved_data_points",
    "get_approved_data_points_for_snapshot",
    "get_data_gap_analysis",
]
"""分析模块 Pydantic 响应结构（省间公平性分析等）。"""

from typing import Optional

from pydantic import BaseModel


class ProvinceEquityRow(BaseModel):
    """单个省份的公平性指标（Top/Bottom 排名与全量排行共用）。"""

    rank: Optional[int] = None  # 优先按年龄标化阳性率降序排名；无有效数据时为 None
    province: str = ""
    weighted_positivity: Optional[float] = None  # 加权阳性率（%，逆方差合并）
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    asr: Optional[float] = None  # 年龄标化阳性率（%，直接法，七普标准人口）；无有效分层时 None
    asr_ci_lower: Optional[float] = None
    asr_ci_upper: Optional[float] = None
    is_age_standardized: bool = False  # 排名是否基于年龄标化率（True）或回落加权率（False）
    n_strata: int = 0  # 参与标化的有效年龄分层数
    total_samples: int = 0
    n_studies: int = 0
    is_meeting_target: Optional[bool] = None  # 是否达到 WHO 免疫屏障阈值；无阈值时为 None


class EquitySummary(BaseModel):
    """省间公平性汇总指标。"""

    gini: Optional[float] = None  # 省间基尼系数
    coefficient_of_variation: Optional[float] = None  # 省间变异系数
    best_province: Optional[str] = None
    best_positivity: Optional[float] = None
    worst_province: Optional[str] = None
    worst_positivity: Optional[float] = None
    target_threshold_percent: Optional[float] = None  # WHO 达标阈值（%）
    meeting_ratio: Optional[float] = None  # 达标省占比（0-1）
    meeting_provinces_count: int = 0
    total_provinces: int = 0  # 有有效阳性率的省数


class EquityAnalysisResponse(BaseModel):
    """省间公平性分析响应（作为 ApiResponse.data 的载荷）。"""

    disease: Optional[str] = None
    n_provinces: int = 0
    n_data_points: int = 0
    summary: EquitySummary = EquitySummary()
    top_provinces: list[ProvinceEquityRow] = []
    bottom_provinces: list[ProvinceEquityRow] = []
    province_rows: list[ProvinceEquityRow] = []
    notes: list[str] = []


class CoverageReviewDisease(BaseModel):
    """单个疾病的审核状态统计（数据点 / 样本量 / 通过率）。"""

    disease: str = ""
    total_points: int = 0
    total_samples: int = 0
    approved_points: int = 0
    approved_samples: int = 0
    pending_points: int = 0
    pending_samples: int = 0
    rejected_points: int = 0
    rejected_samples: int = 0
    approval_rate: float = 0.0  # 通过率 = approved_points / total_points（0-1）


class CoverageReviewOverview(BaseModel):
    """审核状态统计的总体概览。"""

    total_diseases: int = 0
    total_points: int = 0
    total_samples: int = 0
    approved_points: int = 0
    pending_points: int = 0
    rejected_points: int = 0
    overall_approval_rate: float = 0.0  # 总体通过率（0-1）


class CoverageReviewResult(BaseModel):
    """按疾病维度的审核状态统计响应（作为 ApiResponse.data 的载荷）。"""

    overview: CoverageReviewOverview = CoverageReviewOverview()
    diseases: list[CoverageReviewDisease] = []

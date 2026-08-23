export type DiseaseKey =
  | 'measles' | 'mumps' | 'rubella' | 'pertussis' | 'diphtheria'
  | 'tetanus' | 'hepatitis_b' | 'hepatitis_a' | 'polio'
  | 'influenza' | 'covid19' | 'meningitis' | 'varicella' | 'hfmd' | 'rotavirus';

export interface Literature {
  id: string;
  title: string;
  title_en: string | null;
  authors: string | null;
  journal: string | null;
  pub_year: number | null;
  doi: string | null;
  pmid: string | null;
  abstract: string | null;
  keywords: string[] | null;
  region: string | null;
  province: string | null;
  publication_types: string[] | null;
  source_db: string | null;
  file_path: string | null;
  pdf_hash: string | null;
  has_fulltext: boolean;
  file_format: string | null;
  extraction_status: string;
  extracted_count: number;
  approved_count: number;
  // LLM 提取的 token 用量与费用统计
  llm_model_used?: string | null;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  llm_cost_usd?: number | null;
  llm_call_count?: number;
  llm_usage_detail?: Record<string, {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    call_count: number;
  }> | null;
  tags?: Array<{ id: string; name: string; color: string }>;
  created_at: string;
  updated_at: string;
}

// AI 提取状态查询结果（含 token 用量）
export interface ExtractionStatusWithUsage {
  literature_id: string;
  status: string;
  extracted_count: number;
  approved_count: number;
  data_point_count: number;
  llm_model_used: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  llm_cost_usd: number;
  llm_call_count: number;
  llm_usage_detail: Record<string, {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    call_count: number;
  }> | null;
}

export interface DataPoint {
  id: string;
  literature_id: string;
  disease: string | null;
  region: string | null;
  province: string | null;
  city: string | null;
  data_type: string | null;
  value: number | null;
  unit: string | null;
  ci_lower: number | null;
  ci_upper: number | null;
  sample_size: number | null;
  method: string | null;
  assay: string | null;
  population: string | null;
  age_min: number | null;
  age_max: number | null;
  collection_year: number | null;
  confidence: string;
  review_status: string;
  // 数据点审核：审核意见、审核人、审核时间
  review_comment?: string | null;
  reviewer_id?: string | null;
  reviewer_name?: string | null;
  reviewed_at?: string | null;
  // 质量分级（审核通过后异步打分写入；breakdown 为元数据级实时明细）
  quality_score?: number | null;
  quality_grade?: string | null;
  estimate_grade?: string | null;
  quality_breakdown?: Record<string, { score: number; label: string; max?: number }> | null;
  source_context: string | null;
  source_page: number | null;
  // P0 新增：精确字符级溯源字段
  source_char_start: number | null;
  source_char_end: number | null;
  is_grounded: boolean;
  created_at: string;
  updated_at: string;
}

// ===== 查重与合并相关类型 =====

export interface DuplicateMatchItem {
  literature: Literature;
  match_reasons: string[];
  match_values: Record<string, string>;
}

export interface CheckDuplicateResult {
  literature_id: string | null;
  total: number;
  duplicates: DuplicateMatchItem[];
}

export interface DuplicateGroup {
  literature_ids: string[];
  match_reasons: string[];
  representative_id: string;
}

export interface ScanDuplicatesResult {
  groups: DuplicateGroup[];
  total_groups: number;
  total_duplicates: number;
}

export interface FieldComparison {
  field: string;
  source_value: unknown;
  target_value: unknown;
  differs: boolean;
}

export interface DataPointConflictItem {
  source_dp: Record<string, unknown>;
  target_dp: Record<string, unknown>;
  key: string;
}

export interface MergePreviewResult {
  field_comparison: FieldComparison[];
  source_data_point_count: number;
  target_data_point_count: number;
  conflicts: DataPointConflictItem[];
  total_conflicts: number;
}

export type MergeFieldChoice = 'source' | 'target' | 'merge';
export type DpConflictStrategy = 'keep_both' | 'prefer_target' | 'prefer_source';

export interface MergeRequestPayload {
  source_id: string;
  target_id: string;
  field_choices: Record<string, MergeFieldChoice>;
  dp_conflict_strategy: DpConflictStrategy;
}

export interface MergeResult {
  merged_literature: Literature;
  moved_data_points: number;
  deleted_conflict_data_points: number;
  deleted_source_id: string;
}

export interface MapDataPoint {
  province?: string;
  city?: string;
  /** 疾病名称（未指定疾病筛选时返回，用于区分不同疾病的聚合数据） */
  disease?: string;
  point_count: number;
  study_count: number;
  total_sample: number;
  weighted_positivity: number | null;
  /** 城市级坐标（地图下钻散点图用） */
  latitude?: number | null;
  longitude?: number | null;
}

export interface YearlyMapData {
  year: number;
  data: MapDataPoint[];
}

export interface ApiResponse<T = unknown> {
  success: boolean;
  message: string;
  data: T;
  meta: Record<string, unknown> | null;
}

export interface PagedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ExtractionStatus {
  literature_id: string;
  status: string;
  extracted_count: number;
  approved_count: number;
  data_point_count: number;
}

export interface ReportData {
  id?: string;
  title: string;
  content: string;
  report_type: string;
  literature_count: number;
  data_point_count: number;
  language: string;
  llm_model?: string;
  task_type?: string;
  task_time?: string;
  task_location?: string;
  personnel_count?: number;
  personnel_gender?: string;
  personnel_age?: string;
  personnel_vaccination_history?: string;
  generated_at: string;
}


export interface ReportRecord {
  id: string;
  title: string;
  report_type: string;
  disease: string | null;
  province: string | null;
  data_type: string | null;
  language: string;
  llm_model?: string;
  task_type?: string;
  task_time?: string;
  task_location?: string;
  personnel_count?: number;
  generated_at: string;
  content?: string;
}

// ===== 报告模板 =====

export interface ReportSection {
  title: string;
  type: 'text' | 'chart' | 'table' | 'kpi';
  content_template?: string;
  order: number;
  analysis?: 'trend' | 'region' | 'age_curve' | 'disease';
  data?: 'province' | 'year' | 'age' | 'disease';
  kpi?: string[];
}

export interface ReportTemplate {
  id: string;
  name: string;
  report_type: 'antibody_analysis' | 'vaccination_strategy' | 'immune_barrier_assessment';
  sections: ReportSection[];
  is_default: boolean;
  desc?: string | null;
  created_at: string;
  updated_at: string;
}

// ===== 远程模型配置 =====

export interface ApiModelConfig {
  id: string;
  name: string;
  model_name: string;
  api_key: string;
  base_url: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LocalModelConfig {
  id: string;
  name: string;
  model_name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ModelOption {
  value: string;
  label: string;
  group: 'local' | 'remote';
  is_default?: boolean;
}

export interface ModelsListData {
  local: ModelOption[];
  remote: ModelOption[];
}
// ===== 催化模型族（MLE 拟合 + 模型比较） =====

export interface CatalyticModel {
  name: string;
  label: string;
  k_params: number;
  /** 参数 MLE 估计 + 95%CI（键为 lambda / mu / lambda1 / lambda2 等及对应 _ci_lower/_ci_upper） */
  params: Record<string, number | null>;
  loglik: number | null;
  aic: number | null;
  bic: number | null;
  delta_aic: number | null;
  akaike_weight: number | null;
  converged: boolean;
}

export interface CatalyticLRT {
  pair: string;
  chisq: number;
  df: number;
  p_value: number;
}

export interface CatalyticCurvePoint {
  age: number;
  prevalence: number;
}

export interface ImmuneBarrierData {
  disease: string;
  who_threshold: number | null;
  r0_reference?: {
    typical: number | null;
    range_low: number | null;
    range_high: number | null;
  };
  summary: {
    total_data_points: number;
    total_literatures: number;
    total_samples: number;
    weighted_positivity_rate: number | null;
    weighted_avg_foi_per_year?: number | null;
    estimated_r0_from_foi?: number | null;
    hit_from_foi_percent?: number | null;
    hit_from_reference_r0_percent?: number | null;
    hit_target_used_percent?: number | null;
    hit_target_source?: string;
    // 催化模型族 MLE 拟合 + 模型比较（新）
    models?: CatalyticModel[];
    recommended_model?: string | null;
    recommended_params?: Record<string, number | null> | null;
    fitted_curve?: CatalyticCurvePoint[];
    modeling_notes?: string[];
    r0_assumption_note?: string | null;
    n_catalytic_records?: number;
    catalytic_age_range?: [number | null, number | null];
  };
  yearly_trend: Array<{ year: number; weighted_positivity: number | null; sample_size: number; point_count: number }>;
  age_groups?: Array<{
    age_group: string;
    age_range: [number, number];
    data_point_count: number;
    total_samples: number;
    weighted_positivity_rate: number | null;
    weighted_avg_foi_per_year: number | null;
    status: string;
  }>;
  province_matrix?: Array<{
    province: string;
    data_point_count: number;
    total_samples: number;
    weighted_positivity_rate: number | null;
    weighted_avg_foi_per_year: number | null;
    estimated_r0_from_foi: number | null;
    hit_target_percent: number | null;
    status: string;
  }>;
  status: string;
  assessment: string;
}

// ===== 数据覆盖度分析 =====

export interface DataGapOverview {
  total_data_points: number;
  total_provinces: number;
  total_cities: number;
  total_diseases: number;
  year_range: [number, number] | null;
  years: number[];
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  total_gap_combos: number;
  combo_status_counts?: Record<string, number>;
  well_covered_threshold?: number;
}

export type CoverageStatus = 'well_covered' | 'need_review' | 'need_supplement' | 'need_both';

export interface ReviewNeededItem {
  province: string;
  year: number | null;
  disease: string;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  total_count: number;
  completeness_score?: number;
  status?: CoverageStatus;
}

export interface SupplementNeededItem {
  province: string;
  year: number | null;
  disease: string;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  total_count: number;
  completeness_score?: number;
  status?: CoverageStatus;
}

export interface DataGapItem {
  disease: string;
  covered_provinces: string[];
  missing_provinces: string[];
  covered_count: number;
  missing_count: number;
  /** 覆盖完整度 0-100，covered_count / 中国省份总数 × 100（P0+ 分析模块新增） */
  coverage_percent?: number;
}

export interface ProvinceYearCell {
  total: number;
  pending: number;
  approved: number;
  completeness_score?: number;
  status?: CoverageStatus;
}

export interface ProvinceYearRow {
  province: string;
  years: Record<string, ProvinceYearCell>;
  total: number;
  pending: number;
  approved?: number;
  completeness_score?: number;
  status?: CoverageStatus;
}

export interface CityYearRow {
  province: string;
  city: string;
  years: Record<string, ProvinceYearCell>;
  total: number;
  pending: number;
  approved?: number;
  completeness_score?: number;
  status?: CoverageStatus;
}

export interface DataGapAnalysisResult {
  overview: DataGapOverview;
  review_needed: ReviewNeededItem[];
  supplement_needed: SupplementNeededItem[];
  data_gaps: DataGapItem[];
  province_year_matrix: ProvinceYearRow[];
  city_year_matrix: CityYearRow[];
}

// ===== 文件夹监控 =====

export interface MonitoredFolder {
  id: string;
  name: string;
  folder_path: string;
  enabled: boolean;
  scan_interval_seconds: number;
  file_extensions: string | null;
  auto_extract: boolean;
  extraction_model: string | null;
  extraction_api_key: string | null;
  extraction_base_url: string | null;
  last_scan_at: string | null;
  last_scan_new_count: number;
  total_imported_count: number;
  status: string;  // idle / scanning / error
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface MonitoredFolderCreate {
  name: string;
  folder_path: string;
  enabled?: boolean;
  scan_interval_seconds?: number;
  file_extensions?: string | null;
  auto_extract?: boolean;
  extraction_model?: string | null;
  extraction_api_key?: string | null;
  extraction_base_url?: string | null;
}

export interface MonitoredFile {
  id: string;
  folder_id: string;
  file_path: string;
  file_name: string;
  file_hash: string | null;
  file_size: number | null;
  file_mtime: string | null;
  status: string;  // pending / imported / skipped_duplicate / failed
  literature_id: string | null;
  error_message: string | null;
  imported_at: string | null;
  created_at: string;
}

export interface ScanResult {
  scanned: number;
  imported: number;
  skipped: number;
  failed: number;
}

// ===== FOI（感染力）+ 群体免疫阈值分析 =====

export interface FoiAgeGroupRow {
  age_group: string;
  age_mid_approx: number;
  data_point_count: number;
  total_samples: number;
  weighted_positivity_rate: number | null;
  weighted_avg_foi_per_year: number | null;
}

export interface FoiDiseaseSummary {
  disease: string;
  total_data_points: number;
  overall_weighted_positivity_rate: number | null;
  weighted_avg_foi_per_year: number | null;
  estimated_r0_from_foi: number | null;
  r0_reference: {
    typical: number | null;
    range_low: number | null;
    range_high: number | null;
  };
  hit_from_foi_percent: number | null;
  hit_from_reference_r0_percent: number | null;
  who_threshold_percent: number | null;
  hit_target_used_percent: number | null;
  herd_immunity_status: 'reached' | 'near' | 'not_reached' | 'undetermined' | 'no_data';
  life_expectancy_used: number;
}

export interface FoiProvinceMatrixRow {
  disease: string;
  province: string;
  data_point_count: number;
  total_samples: number;
  weighted_positivity_rate: number | null;
  weighted_avg_foi_per_year: number | null;
  herd_immunity_status: 'reached' | 'near' | 'not_reached' | 'undetermined' | 'no_data';
  hit_target_percent: number | null;
}

export interface FoiPerDiseaseResult {
  disease: string;
  summary: FoiDiseaseSummary;
  foi_by_age_group: FoiAgeGroupRow[];
}

export interface FoiHerdImmunityResult {
  disease: string | null;
  total_data_points: number;
  per_disease_results: FoiPerDiseaseResult[];
  summary: FoiDiseaseSummary | {
    num_diseases_analyzed: number;
    diseases: string[];
  };
  province_foi_matrix: FoiProvinceMatrixRow[];
  notes: string[];
}

// ===== 疫苗效果 (VE) + 接种率分析 =====

export interface VeResult {
  vaxxed_points: number;
  unvaxxed_points: number;
  vaxxed_total_samples: number;
  unvaxxed_total_samples: number;
  vaxxed_weighted_sp: number | null;
  unvaxxed_weighted_sp: number | null;
  ve_infection_percent: number | null;
  interpretation: string | null;
}

export interface VaccineCoverageInfo {
  nip_reference_national_percent: number | null;
  implied_from_seroprevalence_percent: number | null;
}

export interface VaccinePerDiseaseResult {
  disease: string;
  total_data_points: number;
  overall_weighted_sp: number | null;
  herd_immunity_target_percent: number | null;
  reference_r0_typical: number | null;
  ve_result: VeResult | null;
  coverage: VaccineCoverageInfo;
}

export interface VaccineProvinceMatrixRow {
  disease: string;
  province: string;
  data_point_count: number;
  weighted_sp_percent: number | null;
  ve_infection_percent: number | null;
  nip_reference_coverage_percent: number | null;
  implied_coverage_from_sp_percent: number | null;
  coverage_status: 'on_track' | 'near' | 'below' | 'undetermined';
}

export interface VaccineEffectivenessCoverageResult {
  disease: string | null;
  province: string | null;
  total_data_points: number;
  per_disease_results: VaccinePerDiseaseResult[];
  province_coverage_matrix: VaccineProvinceMatrixRow[];
  summary: VaccinePerDiseaseResult | {
    num_diseases_analyzed: number;
    diseases: string[];
  };
  notes: string[];
}

// ===== 分析模块新增接口（公平性 / 数据质量 / 目标达成 / 年龄曲线 / meta / assay / 模拟）=====

export interface EquityProvinceRow {
  rank: number | null;
  province: string;
  weighted_positivity: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  total_samples: number;
  n_studies: number;
  is_meeting_target: boolean | null;
}

export interface EquityAnalysisResponse {
  disease: string | null;
  n_provinces: number;
  n_data_points: number;
  summary: {
    gini: number | null;
    coefficient_of_variation: number | null;
    best_province: string | null;
    best_positivity: number | null;
    worst_province: string | null;
    worst_positivity: number | null;
    target_threshold_percent: number | null;
    meeting_ratio: number | null;
    meeting_provinces_count: number;
    total_provinces: number;
  };
  top_provinces: EquityProvinceRow[];
  bottom_provinces: EquityProvinceRow[];
  province_rows: EquityProvinceRow[];
  notes: string[];
}

export interface QualityGradeCounts {
  A: number;
  B: number;
  C: number;
  D: number;
}

export interface QualityProvinceRow {
  province: string;
  n_estimates: number;
  high_quality_ratio: number;
  with_ci_ratio: number;
  grounded_ratio: number;
  grades: QualityGradeCounts;
  is_single_estimate: boolean;
}

export interface QualityAssessmentResponse {
  disease: string | null;
  province: string | null;
  year_start: number | null;
  year_end: number | null;
  total_estimates: number;
  n_provinces: number;
  summary: {
    high_quality_ratio: number;
    grade_a_ratio: number;
    grade_b_ratio: number;
    grade_c_ratio: number;
    grade_d_ratio: number;
    with_ci_ratio: number;
    grounded_ratio: number;
  };
  grade_distribution: QualityGradeCounts;
  provinces: QualityProvinceRow[];
  single_estimate_provinces: string[];
  notes: string[];
}

export interface GoalTrackingYearRow {
  year: number;
  national_positivity: number | null;
  national_ci_lower: number | null;
  national_ci_upper: number | null;
  n_provinces: number;
  meeting_provinces: number;
  meeting_ratio: number;
  gap_to_hit: number | null;
}

export interface GoalTrackingResponse {
  disease: string | null;
  goal_threshold_percent: number | null;
  n_provinces: number;
  years: GoalTrackingYearRow[];
  latest_year: number | null;
  latest_gap_to_hit: number | null;
  notes: string[];
}

export interface AgeCurvePoint {
  age_mid: number;
  x: number;
  n: number;
  prevalence: number;
}

export interface AgeCurveCurvePoint {
  age: number;
  prevalence: number;
  ci_lower: number;
  ci_upper: number;
}

export interface AgeCurveFoiPoint {
  age: number;
  foi: number | null;
}

export interface AgeCurveMeta {
  covarage_warning: boolean;
  dropped_points: number;
  lambda_smooth: number | null;
  monotonic_violation: boolean | null;
}

export interface AgeCurveResponse {
  disease: string | null;
  province: string | null;
  n_points: number;
  curve: AgeCurveCurvePoint[];
  points: AgeCurvePoint[];
  foi_curve: AgeCurveFoiPoint[];
  meta: AgeCurveMeta;
}

export interface MetaStudyItem {
  literature_title: string;
  collection_year: number | null;
  sample_size: number | null;
  value: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  assay: string | null;
}

export type HeterogeneityLevel = 'low' | 'moderate' | 'high' | 'n/a';

export interface MetaMergeProvinceResult {
  province: string;
  k: number;
  pooled_fixed_percent: number | null;
  pooled_random_percent: number | null;
  i_squared_percent: number;
  q_statistic: number | null;
  tau_squared: number | null;
  heterogeneity: HeterogeneityLevel;
  studies: MetaStudyItem[];
}

export interface MetaMergeResponse {
  disease: string | null;
  province: string | null;
  n_provinces: number;
  results: MetaMergeProvinceResult[];
  notes: string[];
}

// ===== 多文献 Meta 分析 /analysis/meta-analysis =====

export interface MetaAnalysisStudy {
  label: string;          // 研究标签（标题 年份）
  x: number;              // 阳性数
  n: number;              // 样本量
  p: number;              // 阳性率（0-1 比例）
  weight: number;         // 主模型权重(%)
  t: number;              // FT 变换效应量
  se: number;
  sqrt_n: number;
}

export interface MetaAnalysisPooled {
  rate: number | null;    // 合并率（%）
  ci_lower: number | null;
  ci_upper: number | null;
  model: string | null;   // 'random' | 'fixed' | 'single_study'
  tau2: number;
  tau2_se: number | null;
  Q: number;
  Q_p: number | null;
  I2: number;
  k: number;
  se: number | null;
  n_rep?: number | null;
}

export interface MetaFunnelPoint {
  t: number;
  sqrt_n: number;
}

export interface MetaEggerTest {
  intercept: number;
  p_value: number;
  note?: string;
}

export interface MetaAnalysisGroup {
  group: string;
  n_studies: number;
  meta: {
    per_study: MetaAnalysisStudy[];
    pooled: MetaAnalysisPooled;
    funnel: MetaFunnelPoint[] | null;
    egger: MetaEggerTest | null;
    primary_model: string | null;
    notes: string[];
  };
}

export interface MetaAnalysisResponse {
  disease: string | null;
  group_by: string | null;
  groups: MetaAnalysisGroup[];
  q_between: {
    Q_between: number;
    df: number;
    p_value: number;
    Q_total: number;
    Q_within: number;
  } | null;
  notes: string[];
}

// ===== 出生队列分析 /analysis/birth-cohort =====

export interface BirthCohortSeriesPoint {
  year: number;
  rate: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  n: number;
}

export interface BirthCohortGroup {
  birth_year_band: string;
  series: BirthCohortSeriesPoint[];
}

export interface BirthCohortResponse {
  disease: string | null;
  province: string | null;
  year_start: number | null;
  year_end: number | null;
  cohorts: BirthCohortGroup[];
  matrix: (number | null)[][];
  x_years: number[];
  y_bands: string[];
  disease_note: string | null;
  meta: {
    n_records: number;
    dropped: number;
    min_cell_points: number;
    method: string;
  };
}

export interface AssayHeterogeneityRow {
  assay: string;
  n_studies: number;
  total_samples: number;
  weighted_positivity: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
}

export interface AssayHeterogeneityResponse {
  disease: string | null;
  province: string | null;
  n_assays: number;
  results: AssayHeterogeneityRow[];
  pooled_all_percent: number | null;
  pooled_all_ci_lower: number | null;
  pooled_all_ci_upper: number | null;
  across_assay_i_squared_percent: number;
  across_assay_q_statistic: number | null;
  across_assay_k: number;
  notes: string[];
}

/** 空间热点/冷点分类：99/95/90% 置信热点（hot_*）、冷点（cold_*）、不显著（ns） */
export type HotspotCluster =
  | 'hot_99' | 'hot_95' | 'hot_90'
  | 'cold_99' | 'cold_95' | 'cold_90'
  | 'ns';

export interface SpatialHotspotProvince {
  name: string;
  rate: number | null;
  gi_z: number | null;
  p: number | null;
  cluster: HotspotCluster;
}

export interface SpatialHotspotsResponse {
  disease: string;
  level: string;
  year_start: number | null;
  year_end: number | null;
  n_valid: number;
  adjacency_version: string | null;
  global_moran: {
    I: number;
    p_sim: number;
    z: number;
    conclusion: string;
  } | null;
  provinces: SpatialHotspotProvince[];
}

export type BarrierStatus = 'reached' | 'near' | 'not_reached' | 'undetermined';

export interface SimulationCurrent {
  weighted_positivity_percent: number | null;
  weighted_avg_foi_per_year: number | null;
  estimated_r0: number | null;
  r0_reference: {
    typical: number | null;
    range_low: number | null;
    range_high: number | null;
  } | null;
  hit_percent: number | null;
  status: BarrierStatus;
}

export interface SimulationResult {
  effective_coverage_percent: number;
  hit_percent: number | null;
  gap_to_hit_percent: number | null;
  gain_from_booster_percent: number;
  status: BarrierStatus;
}

export interface SimulationResponse {
  disease: string | null;
  province: string | null;
  assumed_coverage_percent: number;
  booster_rate_percent: number;
  current: SimulationCurrent | null;
  simulated: SimulationResult | null;
  required_coverage_to_reach_hit: number | null;
  notes: string[];
}

// ===== 审核状态统计（按疾病 /analysis/coverage-review）=====

export interface CoverageReviewDisease {
  disease: string;
  total_points: number;
  total_samples: number;
  approved_points: number;
  approved_samples: number;
  pending_points: number;
  pending_samples: number;
  rejected_points: number;
  rejected_samples: number;
  approval_rate: number; // 通过率 0-1
}

export interface CoverageReviewOverview {
  total_diseases: number;
  total_points: number;
  total_samples: number;
  approved_points: number;
  pending_points: number;
  rejected_points: number;
  overall_approval_rate: number; // 0-1
}

export interface CoverageReviewResult {
  overview: CoverageReviewOverview;
  diseases: CoverageReviewDisease[];
}

// ===== 审核统计（/analysis/review-stats）=====

export interface ReviewStatsBucket {
  reviewed: number;
  approved: number;
  rejected: number;
  pass_rate: number; // 0-1
  avg_review_minutes: number | null;
}

export interface ReviewStatsByDisease extends ReviewStatsBucket {
  disease: string;
}

export interface ReviewStatsByReviewer extends ReviewStatsBucket {
  reviewer_id: string;
  reviewer_name: string;
}

export interface ReviewStatsResult {
  grand_total: ReviewStatsBucket;
  by_disease: ReviewStatsByDisease[];
  by_reviewer: ReviewStatsByReviewer[];
}

// ===== 抗原图谱（滴度矩阵制图 /analysis/antigenic-map）=====

export interface AntigenicMapPoint {
  name: string;
  type: 'antigen' | 'serum';
  x: number;
  y: number;
}

export interface AntigenicMapData {
  titer_table_id: string;
  literature_id: string;
  assay_type: 'hi' | 'vnt' | 'elisa';
  unit: string | null;
  antigens: string[];
  ref_antisera: string[];
  quality_score: number | null;
  confidence: string;
  source_page: number | null;
  coordinates: AntigenicMapPoint[];
  stress_raw: number;
  stress_normalized: number;
  stress_per_point: number[];
  grid_explanation: string;
  n_antigen: number;
  n_serum: number;
  dropped_rows: number[];
  converged: boolean;
  n_iter: number;
  meta?: {
    methodology_note?: string;
  };
}

export interface TiterTableItem {
  id: string;
  literature_id: string;
  literature_title: string;
  assay_type: 'hi' | 'vnt' | 'elisa';
  unit: string | null;
  n_antigens: number;
  n_sera: number;
  quality_score: number | null;
  confidence: string;
  created_at: string | null;
}

export interface TiterTableListData {
  items: TiterTableItem[];
  total: number;
}


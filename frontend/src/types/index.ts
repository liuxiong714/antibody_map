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
  literature_count: number;
  data_point_count: number;
  task_type?: string;
  task_time?: string;
  task_location?: string;
  personnel_count?: number;
  generated_at: string;
  content?: string;
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

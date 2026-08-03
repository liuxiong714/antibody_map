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
  created_at: string;
  updated_at: string;
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
  created_at: string;
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
  point_count: number;
  study_count: number;
  total_sample: number;
  weighted_positivity: number | null;
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
  who_threshold: number;
  summary: { total_data_points: number; total_literatures: number; total_samples: number; weighted_positivity_rate: number | null };
  yearly_trend: Array<{ year: number; weighted_positivity: number | null; sample_size: number; point_count: number }>;
  status: string;
  assessment: string;
}

// ===== 数据覆盖度分析 =====

export interface DataGapOverview {
  total_data_points: number;
  total_provinces: number;
  total_diseases: number;
  year_range: [number, number] | null;
  years: number[];
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  total_gap_combos: number;
}

export interface ReviewNeededItem {
  province: string;
  year: number | null;
  disease: string;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  total_count: number;
}

export interface DataGapItem {
  disease: string;
  covered_provinces: string[];
  missing_provinces: string[];
  covered_count: number;
  missing_count: number;
}

export interface ProvinceYearCell {
  total: number;
  pending: number;
  approved: number;
}

export interface ProvinceYearRow {
  province: string;
  years: Record<string, ProvinceYearCell>;
  total: number;
  pending: number;
}

export interface DataGapAnalysisResult {
  overview: DataGapOverview;
  review_needed: ReviewNeededItem[];
  data_gaps: DataGapItem[];
  province_year_matrix: ProvinceYearRow[];
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

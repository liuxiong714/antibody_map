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
  created_at: string;
}

export interface MapDataPoint {
  province?: string;
  city?: string;
  point_count: number;
  study_count: number;
  total_sample: number;
  weighted_positivity: number | null;
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
  title: string;
  content: string;
  literature_count: number;
  data_point_count: number;
  language: string;
  generated_at: string;
}


export interface ReportRecord {
  id: string;
  title: string;
  disease: string | null;
  province: string | null;
  data_type: string | null;
  language: string;
  literature_count: number;
  data_point_count: number;
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

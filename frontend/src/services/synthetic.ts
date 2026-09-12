import api from './api';

export interface SyntheticCreatePayload {
  disease: string;
  n_literatures: number;
  points_per_literature: number;
  generator_model: string;
  noise_ratio: number;
  seed: number;
}

export interface SyntheticPerNoise {
  total: number;
  rejected: number;
  rejection_rate: number;
}

export interface SyntheticReport {
  disease?: string;
  clean_total: number;
  clean_matched: number;
  clean_recall: number;
  value_exact_rate: number;
  value_tolerance_rate: number;
  noise_total: number;
  noise_rejected: number;
  noise_rejection_rate: number;
  field_accuracy?: Record<string, number>;
  per_noise_type?: Record<string, SyntheticPerNoise>;
}

export interface SyntheticLitProgress {
  id: string;
  title: string;
  extraction_status: string;
}

export interface SyntheticLitRow {
  literature_id: string;
  clean_total: number;
  clean_matched: number;
  noise_total: number;
  noise_rejected: number;
}

export interface SyntheticTask {
  id: string;
  disease: string;
  n_literatures: number;
  points_per_literature: number;
  generator_model: string;
  extractor_model: string | null;
  noise_ratio: number;
  seed: number;
  status: string;
  error_message: string | null;
  literature_count: number;
  created_at: string | null;
  updated_at: string | null;
  report?: SyntheticReport | null;
  literature_progress?: SyntheticLitProgress[];
  report_by_literature?: SyntheticLitRow[];
  report_per_noise?: Record<string, SyntheticPerNoise>;
}

export async function createSynthetic(payload: SyntheticCreatePayload): Promise<SyntheticTask> {
  const { data } = await api.post<SyntheticTask>('/synthetic', payload);
  return data;
}

export async function triggerExtractSynthetic(id: string, model: string): Promise<any> {
  const { data } = await api.post(`/synthetic/${id}/extract`, { model });
  return data;
}

export async function listSynthetic(): Promise<SyntheticTask[]> {
  const { data } = await api.get<SyntheticTask[]>('/synthetic');
  return data;
}

export async function getSynthetic(id: string): Promise<SyntheticTask> {
  const { data } = await api.get<SyntheticTask>(`/synthetic/${id}`);
  return data;
}

export async function assessSynthetic(id: string): Promise<SyntheticReport> {
  const { data } = await api.post<SyntheticReport>(`/synthetic/${id}/assess`);
  return data;
}

/** 导出评估报告 CSV（responseType blob，由调用方触发下载） */
export async function exportSynthetic(id: string): Promise<Blob> {
  const resp = await api.get(`/synthetic/${id}/export`, { responseType: 'blob' });
  return resp.data;
}
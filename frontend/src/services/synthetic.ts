import api from './api';

export interface SyntheticCreatePayload {
  disease: string;
  n_literatures: number;
  points_per_literature: number;
  generator_model: string;
  noise_ratio: number;
  seed: number;
  output_format: string;
  include_table: boolean;
  /** 测试文献来源：generated=生成模型A模拟生成 / existing=数据库已有文献 */
  literature_source: 'generated' | 'existing';
  /** existing 来源时：所选真实文献 id 列表 */
  literature_ids?: string[];
  /** existing 来源时：产出基准(GT)的参考模型 */
  reference_model?: string;
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

/** 单个数据点：真实(GT)点与提取识别点共用，字段按需存在 */
export interface SyntheticPoint {
  idx: number;
  data_type?: string;
  value?: number | null;
  unit?: string | null;
  sample_size?: number | null;
  province?: string | null;
  city?: string | null;
  collection_year?: number | null;
  noise_kind?: string | null;
  /** GT 点：是否被任一提取点命中 */
  matched?: boolean;
  /** 提取点：命中到哪个 GT 点(idx 从0)，null=模型额外识别/未对应 */
  gt_idx?: number | null;
}

export interface SyntheticLitRow {
  literature_id: string;
  title?: string;
  clean_total: number;
  clean_matched: number;
  noise_total: number;
  noise_rejected: number;
  gt_points?: SyntheticPoint[];
  extracted_points?: SyntheticPoint[];
}

export interface SyntheticMultiProgressItem {
  model: string;
  literature_id: string;
  title: string;
  status: string;
  error: string | null;
  updated_at: string | null;
  points_count: number;
}

export interface SyntheticComparisonItem {
  model: string;
  clean_total: number;
  clean_matched: number;
  clean_recall: number;
  value_exact_rate: number;
  noise_total: number;
  noise_rejected: number;
  noise_rejection_rate: number;
  field_accuracy?: Record<string, number>;
}

export interface SyntheticMultiLitModelInfo {
  extracted_points?: SyntheticPoint[];
  clean_total: number;
  clean_matched: number;
  noise_total: number;
  noise_rejected: number;
}

export interface SyntheticMultiLitRow {
  literature_id: string;
  title?: string;
  gt_points?: SyntheticPoint[];
  models?: Record<string, SyntheticMultiLitModelInfo>;
}

export interface SyntheticMultiModel {
  models: string[];
  comparison?: SyntheticComparisonItem[];
  by_literature?: SyntheticMultiLitRow[];
}

export interface SyntheticTask {
  id: string;
  disease: string;
  n_literatures: number;
  points_per_literature: number;
  literature_source: 'generated' | 'existing';
  generator_model: string;
  extractor_model: string | null;
  reference_model: string | null;
  models: string[] | null;
  noise_ratio: number;
  seed: number;
  output_format: string;
  include_table: boolean;
  status: string;
  error_message: string | null;
  literature_count: number;
  created_at: string | null;
  updated_at: string | null;
  report?: SyntheticReport | null;
  literature_progress?: SyntheticLitProgress[];
  multi_progress?: SyntheticMultiProgressItem[];
  report_by_literature?: SyntheticLitRow[];
  report_per_noise?: Record<string, SyntheticPerNoise>;
  multi_model?: SyntheticMultiModel | null;
  /** 阶段耗时（秒） */
  generation_seconds?: number | null;
  extraction_seconds?: number | null;
  total_seconds?: number | null;
}

export async function createSynthetic(payload: SyntheticCreatePayload): Promise<SyntheticTask> {
  const { data } = await api.post<SyntheticTask>('/synthetic', payload);
  return data;
}

export async function triggerExtractSynthetic(
  id: string,
  model: string | null,
  models?: string[],
): Promise<any> {
  const body = models && models.length
    ? { models }
    : { model };
  const { data } = await api.post(`/synthetic/${id}/extract`, body);
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

/** 删除失败状态的自测任务（后端级联清理其合成文献与数据点） */
export async function deleteSynthetic(id: string) {
  const { data } = await api.delete(`/synthetic/${id}`);
  return data;
}
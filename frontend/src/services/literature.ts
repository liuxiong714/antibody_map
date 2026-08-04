import api from './api';
import type {
  Literature,
  CheckDuplicateResult,
  ScanDuplicatesResult,
  MergePreviewResult,
  MergeRequestPayload,
  MergeResult,
} from '../types';

export interface PaginatedResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// 拦截器已将 ApiResponse.data 提升到 resp.data，此处解包 AxiosResponse

export async function listLiterature(params: Record<string, unknown>) {
  const { data } = await api.get<PaginatedResult<Literature>>('/literatures', { params });
  return data;
}

export async function getLiterature(id: string) {
  const { data } = await api.get<Literature>(`/literatures/${id}`);
  return data;
}

export async function deleteLiterature(id: string) {
  const { data } = await api.delete<{ message: string }>(`/literatures/${id}`);
  return data;
}

export async function updateLiterature(id: string, updates: Record<string, unknown>) {
  const { data } = await api.put<Literature>(`/literatures/${id}`, updates);
  return data;
}

export async function uploadLiterature(formData: FormData) {
  const { data } = await api.post<Literature>('/literatures/upload', formData);
  return data;
}

export async function createLiteratureFromUrl(url: string, title?: string, province?: string) {
  const formData = new FormData();
  formData.append('url', url);
  if (title) formData.append('title', title);
  if (province) formData.append('province', province);
  const { data } = await api.post<Literature>('/literatures/from-url', formData);
  return data;
}

export interface ExtractionOptions {
  model: string;
  apiKey?: string;
  baseUrl?: string;
}

export async function triggerExtraction(literatureId: string, options?: ExtractionOptions) {
  const body = options ? {
    model: options.model,
    api_key: options.apiKey,
    base_url: options.baseUrl,
  } : {};
  const { data } = await api.post(`/literatures/${literatureId}/extraction`, body);
  return data;
}

export async function getExtractionResults(literatureId: string) {
  const { data } = await api.get(`/literatures/${literatureId}/extraction`);
  return data;
}

export async function updateDataPoints(
  literatureId: string,
  dataPoints: Array<{
    id: string;
    review_status?: string;
    disease?: string | null;
    province?: string | null;
    city?: string | null;
    data_type?: string | null;
    value?: number | null;
    unit?: string | null;
    sample_size?: number | null;
    population?: string | null;
    age_min?: number | null;
    age_max?: number | null;
    collection_year?: number | null;
    confidence?: string | null;
    method?: string | null;
    assay?: string | null;
    source_page?: number | null;
    source_context?: string | null;
    // P0 新增：精确字符级溯源
    source_char_start?: number | null;
    source_char_end?: number | null;
    is_grounded?: boolean;
  }>,
) {
  const { data } = await api.put(`/literatures/${literatureId}/extraction`, { data_points: dataPoints });
  return data;
}

export async function createDataPoint(
  literatureId: string,
  dataPoint: {
    disease?: string | null;
    province?: string | null;
    city?: string | null;
    data_type?: string | null;
    value?: number | null;
    unit?: string | null;
    sample_size?: number | null;
    population?: string | null;
    age_min?: number | null;
    age_max?: number | null;
    collection_year?: number | null;
    confidence?: string | null;
    method?: string | null;
    assay?: string | null;
    source_page?: number | null;
    source_context?: string | null;
    // P0 新增：精确字符级溯源
    source_char_start?: number | null;
    source_char_end?: number | null;
    is_grounded?: boolean;
  },
) {
  const { data } = await api.post(`/literatures/${literatureId}/extraction/data-points`, dataPoint);
  return data;
}

// ===== P2：溯源文本查看 =====

export interface SourceTextResult {
  full_text: string | null;
  snippet: string | null;
  snippet_start?: number;
  snippet_end?: number;
  highlight_start?: number;
  highlight_end?: number;
  total_length: number;
  truncated?: boolean;
}

export async function getSourceText(
  literatureId: string,
  start?: number,
  end?: number,
  context = 200,
): Promise<SourceTextResult> {
  const params: Record<string, number> = { context };
  if (start != null) params.start = start;
  if (end != null) params.end = end;
  const { data } = await api.get<SourceTextResult>(
    `/literatures/${literatureId}/source-text`,
    { params },
  );
  return data;
}

// ===== 查重与合并 API =====

export async function checkDuplicate(payload: {
  literature_id?: string;
  title?: string;
  doi?: string;
  authors?: string;
  pdf_hash?: string;
}): Promise<CheckDuplicateResult> {
  const { data } = await api.post<CheckDuplicateResult>('/literatures/check-duplicate', payload);
  return data;
}

export async function scanDuplicates(): Promise<ScanDuplicatesResult> {
  const { data } = await api.post<ScanDuplicatesResult>('/literatures/scan-duplicates');
  return data;
}

export async function previewMerge(sourceId: string, targetId: string): Promise<MergePreviewResult> {
  const { data } = await api.post<MergePreviewResult>('/literatures/merge/preview', {
    source_id: sourceId,
    target_id: targetId,
  });
  return data;
}

export async function mergeLiteratures(payload: MergeRequestPayload): Promise<MergeResult> {
  const { data } = await api.post<MergeResult>('/literatures/merge', payload);
  return data;
}

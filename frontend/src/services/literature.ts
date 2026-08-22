import api from './api';
import type {
  Literature,
  ExtractionStatusWithUsage,
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

export async function openLiteratureFolder(id: string) {
  const { data } = await api.post<{ opened: boolean; path: string; folder: string }>(
    `/literatures/${id}/open-folder`,
  );
  return data;
}

/**
 * 下载文献文件（带 JWT 认证，经浏览器自动触发下载）。
 * 说明：不能用 window.open('/api/.../download') 裸跳转——后端要求 JWT，
 * 裸跳转不带 Authorization 头会返回 401。这里走 axios(自带 token) 取 blob 后触发下载。
 */
export async function downloadLiteratureFile(id: string, title?: string) {
  const resp = await api.get<Blob>(`/literatures/${id}/download`, {
    responseType: 'blob',
  });
  const blob = resp.data as Blob;
  // 优先从 Content-Disposition 解析服务器返回的文件名，其次用标题兜底
  let filename = '';
  const cd = (resp.headers?.['content-disposition'] as string) || '';
  const utf8Match = cd.match(/filename\*=utf-8''([^;]+)/i);
  if (utf8Match) {
    filename = decodeURIComponent(utf8Match[1]);
  } else {
    const plainMatch = cd.match(/filename="?([^"]+)"?/i);
    if (plainMatch) filename = plainMatch[1];
  }
  if (!filename) {
    const base = (title || `literature_${id}`).replace(/[\\/:*?"<>|]+/g, '_');
    filename = `${base}.${extFromContentType(blob.type)}`;
  }

  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
}

function extFromContentType(type: string): string {
  const map: Record<string, string> = {
    'application/pdf': 'pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    'text/html': 'html',
    'text/plain': 'txt',
    'application/epub+zip': 'epub',
  };
  return map[type] || type.split('/')[1] || 'download';
}

export async function deleteLiterature(id: string) {
  const { data } = await api.delete<{ message: string }>(`/literatures/${id}`);
  return data;
}

export async function batchDeleteLiteratures(ids: string[]) {
  const { data } = await api.post<{ message: string }>('/literatures/batch-delete', { literature_ids: ids });
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
  clearExistingData?: boolean;
}

export async function triggerExtraction(literatureId: string, options?: ExtractionOptions) {
  const body: Record<string, unknown> = {};
  if (options) {
    body.model = options.model;
    body.api_key = options.apiKey;
    body.base_url = options.baseUrl;
    if (options.clearExistingData !== undefined) {
      body.clear_existing_data = options.clearExistingData;
    }
  }
  // AI 提取启动接口本身是"提交任务"式的（后端通过 SSE/轮询查进度），超时时间给 60s 保障启动阶段稳定
  const { data } = await api.post(`/literatures/${literatureId}/extraction`, body, { timeout: 60_000 });
  return data;
}

export interface BatchExtractionResult {
  submitted: Array<{ id: string; title: string }>;
  skipped: Array<{ id: string; title?: string; reason: string }>;
  errors: Array<{ id: string; reason: string }>;
  submitted_count: number;
  skipped_count: number;
  error_count: number;
}

export async function triggerBatchExtraction(
  literatureIds: string[],
  options?: ExtractionOptions,
): Promise<BatchExtractionResult> {
  const body: Record<string, unknown> = {
    literature_ids: literatureIds,
  };
  if (options) {
    body.model = options.model;
    body.api_key = options.apiKey;
    body.base_url = options.baseUrl;
    if (options.clearExistingData !== undefined) {
      body.clear_existing_data = options.clearExistingData;
    }
  }
  const { data } = await api.post('/literatures/extraction/batch', body, { timeout: 60_000 });
  return data;
}

// ── 文献标签管理 ──

export interface TagItem {
  id: string;
  name: string;
  color: string;
}

export async function listTags(): Promise<TagItem[]> {
  const { data } = await api.get('/tags');
  return data.data || [];
}

export async function createTag(name: string, color?: string): Promise<TagItem> {
  const { data } = await api.post('/tags', { name, color });
  return data.data;
}

export async function deleteTag(tagId: string): Promise<void> {
  await api.delete(`/tags/${tagId}`);
}

export async function setLiteratureTags(literatureId: string, tagIds: string[]): Promise<void> {
  await api.post(`/literatures/${literatureId}/tags`, tagIds);
}

// ── 提取状态修复与手动停止 ──

export async function stopExtraction(literatureId: string): Promise<{ literature_id: string; status: string }> {
  const { data } = await api.post(`/literatures/${literatureId}/extraction/stop`);
  return data;
}

export async function resetStuckExtractions(): Promise<{ reset_count: number; literature_ids?: string[] }> {
  const { data } = await api.post('/literatures/extraction/reset-stuck');
  return data;
}

export interface SyncMetadataResult {
  id: string;
  pub_year: number | null;
  province: string | null;
  pub_year_updated: boolean;
  province_updated: boolean;
  data_point_count: number;
}

export async function syncMetadata(literatureId: string): Promise<SyncMetadataResult> {
  const { data } = await api.post(`/literatures/${literatureId}/sync-metadata`);
  return data;
}

export interface BatchSyncMetadataResult {
  total: number;
  synced: number;
  skipped: number;
  details: Array<{
    id: string;
    title: string;
    pub_year: number | null;
    province: string | null;
    pub_year_updated: boolean;
    province_updated: boolean;
  }>;
}

export async function syncMetadataBatch(): Promise<BatchSyncMetadataResult> {
  const { data } = await api.post('/literatures/sync-metadata-batch');
  return data;
}

export async function getExtractionStatus(literatureId: string) {
  const { data } = await api.get<ExtractionStatusWithUsage>(`/literatures/${literatureId}/extraction/status`);
  return data;
}

export async function getExtractionResults(literatureId: string) {
  const { data } = await api.get(`/literatures/${literatureId}/extraction`);
  return data;
}

/** 获取文献的历次 AI 提取历史 */
export interface ExtractionHistoryItem {
  id: string;
  extracted_at: string;
  model: string | null;
  status: string;
  data_point_count: number;
  error_message: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  llm_cost_usd: number;
  llm_call_count: number;
  llm_usage_detail: Record<string, { prompt_tokens: number; completion_tokens: number; total_tokens: number; call_count: number }> | null;
}

export async function getExtractionHistory(literatureId: string): Promise<ExtractionHistoryItem[]> {
  const { data } = await api.get<ExtractionHistoryItem[]>(`/literatures/${literatureId}/extraction/history`);
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

// 批量审核通过（comment 可选）
export async function confirmDataPoints(
  literatureId: string,
  ids: string[],
  comment?: string,
) {
  const { data } = await api.post(`/literatures/${literatureId}/extraction/confirm`, {
    ids,
    comment: comment ?? undefined,
  });
  return data;
}

// 批量驳回（comment 必填，后端强制）
export async function disputeDataPoints(
  literatureId: string,
  ids: string[],
  comment: string,
) {
  const { data } = await api.post(`/literatures/${literatureId}/extraction/dispute`, {
    ids,
    comment,
  });
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

// ===== 关联文件上传 =====

export async function uploadLiteratureFile(
  literatureId: string,
  file: File,
) {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post(`/literatures/${literatureId}/file`, formData);
  return data;
}

// ===== 导入 =====

export interface ImportResult {
  imported_count: number;
  skipped_count: number;
  data_point_count: number;
  error_count: number;
  errors: Array<{ index: number; title?: string; reason: string }>;
  imported_titles: string[];
}

export async function importLiteratures(
  file: File,
  skipDuplicates: boolean = true,
): Promise<ImportResult> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('skip_duplicates', String(skipDuplicates));
  const { data } = await api.post<ImportResult>('/literatures/import', formData);
  return data;
}

// ===== 批量从本地文件夹导入 =====

export interface BatchImportResult {
  matched: number;
  imported: number;
  skipped: number;
  failed: number;
  extraction_triggered: number;
  total: number;
  details: Array<{
    filename: string;
    status: string;
    literature_id?: string;
    title?: string;
    error?: string;
    reason?: string;
  }>;
}

export async function batchImportFromFolder(
  folderPath: string,
  triggerExtraction: boolean = true,
): Promise<BatchImportResult> {
  const formData = new FormData();
  formData.append('folder_path', folderPath);
  formData.append('trigger_extraction_after', String(triggerExtraction));
  const { data } = await api.post<BatchImportResult>('/literatures/batch-import-from-folder', formData);
  return data;
}

/** 从浏览器批量上传文件（使用 webkitdirectory 选择文件夹） */
export async function batchUploadFiles(
  files: File[],
  triggerExtraction: boolean = true,
): Promise<BatchImportResult> {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  formData.append('trigger_extraction_after', String(triggerExtraction));
  const { data } = await api.post<BatchImportResult>('/literatures/batch-upload-files', formData, {
    timeout: 300_000, // 大文件上传给 5 分钟超时
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export interface CleanupEmptyResult {
  preview_count: number;
  deleted_count: number;
}

export async function cleanupEmpty(dryRun: boolean = true): Promise<CleanupEmptyResult> {
  const { data } = await api.post<CleanupEmptyResult>(`/literatures/cleanup-empty?dry_run=${dryRun}`);
  return data;
}

// ===== 孤儿文件清理 =====

export interface OrphanCleanupPreview {
  scanned: number;
  orphan_count: number;
  orphan_files: string[];
}

export interface OrphanCleanupResult {
  scanned: number;
  orphan_count: number;
  moved: number;
  failed: number;
  purged: number;
  trash_dir: string;
}

export async function previewOrphanCleanup(): Promise<OrphanCleanupPreview> {
  const { data } = await api.get<OrphanCleanupPreview>('/literatures/cleanup-orphan-files/preview');
  return data;
}

export async function executeOrphanCleanup(): Promise<OrphanCleanupResult> {
  const { data } = await api.post<OrphanCleanupResult>('/literatures/cleanup-orphan-files');
  return data;
}

export interface ExtractionQueueStatus {
  pending_count: number;
  queued_count: number;
  processing_count: number;
  done_count: number;
  failed_count: number;
  total: number;
  queued_literatures: { id: string; title: string }[];
  processing_literatures: { id: string; title: string }[];
}

export async function getExtractionQueueStatus(): Promise<ExtractionQueueStatus> {
  const { data } = await api.get<ExtractionQueueStatus>('/extractions/queue-status');
  return data;
}

// ===== 回收站管理 =====

export interface TrashItem {
  id: string;
  title: string;
  authors?: string;
  journal?: string;
  pub_year?: number;
  deleted_at: string;
  [key: string]: any;
}

export interface TrashListResult {
  items: TrashItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface EmptyTrashResult {
  permanently_deleted: number;
  remaining: number;
}

export async function listTrash(page: number = 1, pageSize: number = 20, keyword?: string): Promise<TrashListResult> {
  const params: any = { page, page_size: pageSize };
  if (keyword) params.keyword = keyword;
  const { data } = await api.get<TrashListResult>('/literatures/trash', { params });
  return data;
}

export async function restoreLiterature(literatureId: string): Promise<void> {
  await api.post(`/literatures/trash/${literatureId}/restore`);
}

export async function permanentlyDeleteLiterature(literatureId: string): Promise<void> {
  await api.delete(`/literatures/trash/${literatureId}`);
}

export async function emptyTrash(olderThanDays: number = 30): Promise<EmptyTrashResult> {
  const { data } = await api.post<EmptyTrashResult>(`/literatures/trash/empty?older_than_days=${olderThanDays}`);
  return data;
}

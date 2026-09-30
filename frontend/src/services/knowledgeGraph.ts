import api from './api';
import { cachedGet } from '../lib/apiCache';
import type {
  KgGraphData, KgOptionsData, KgOverviewData,
  KgSearchResult, KgPathResult, KgStatsData, KgEvidence,
} from '../types';

// 静态/低频变化数据用较长 TTL；依赖筛选条件的图谱数据用短 TTL
const CACHE_STATIC = 120_000;
const CACHE_FILTER = 30_000;

export async function getKgOverview(params?: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<KgOverviewData>('/kg/overview', { params });
      return data;
    },
    '/kg/overview',
    params,
    CACHE_STATIC,
  );
}

export async function getKgOptions() {
  return cachedGet(
    async () => {
      const { data } = await api.get<KgOptionsData>('/kg/options');
      return data;
    },
    '/kg/options',
    undefined,
    CACHE_STATIC,
  );
}

export async function getKgGraph(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<KgGraphData>('/kg/graph', {
        params,
        // indexes: null → 数组序列化成重复键 foo=a&foo=b（FastAPI list[str] Query 兼容）
        paramsSerializer: { indexes: null },
      });
      return data;
    },
    '/kg/graph',
    params,
    CACHE_FILTER,
  );
}

export async function searchKgEntities(q: string, type?: string, limit = 20) {
  const params: Record<string, unknown> = { q, limit };
  if (type) params.type = type;
  const { data } = await api.get<KgSearchResult[]>('/kg/entities/search', { params });
  return data;
}

export async function queryKgPath(fromId: string, toId: string, maxDepth = 3) {
  const { data } = await api.get<KgPathResult>('/kg/query/path', {
    params: { from_id: fromId, to_id: toId, max_depth: maxDepth },
  });
  return data;
}

export async function getKgStats() {
  return cachedGet(
    async () => {
      const { data } = await api.get<KgStatsData>('/kg/stats');
      return data;
    },
    '/kg/stats',
    undefined,
    CACHE_STATIC,
  );
}

export interface KgTriggerResp {
  task_id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  scope: string;
}

export async function triggerKgExtraction(limit = 5, literatureIds?: string[], model?: string): Promise<KgTriggerResp> {
  const { data } = await api.post<KgTriggerResp>(
    '/kg/extraction/trigger',
    null,
    {
      params: {
        limit,
        model: model || undefined,
        // 定向抽取：多个 literature_id 查询参数；未提供时后端走自动批量
        literature_id: literatureIds && literatureIds.length ? literatureIds : undefined,
      },
      // axios 默认把数组序列化成 literature_id[]=a&...，与后端 Query(alias="literature_id")
      // 不匹配导致定向文献 ID 全丢、退化为自动批量；indexes:null 改为重复键 literature_id=a&literature_id=b
      paramsSerializer: { indexes: null },
    },
  );
  return data;
}

export async function getKgMergeCandidates(limit = 30) {
  const { data } = await api.get<Array<{
    entity_type: string; reason: string;
    members: Array<{ id: string; name: string; entity_type: string; attributes: Record<string, unknown>; source_literature_id: string | null; triple_count: number }>;
  }>>('/kg/entities/merge-candidates', { params: { limit } });
  return data;
}

export async function mergeKgEntities(keepId: string, mergeIds: string[]) {
  const { data } = await api.post<{ merged: number; moved_triples: number }>(
    '/kg/entities/merge',
    { keep_id: keepId, merge_ids: mergeIds },
  );
  return data;
}

export async function askKgQuestion(question: string, prevSlots?: Record<string, string> | null) {
  const { data } = await api.post<{
    answer: string; template: string | null; method: string; result_count: number;
    slots: Record<string, string> | null; evidence?: KgEvidence[]; log_id?: string;
  }>(
    '/kg/qa/ask',
    { question, prev_slots: prevSlots || null },
    // 未命中模板的问题会走 LLM 兜底（本地模型较慢），超时对齐后端 LLM_REQUEST_TIMEOUT(600s)，避免 120s 全局超时提前中断
    { timeout: 600_000 },
  );
  return data;
}

/** 问答反馈（点赞/点踩），log_id 来自 askKgQuestion 返回 */
export async function feedbackKgQa(logId: string, feedback: 'up' | 'down') {
  const { data } = await api.post<{ id: string; feedback: string }>(
    `/kg/qa/log/${logId}/feedback`,
    { feedback },
  );
  return data;
}

export interface KgTripleReviewItem {
  id: string;
  subject: string;
  subject_type: string;
  predicate: string;
  object: string;
  object_type: string;
  confidence: number;
  source_context: string | null;
  literature_id: string | null;
  literature_title: string | null;
}

/** 抽取质量评估：抽样待校验三元组 */
export async function getKgReviewSample(limit = 20, minConfidence?: number) {
  const { data } = await api.get<KgTripleReviewItem[]>('/kg/triples/review-sample', {
    params: { limit, ...(minConfidence != null ? { min_confidence: minConfidence } : {}) },
  });
  return data;
}

/** 标记三元组校验结果（管理员） */
export async function reviewKgTriples(ids: string[], status: 'approved' | 'rejected') {
  const { data } = await api.post<{ updated: number; status: string }>(
    '/kg/triples/review',
    { ids, status },
  );
  return data;
}

/** 批量删除错误三元组（管理员） */
export async function deleteKgTriples(ids: string[]) {
  const { data } = await api.post<{ deleted: number }>('/kg/triples/batch-delete', { ids });
  return data;
}

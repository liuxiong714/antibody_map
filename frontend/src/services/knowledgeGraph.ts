import api from './api';
import { cachedGet } from '../lib/apiCache';
import type {
  KgGraphData, KgOptionsData, KgOverviewData,
  KgSearchResult, KgPathResult, KgStatsData,
} from '../types';

// 静态/低频变化数据用较长 TTL；依赖筛选条件的图谱数据用短 TTL
const CACHE_STATIC = 120_000;
const CACHE_FILTER = 30_000;

export async function getKgOverview() {
  return cachedGet(
    async () => {
      const { data } = await api.get<KgOverviewData>('/kg/overview');
      return data;
    },
    '/kg/overview',
    undefined,
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
      const { data } = await api.get<KgGraphData>('/kg/graph', { params });
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

export async function triggerKgExtraction(limit = 5, literatureIds?: string[]): Promise<KgTriggerResp> {
  const { data } = await api.post<KgTriggerResp>(
    '/kg/extraction/trigger',
    null,
    {
      params: {
        limit,
        // 定向抽取：多个 literature_id 查询参数；未提供时后端走自动批量
        literature_id: literatureIds && literatureIds.length ? literatureIds : undefined,
      },
    },
  );
  return data;
}

export async function askKgQuestion(question: string) {
  const { data } = await api.post<{ answer: string; template: string | null; method: string; result_count: number; slots: Record<string, string> | null }>(
    '/kg/qa/ask',
    { question },
    // 未命中模板的问题会走 LLM 兜底（本地模型较慢），超时对齐后端 LLM_REQUEST_TIMEOUT(600s)，避免 120s 全局超时提前中断
    { timeout: 600_000 },
  );
  return data;
}

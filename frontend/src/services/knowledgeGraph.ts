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

export async function triggerKgExtraction(limit = 5) {
  const { data } = await api.post<{ processed: number; total_written: number; remaining: number; errors: string[] }>(
    '/kg/extraction/trigger',
    null,
    { params: { limit } },
  );
  return data;
}

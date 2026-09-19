// 流行病学 / 病原学监测数据只读 API（阶段3「流行特征」页）
import api from './api';
import { cachedGet, clearApiCache } from '../lib/apiCache';

// ===== 类型 =====

export interface EpidemicByType {
  data_type: string;
  count: number;
  literature_count: number;
  first_year: number | null;
  latest_year: number | null;
  sum: number;
  avg: number;
  unit: string | null;
}

export interface EpidemicByProvince {
  province: string;
  literature_count: number;
  incidence?: number | null;
  case_count?: number | null;
  mortality?: number | null;
  death_count?: number | null;
}

export interface EpidemicOverview {
  by_type: EpidemicByType[];
  by_province: EpidemicByProvince[];
  total_literatures: number;
  total_data_points: number;
}

export interface EpidemicDataPoint {
  id: string;
  literature_id: string | null;
  disease: string | null;
  province: string | null;
  city: string | null;
  data_type: string;
  value: number | null;
  unit: string | null;
  sample_size: number | null;
  collection_year: number | null;
  population: string | null;
  source_context: string | null;
}

export interface PathogenMonitoringItem {
  id: string;
  literature_id: string | null;
  disease: string | null;
  pathogen_type: string | null;
  pathogen_name: string | null;
  serotype: string | null;
  genotype: string | null;
  subtype: string | null;
  lineage: string | null;
  variant_sites: string | null;
  detection_rate: number | null;
  isolation_count: number | null;
  sample_size: number | null;
  detection_method: string | null;
  population: string | null;
  specimen: string | null;
  region: string | null;
  province: string | null;
  city: string | null;
  collection_year: number | null;
  source_context: string | null;
  review_status: string;
}

export interface DistEntry { value: string; count: number }

export interface PathogenMonitoringResult {
  list: { items: PathogenMonitoringItem[]; page: number; page_size: number; total: number };
  by_genotype: DistEntry[];
  by_serotype: DistEntry[];
  by_subtype: DistEntry[];
  by_pathogen_type: DistEntry[];
  by_pathogen_name: DistEntry[];
}

const CACHE_STATIC = 60_000;

/** 流行病学指标概览 */
export function getEpidemicOverview(params: Record<string, unknown> = {}) {
  return cachedGet(
    async () => {
      const { data } = await api.get<EpidemicOverview>('/epidemic/overview', { params });
      return data;
    },
    '/epidemic/overview',
    params,
    CACHE_STATIC,
  );
}

/** 流行病学数据点明细（分页） */
export function getEpidemicDataPoints(params: Record<string, unknown> = {}) {
  return cachedGet(
    async () => {
      const { data } = await api.get<{ items: EpidemicDataPoint[]; page: number; page_size: number; total: number }>(
        '/epidemic/data-points',
        { params },
      );
      return data;
    },
    '/epidemic/data-points',
    params,
    CACHE_STATIC,
  );
}

/** 病原学监测列表 + 分布 */
export function getPathogenMonitoring(params: Record<string, unknown> = {}) {
  return cachedGet(
    async () => {
      const { data } = await api.get<PathogenMonitoringResult>('/epidemic/pathogen-monitoring', { params });
      return data;
    },
    '/epidemic/pathogen-monitoring',
    params,
    CACHE_STATIC,
  );
}

/** 单篇文献病原学记录（文献详情） */
export async function getPathogenMonitoringByLiterature(literatureId: string) {
  const { data } = await api.get<{ items: PathogenMonitoringItem[]; total: number }>(
    `/epidemic/pathogen-monitoring/literature/${literatureId}`,
  );
  return data;
}

/** 新提取/审核数据后清除缓存 */
export function clearEpidemicApiCache() {
  clearApiCache('/epidemic/');
}
import api from './api';
import { cachedGet, clearApiCache } from '../lib/apiCache';
import type { ImmuneBarrierData, MapDataPoint, PagedResponse, ReportData, ReportRecord, ReportTemplate, ReportSection, YearlyMapData, DataGapAnalysisResult, FoiHerdImmunityResult, VaccineEffectivenessCoverageResult, ApiModelConfig, LocalModelConfig, ModelsListData, EquityAnalysisResponse, QualityAssessmentResponse, GoalTrackingResponse, AgeCurveResponse, BirthCohortResponse, MetaMergeResponse, MetaAnalysisResponse, AssayHeterogeneityResponse, SimulationResponse, CoverageReviewResult, ReviewStatsResult, SpatialHotspotsResponse, AntigenicMapData, TiterTableListData } from '../types';

// 拦截器已将 ApiResponse.data 提升到 resp.data，此处解包 AxiosResponse

// 缓存 TTL（毫秒）：静态/低频变化数据用较长 TTL，筛选频繁变化数据用短 TTL
const CACHE_STATIC = 120_000; // 2 分钟：省份数据、可用年份、人群选项、汇总
const CACHE_FILTER = 30_000; // 30 秒：依赖筛选条件的动态数据

export async function getProvinceData(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<MapDataPoint[]>('/map/province-data', { params });
      return data;
    },
    '/map/province-data',
    params,
    CACHE_STATIC,
  );
}

export async function getYearlyProvinceData(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<YearlyMapData[]>('/map/yearly-data', { params });
      return data;
    },
    '/map/yearly-data',
    params,
    CACHE_STATIC,
  );
}

export async function getAvailableYears(disease?: string) {
  const params: Record<string, unknown> = {};
  if (disease) params.disease = disease;
  return cachedGet(
    async () => {
      const { data } = await api.get<number[]>('/map/available-years', { params });
      return data;
    },
    '/map/available-years',
    params,
    CACHE_STATIC,
  );
}

export async function getPopulationOptions(disease?: string) {
  const params: Record<string, unknown> = {};
  if (disease) params.disease = disease;
  return cachedGet(
    async () => {
      const { data } = await api.get<string[]>('/map/population-options', { params });
      return data;
    },
    '/map/population-options',
    params,
    CACHE_STATIC,
  );
}

export async function getCityData(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<MapDataPoint[]>('/map/city-data', { params });
      return data;
    },
    '/map/city-data',
    params,
    CACHE_FILTER,
  );
}

export async function getSummary(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get('/map/summary', { params });
      return data;
    },
    '/map/summary',
    params,
    CACHE_STATIC,
  );
}

/** 数据变更（审核/提取/导入）后清除地图接口缓存，避免展示过期数据 */
export function clearMapApiCache() {
  clearApiCache('/map/');
}

export async function getTrend(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get('/analysis/trend', { params });
      return data;
    },
    '/analysis/trend',
    params,
    CACHE_FILTER,
  );
}

export async function getRegionCompare(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get('/analysis/region-compare', { params });
      return data;
    },
    '/analysis/region-compare',
    params,
    CACHE_FILTER,
  );
}

export async function getAgeStratify(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get('/analysis/age-stratify', { params });
      return data;
    },
    '/analysis/age-stratify',
    params,
    CACHE_FILTER,
  );
}

export async function getApprovedDataPoints(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get('/analysis/approved-data-points', { params });
      return data;
    },
    '/analysis/approved-data-points',
    params,
    CACHE_FILTER,
  );
}

export async function getImmuneBarrier(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<ImmuneBarrierData>('/analysis/immune-barrier', { params });
      return data;
    },
    '/analysis/immune-barrier',
    params,
    CACHE_FILTER,
  );
}

export async function getDataGapAnalysis(params?: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<DataGapAnalysisResult>('/analysis/data-gaps', { params });
      return data;
    },
    '/analysis/data-gaps',
    params,
    CACHE_FILTER,
  );
}

// 按疾病维度的审核状态统计（数据点/样本量/通过率）
export async function fetchCoverageReview(params?: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<CoverageReviewResult>('/analysis/coverage-review', { params });
      return data;
    },
    '/analysis/coverage-review',
    params,
    CACHE_FILTER,
  );
}

// 审核统计（审核量/通过率/平均审核时间，按疾病/审核人）
export async function fetchReviewStats() {
  return cachedGet(
    async () => {
      const { data } = await api.get<ReviewStatsResult>('/analysis/review-stats');
      return data;
    },
    '/analysis/review-stats',
  );
}

/** 数据变更（审核/提取/导入）后清除分析接口缓存，避免展示过期数据 */
export function clearAnalysisApiCache() {
  clearApiCache('/analysis/');
}

export async function generateReport(params: Record<string, unknown>) {
  // 报告生成需要调用 LLM，超时时间放宽到 600s（匹配后端 LLM_REQUEST_TIMEOUT）
  const { data } = await api.post<ReportData>('/reports/generate', null, { params, timeout: 600_000 });
  return data;
}

export async function generateVaccinationStrategy(body: Record<string, unknown>) {
  const { data } = await api.post<ReportData>('/reports/generate-vaccination-strategy', body, { timeout: 600_000 });
  return data;
}

export async function updateReport(id: string, body: { title?: string; content?: string }) {
  const { data } = await api.put<ReportRecord>(`/reports/${id}`, body);
  return data;
}

export async function deleteReport(id: string) {
  const { data } = await api.delete(`/reports/${id}`);
  return data;
}

export async function listReports(params: Record<string, unknown>) {
  const { data } = await api.get<PagedResponse<ReportRecord>>('/reports', { params });
  return data;
}

export async function getReport(id: string) {
  const { data } = await api.get<ReportRecord>(`/reports/${id}`);
  return data;
}

export function getDownloadUrl(id: string) {
  return `/api/v1/reports/${id}/download`;
}

// ===== 报告模板管理 =====

export async function listTemplates(report_type?: string) {
  const params: Record<string, unknown> = {};
  if (report_type) params.report_type = report_type;
  const { data } = await api.get<ReportTemplate[]>('/report/templates', { params });
  return data;
}

export async function createTemplate(body: Partial<ReportTemplate> & { sections: ReportSection[] }) {
  const { data } = await api.post<ReportTemplate>('/report/templates', body);
  return data;
}

export async function updateTemplate(id: string, body: Partial<ReportTemplate> & { sections: ReportSection[] }) {
  const { data } = await api.put<ReportTemplate>(`/report/templates/${id}`, body);
  return data;
}

export async function deleteTemplate(id: string) {
  const { data } = await api.delete(`/report/templates/${id}`);
  return data;
}

// P0: FOI 感染力 + 群体免疫阈值分析
export async function getFoiHerdImmunity(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<FoiHerdImmunityResult>('/analysis/foi-herd-immunity', { params });
      return data;
    },
    '/analysis/foi-herd-immunity',
    params,
    CACHE_FILTER,
  );
}

// P1: 疫苗效果 VE + 接种率综合分析
export async function getVaccineEffectivenessCoverage(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<VaccineEffectivenessCoverageResult>('/analysis/vaccine-effectiveness-coverage', { params });
      return data;
    },
    '/analysis/vaccine-effectiveness-coverage',
    params,
    CACHE_FILTER,
  );
}

// ===== 公平性 / 数据质量 / 目标达成 / 年龄曲线 / meta / assay / 模拟 =====

export async function getEquityAnalysis(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<EquityAnalysisResponse>('/analysis/equity', { params });
      return data;
    },
    '/analysis/equity',
    params,
    CACHE_FILTER,
  );
}

export async function getQualityAssessment(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<QualityAssessmentResponse>('/analysis/quality', { params });
      return data;
    },
    '/analysis/quality',
    params,
    CACHE_FILTER,
  );
}

export async function getGoalTracking(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<GoalTrackingResponse>('/analysis/goal-tracking', { params });
      return data;
    },
    '/analysis/goal-tracking',
    params,
    CACHE_FILTER,
  );
}

export async function getAgeCurve(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<AgeCurveResponse>('/analysis/age-curve', { params });
      return data;
    },
    '/analysis/age-curve',
    params,
    CACHE_FILTER,
  );
}

export async function getBirthCohort(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<BirthCohortResponse>('/analysis/birth-cohort', { params });
      return data;
    },
    '/analysis/birth-cohort',
    params,
    CACHE_FILTER,
  );
}

export async function getMetaMerge(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<MetaMergeResponse>('/analysis/meta-merge', { params });
      return data;
    },
    '/analysis/meta-merge',
    params,
    CACHE_FILTER,
  );
}

export async function getMetaAnalysis(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<MetaAnalysisResponse>('/analysis/meta-analysis', { params });
      return data;
    },
    '/analysis/meta-analysis',
    params,
    CACHE_FILTER,
  );
}

export async function getAssayHeterogeneity(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<AssayHeterogeneityResponse>('/analysis/assay-heterogeneity', { params });
      return data;
    },
    '/analysis/assay-heterogeneity',
    params,
    CACHE_FILTER,
  );
}

export async function getSpatialHotspots(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<SpatialHotspotsResponse>('/analysis/spatial-hotspots', { params });
      return data;
    },
    '/analysis/spatial-hotspots',
    params,
    CACHE_FILTER,
  );
}

export async function getSimulation(params: Record<string, unknown>) {
  return cachedGet(
    async () => {
      const { data } = await api.get<SimulationResponse>('/analysis/simulate', { params });
      return data;
    },
    '/analysis/simulate',
    params,
    CACHE_FILTER,
  );
}

// ===== 模型管理 =====

export async function getModels() {
  const { data } = await api.get<ModelsListData>('/models');
  return data;
}

export async function listRemoteModels() {
  const { data } = await api.get<ApiModelConfig[]>('/models/remote');
  return data;
}

export async function createRemoteModel(body: { name: string; model_name: string; api_key: string; base_url: string; description?: string }) {
  const { data } = await api.post<ApiModelConfig>('/models/remote', body);
  return data;
}

export async function updateRemoteModel(id: string, body: Partial<ApiModelConfig>) {
  const { data } = await api.put<ApiModelConfig>(`/models/remote/${id}`, body);
  return data;
}

export async function deleteRemoteModel(id: string) {
  const { data } = await api.delete(`/models/remote/${id}`);
  return data;
}

export async function listLocalModels() {
  const { data } = await api.get<LocalModelConfig[]>('/models/local');
  return data;
}

export async function createLocalModel(body: { name: string; model_name: string; description?: string }) {
  const { data } = await api.post<LocalModelConfig>('/models/local', body);
  return data;
}

export async function updateLocalModel(id: string, body: Partial<LocalModelConfig>) {
  const { data } = await api.put<LocalModelConfig>(`/models/local/${id}`, body);
  return data;
}

export async function deleteLocalModel(id: string) {
  const { data } = await api.delete(`/models/local/${id}`);
  return data;
}

// ===== 抗原图谱（滴度矩阵制图）=====

export async function getTiterTables(params: Record<string, unknown> = {}) {
  return cachedGet(
    async () => {
      const { data } = await api.get<TiterTableListData>('/analysis/titer-tables', { params });
      return data;
    },
    '/analysis/titer-tables',
    params,
    CACHE_FILTER,
  );
}

export async function getAntigenicMap(titerTableId: string) {
  const { data } = await api.get<AntigenicMapData>(`/analysis/antigenic-map/${titerTableId}`);
  return data;
}

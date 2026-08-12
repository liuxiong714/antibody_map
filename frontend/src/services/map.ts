import api from './api';
import type { ImmuneBarrierData, MapDataPoint, PagedResponse, ReportData, ReportRecord, YearlyMapData, DataGapAnalysisResult, FoiHerdImmunityResult, VaccineEffectivenessCoverageResult, ApiModelConfig, ModelsListData } from '../types';

// 拦截器已将 ApiResponse.data 提升到 resp.data，此处解包 AxiosResponse

export async function getProvinceData(params: Record<string, unknown>) {
  const { data } = await api.get<MapDataPoint[]>('/map/province-data', { params });
  return data;
}

export async function getYearlyProvinceData(params: Record<string, unknown>) {
  const { data } = await api.get<YearlyMapData[]>('/map/yearly-data', { params });
  return data;
}

export async function getAvailableYears(disease?: string) {
  const params: Record<string, unknown> = {};
  if (disease) params.disease = disease;
  const { data } = await api.get<number[]>('/map/available-years', { params });
  return data;
}

export async function getPopulationOptions(disease?: string) {
  const params: Record<string, unknown> = {};
  if (disease) params.disease = disease;
  const { data } = await api.get<string[]>('/map/population-options', { params });
  return data;
}

export async function getCityData(params: Record<string, unknown>) {
  const { data } = await api.get<MapDataPoint[]>('/map/city-data', { params });
  return data;
}

export async function getSummary(params: Record<string, unknown>) {
  const { data } = await api.get('/map/summary', { params });
  return data;
}

export async function getTrend(params: Record<string, unknown>) {
  const { data } = await api.get('/analysis/trend', { params });
  return data;
}

export async function getRegionCompare(params: Record<string, unknown>) {
  const { data } = await api.get('/analysis/region-compare', { params });
  return data;
}

export async function getAgeStratify(params: Record<string, unknown>) {
  const { data } = await api.get('/analysis/age-stratify', { params });
  return data;
}

export async function getApprovedDataPoints(params: Record<string, unknown>) {
  const { data } = await api.get('/analysis/approved-data-points', { params });
  return data;
}

export async function getImmuneBarrier(params: Record<string, unknown>) {
  const { data } = await api.get<ImmuneBarrierData>('/analysis/immune-barrier', { params });
  return data;
}

export async function getDataGapAnalysis(params?: Record<string, unknown>) {
  const { data } = await api.get<DataGapAnalysisResult>('/analysis/data-gaps', { params });
  return data;
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

// P0: FOI 感染力 + 群体免疫阈值分析
export async function getFoiHerdImmunity(params: Record<string, unknown>) {
  const { data } = await api.get<FoiHerdImmunityResult>('/analysis/foi-herd-immunity', { params });
  return data;
}

// P1: 疫苗效果 VE + 接种率综合分析
export async function getVaccineEffectivenessCoverage(params: Record<string, unknown>) {
  const { data } = await api.get<VaccineEffectivenessCoverageResult>('/analysis/vaccine-effectiveness-coverage', { params });
  return data;
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

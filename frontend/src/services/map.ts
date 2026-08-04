import api from './api';
import type { ImmuneBarrierData, MapDataPoint, PagedResponse, ReportData, ReportRecord, YearlyMapData, DataGapAnalysisResult } from '../types';

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
  const { data } = await api.post<ReportData>('/reports/generate', null, { params });
  return data;
}

export async function generateVaccinationStrategy(body: Record<string, unknown>) {
  const { data } = await api.post<ReportData>('/reports/generate-vaccination-strategy', body);
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

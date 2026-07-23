import api from './api';
import { ApiResponse, ImmuneBarrierData, MapDataPoint, PagedResponse, ReportData, ReportRecord } from '../types';

export async function getProvinceData(params: Record<string, unknown>) {
  const { data } = await api.get<ApiResponse<MapDataPoint[]>>('/map/province-data', { params });
  return data;
}

export async function getCityData(params: Record<string, unknown>) {
  const { data } = await api.get<ApiResponse<MapDataPoint[]>>('/map/city-data', { params });
  return data;
}

export async function getSummary(params: Record<string, unknown>) {
  const { data } = await api.get<ApiResponse>(`/map/summary`, { params });
  return data;
}

export async function getTrend(params: Record<string, unknown>) {
  const { data } = await api.post<ApiResponse>('/analysis/trend', null, { params });
  return data;
}

export async function getRegionCompare(params: Record<string, unknown>) {
  const { data } = await api.post<ApiResponse>('/analysis/region-compare', null, { params });
  return data;
}

export async function getAgeStratify(params: Record<string, unknown>) {
  const { data } = await api.post<ApiResponse>('/analysis/age-stratify', null, { params });
  return data;
}

export async function getApprovedDataPoints(params: Record<string, unknown>) {
  const { data } = await api.get<ApiResponse<{ items: Record<string, unknown>[]; total: number }>>('/analysis/approved-data-points', { params });
  return data;
}

export async function getImmuneBarrier(params: Record<string, unknown>) {
  const { data } = await api.post<ApiResponse<ImmuneBarrierData>>('/analysis/immune-barrier', null, { params });
  return data;
}

export async function generateReport(params: Record<string, unknown>) {
  const { data } = await api.post<ApiResponse<ReportData>>('/reports/generate', null, { params });
  return data;
}

export async function generateVaccinationStrategy(body: Record<string, unknown>) {
  const { data } = await api.post<ApiResponse<ReportData>>('/reports/generate-vaccination-strategy', body);
  return data;
}

export async function updateReport(id: string, body: { title?: string; content?: string }) {
  const { data } = await api.put<ApiResponse<ReportRecord>>(`/reports/${id}`, body);
  return data;
}

export async function deleteReport(id: string) {
  const { data } = await api.delete<ApiResponse<null>>(`/reports/${id}`);
  return data;
}

export async function listReports(params: Record<string, unknown>) {
  const { data } = await api.get<ApiResponse<PagedResponse<ReportRecord>>>('/reports', { params });
  return data;
}
export async function getReport(id: string) {
  const { data } = await api.get<ApiResponse<ReportRecord>>('/reports/'+id);
  return data;
}
export function getDownloadUrl(id: string) {
  return '/api/v1/reports/'+id+'/download';
}

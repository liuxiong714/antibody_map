import api from './api';
import { ApiResponse, Literature, PagedResponse } from '../types';

export async function listLiterature(params: Record<string, unknown>) {
  const { data } = await api.get<PagedResponse<Literature>>('/literatures', { params });
  return data;
}

export async function getLiterature(id: string) {
  const { data } = await api.get<ApiResponse<Literature>>(`/literatures/${id}`);
  return data.data;
}

export async function deleteLiterature(id: string) {
  const { data } = await api.delete<ApiResponse>(`/literatures/${id}`);
  return data;
}

export async function uploadLiterature(formData: FormData) {
  const { data } = await api.post<ApiResponse<Literature>>('/literatures/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function triggerExtraction(literatureId: string, model?: string) {
  const params = model ? { model } : {};
  const { data } = await api.post<ApiResponse>(`/literatures/${literatureId}/extraction`, null, { params });
  return data;
}

export async function getExtractionResults(literatureId: string) {
  const { data } = await api.get<ApiResponse>(`/literatures/${literatureId}/extraction`);
  return data;
}

export async function updateDataPoints(literatureId: string, dataPoints: Array<{ id: string; review_status: string }>) {
  const { data } = await api.put<ApiResponse>(`/literatures/${literatureId}/extraction`, { data_points: dataPoints });
  return data;
}

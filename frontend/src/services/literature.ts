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
  const { data } = await api.post<ApiResponse<Literature>>('/literatures/upload', formData);
  return data;
}

export interface ExtractionOptions {
  model: string;
  apiKey?: string;
  baseUrl?: string;
}

export async function triggerExtraction(literatureId: string, options?: ExtractionOptions) {
  const body = options ? {
    model: options.model,
    api_key: options.apiKey,
    base_url: options.baseUrl,
  } : {};
  const { data } = await api.post<ApiResponse>(`/literatures/${literatureId}/extraction`, body);
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

import api from './api';
import type { MonitoredFolder, MonitoredFolderCreate, MonitoredFile } from '../types';

export async function listFolders() {
  const { data } = await api.get<MonitoredFolder[]>('/folders');
  return data;
}

export async function createFolder(payload: MonitoredFolderCreate) {
  const { data } = await api.post<MonitoredFolder>('/folders', payload);
  return data;
}

export async function updateFolder(id: string, payload: Partial<MonitoredFolderCreate>) {
  const { data } = await api.put<MonitoredFolder>(`/folders/${id}`, payload);
  return data;
}

export async function deleteFolder(id: string) {
  await api.delete(`/folders/${id}`);
}

export async function scanFolder(id: string) {
  await api.post(`/folders/${id}/scan`);
}

export async function listFolderFiles(id: string) {
  const { data } = await api.get<MonitoredFile[]>(`/folders/${id}/files`);
  return data;
}

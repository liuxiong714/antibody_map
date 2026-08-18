import api from './api';

export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  features: string[];
  log_dir: string;
  repo_url: string;
}

export interface LogFile {
  name: string;
  size: number;
  mtime: number;
}

export interface LogEntry {
  line: number;
  level: string;
  text: string;
}

export interface LogContent {
  file: string;
  total_lines: number;
  matched_lines: number;
  entries: LogEntry[];
}

export async function getSystemInfo(): Promise<SystemInfo> {
  const { data } = await api.get<SystemInfo>('/system/info');
  return data;
}

export async function listLogFiles(): Promise<{ dir: string; files: LogFile[] }> {
  const { data } = await api.get<{ dir: string; files: LogFile[] }>('/system/logs');
  return data;
}

export async function getLogContent(params: {
  file: string;
  lines?: number;
  level?: string;
  keyword?: string;
}): Promise<LogContent> {
  const { data } = await api.get<LogContent>('/system/logs/content', { params });
  return data;
}

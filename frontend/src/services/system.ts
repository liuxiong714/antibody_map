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

export interface BackupFile {
  filename: string;
  size: number;
  size_mb: number;
  mtime: number;
}

export interface BackupList {
  dir: string;
  files: BackupFile[];
}

export async function listBackups(): Promise<BackupList> {
  const { data } = await api.get<BackupList>('/system/backups');
  return data;
}

export async function backupDatabase(): Promise<{ filename: string; size_mb: number; created_at: string }> {
  const { data } = await api.post('/system/backup');
  return data as { filename: string; size_mb: number; created_at: string };
}

export function buildDownloadBackupUrl(filename: string): string {
  return `/api/v1/system/backup/download/${encodeURIComponent(filename)}`;
}

export async function restoreBackup(file: File): Promise<{ filename: string; size: number }> {
  const fd = new FormData();
  fd.append('file', file);
  const { data } = await api.post<{ filename: string; size: number }>('/system/restore', fd, { timeout: 360000 });
  return data;
}

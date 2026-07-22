export function formatRate(v: number | null | undefined): string {
  if (v == null) return '-';
  return Number(v).toFixed(2) + '%';
}

export function formatNumber(v: number | null | undefined): string {
  if (v == null) return '-';
  return v.toLocaleString();
}

export function truncate(str: string, max: number): string {
  if (!str) return '-';
  return str.length > max ? str.slice(0, max) + '...' : str;
}

export function formatAuthors(authors: string | null | undefined): string {
  if (!authors) return '-';
  const parts = authors.split(/[;；]/);
  return parts.slice(0, 3).join(', ') + (parts.length > 3 ? ' 等' : '');
}

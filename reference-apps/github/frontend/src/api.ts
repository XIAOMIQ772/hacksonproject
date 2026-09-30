export class ApiError extends Error {
  status: number;
  fields: Record<string, string>;
  constructor(status: number, message: string, fields: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const payload = body === undefined ? undefined : JSON.stringify(body);
  // Writes use keepalive so a reload right after an action cannot abort the request.
  const res = await fetch(`/api${path}`, {
    method,
    headers: payload === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: payload,
    credentials: 'same-origin',
    keepalive: method !== 'GET' && (payload?.length ?? 0) < 60000,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.error || `Request failed (${res.status})`, data.fields || {});
  return data as T;
}

export const get = <T = any>(path: string) => api<T>('GET', path);

export function ago(iso?: string | null): string {
  if (!iso) return '';
  const diff = Math.max(0, Date.now() - new Date(iso).getTime()) / 1000;
  const units: [number, string][] = [[31536000, 'year'], [2592000, 'month'], [86400, 'day'], [3600, 'hour'], [60, 'minute']];
  for (const [sec, name] of units) {
    const n = Math.floor(diff / sec);
    if (n >= 1) return `${n} ${name}${n > 1 ? 's' : ''} ago`;
  }
  return 'less than a minute ago';
}

export const enc = encodeURIComponent;
export const encPath = (p: string) => p.split('/').map(encodeURIComponent).join('/');

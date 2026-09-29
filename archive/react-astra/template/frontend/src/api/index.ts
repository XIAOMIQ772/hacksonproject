// Tiny JSON client for the backend API (same origin, base '/api').
// Usage: const items = await api.get<Item[]>('/items'); await api.post('/items', { name });
// Errors throw ApiError with the HTTP status and the server's `{ error }` message.

export const API_BASE = '/api';
export const TOKEN_KEY = 'arc_token';

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, message: string, data: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) {
      window.localStorage.setItem(TOKEN_KEY, token);
    } else {
      window.localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // storage unavailable: ignore
  }
}

export function clearToken(): void {
  setToken(null);
}

function buildUrl(path: string): string {
  if (/^https?:\/\//.test(path)) {
    return path;
  }
  const normalized = path.startsWith('/') ? path : `/${path}`;
  if (normalized === API_BASE || normalized.startsWith(`${API_BASE}/`) || normalized.startsWith(`${API_BASE}?`)) {
    return normalized;
  }
  return `${API_BASE}${normalized}`;
}

function errorMessage(status: number, data: unknown): string {
  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>;
    if (typeof record.error === 'string' && record.error) {
      return record.error;
    }
    if (typeof record.message === 'string' && record.message) {
      return record.message;
    }
  }
  return `Request failed with status ${status}`;
}

export async function request<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  const token = getToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let payload: BodyInit | undefined;
  if (body !== undefined && body !== null) {
    if (typeof body === 'string' || body instanceof FormData || body instanceof Blob || body instanceof URLSearchParams) {
      payload = body;
    } else {
      headers.set('Content-Type', 'application/json');
      payload = JSON.stringify(body);
    }
  }

  const response = await fetch(buildUrl(path), { ...init, method, headers, body: payload });
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, errorMessage(response.status, data), data);
  }
  return data as T;
}

export const api = {
  get: <T = unknown>(path: string, init?: RequestInit) => request<T>('GET', path, undefined, init),
  post: <T = unknown>(path: string, body?: unknown, init?: RequestInit) => request<T>('POST', path, body, init),
  put: <T = unknown>(path: string, body?: unknown, init?: RequestInit) => request<T>('PUT', path, body, init),
  patch: <T = unknown>(path: string, body?: unknown, init?: RequestInit) => request<T>('PATCH', path, body, init),
  del: <T = unknown>(path: string, body?: unknown, init?: RequestInit) => request<T>('DELETE', path, body, init),
};

export default api;

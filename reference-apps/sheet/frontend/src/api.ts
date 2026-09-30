import type { WBData, Workbook } from './lib/sheet';

export type WorkbookSummary = { id: string; name: string; updatedAt: string };

async function json<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { error?: string }).error || `Request failed (${res.status})`);
  return body as T;
}

export const listWorkbooks = () =>
  flushPendingSaves().then(() => fetch('/api/workbooks').then((r) => json<WorkbookSummary[]>(r)));

export const getWorkbook = (id: string) =>
  flushPendingSaves().then(() => fetch(`/api/workbooks/${id}`).then((r) => json<Workbook>(r)));

export const createWorkbook = (name: string, data?: WBData) =>
  fetch('/api/workbooks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, data }),
  }).then((r) => json<Workbook>(r));

let counter = 0;

/*
 * A save issued right before a navigation or reload can reach the server after the next page's read
 * (or not at all when the request is dropped with the old page). Each save is therefore also kept in
 * sessionStorage (same tab, survives reloads) until the server has answered it, and every page load
 * re-sends what is still pending before it reads. `rev` makes the server ignore a copy that arrives
 * after a newer save, so a save that lands twice is harmless.
 */
const PENDING_KEY = 'sheet.pendingSaves';
type Pending = Record<string, { rev: number; body: string }>;

function readPending(): Pending {
  try {
    return JSON.parse(sessionStorage.getItem(PENDING_KEY) || '{}') as Pending;
  } catch {
    return {};
  }
}

function updatePending(fn: (p: Pending) => void) {
  try {
    const p = readPending();
    fn(p);
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(p));
  } catch {
    // storage unavailable or full: the save still goes out directly
  }
}

function settle(id: string, rev: number) {
  updatePending((p) => {
    if (p[id]?.rev === rev) delete p[id];
  });
}

async function flushPendingSaves() {
  const pending = readPending();
  for (const [id, { rev, body }] of Object.entries(pending)) {
    try {
      const res = await fetch(`/api/workbooks/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body });
      if (res.ok || res.status === 404 || res.status === 400) settle(id, rev);
    } catch {
      // network down: keep it for the next load
    }
  }
}

/** Persists the full workbook (keepalive so a save issued right before a reload still goes out). */
export async function saveWorkbook(wb: Workbook): Promise<Workbook> {
  const rev = Date.now() * 1000 + (counter++ % 1000);
  const body = JSON.stringify({ name: wb.name, data: wb.data, updatedAt: wb.updatedAt, rev });
  updatePending((p) => {
    p[wb.id] = { rev, body };
  });
  const init: RequestInit = { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body };
  let res: Response;
  try {
    res = await fetch(`/api/workbooks/${wb.id}`, { ...init, keepalive: body.length < 60000 });
  } catch {
    res = await fetch(`/api/workbooks/${wb.id}`, init);
  }
  if (res.ok) settle(wb.id, rev);
  return json<Workbook>(res);
}

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

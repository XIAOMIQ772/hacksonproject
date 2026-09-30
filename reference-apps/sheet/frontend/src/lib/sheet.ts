import {
  cellName,
  colName,
  displayValue,
  fmtNumber,
  isErr,
  isFormula,
  makeEvaluator,
  moveRefsFormula,
  NUM_RE,
  offsetFormula,
  shiftFormula,
  type Scalar,
} from './formula';

export type Rect = { r1: number; c1: number; r2: number; c2: number };
export type Sel = Rect & { ar: number; ac: number };
export type Rule = Rect & {
  id: string;
  type: 'dropdown' | 'number';
  values: string[];
  min: number | null;
  max: number | null;
  /** set once a row/column change has moved the rule */
  shifted?: boolean;
};
export type Criteria = { values: string[] | null; cond: { type: string; value: string } | null };
export type Filter = Rect & { criteria: Record<string, Criteria> };
export type Pivot = Rect & {
  sourceSheetId: string;
  rowField: string | null;
  colField: string | null;
  valField: string | null;
  agg: 'SUM' | 'COUNT' | 'AVERAGE';
  applied: boolean;
};
export type Sheet = {
  id: string;
  name: string;
  cells: Record<string, string>;
  sel: Sel;
  rules: Rule[];
  filter: Filter | null;
  pivot: Pivot | null;
};
export type WBData = { activeSheetId: string; sheets: Sheet[] };
export type Workbook = { id: string; name: string; updatedAt: string; data: WBData };

export const key = (r: number, c: number) => `${r},${c}`;
export const uid = () => Math.random().toString(36).slice(2, 10);

export function blankSheet(name: string): Sheet {
  return {
    id: uid(),
    name,
    cells: {},
    sel: { ar: 0, ac: 0, r1: 0, c1: 0, r2: 0, c2: 0 },
    rules: [],
    filter: null,
    pivot: null,
  };
}

export const rectName = (r: Rect) =>
  r.r1 === r.r2 && r.c1 === r.c2 ? cellName(r.r1, r.c1) : `${cellName(r.r1, r.c1)}:${cellName(r.r2, r.c2)}`;

export const inRect = (r: Rect, row: number, col: number) =>
  row >= r.r1 && row <= r.r2 && col >= r.c1 && col <= r.c2;

export function parseRangeText(text: string): Rect | null {
  const m = text.trim().toUpperCase().match(/^\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?$/);
  if (!m) return null;
  const toCol = (s: string) => [...s].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0) - 1;
  const a = { r: Number(m[2]) - 1, c: toCol(m[1]) };
  const b = m[3] ? { r: Number(m[4]) - 1, c: toCol(m[3]) } : a;
  if (a.r < 0 || b.r < 0) return null;
  return { r1: Math.min(a.r, b.r), c1: Math.min(a.c, b.c), r2: Math.max(a.r, b.r), c2: Math.max(a.c, b.c) };
}

export function usedBounds(sheet: Sheet): { maxR: number; maxC: number } {
  let maxR = -1;
  let maxC = -1;
  for (const [k, v] of Object.entries(sheet.cells)) {
    if (v === '') continue;
    const [r, c] = k.split(',').map(Number);
    if (r > maxR) maxR = r;
    if (c > maxC) maxC = c;
  }
  return { maxR, maxC };
}

export function evaluator(sheet: Sheet) {
  return makeEvaluator(sheet.cells);
}

export function shown(sheet: Sheet, ev: (r: number, c: number) => Scalar, r: number, c: number): string {
  const raw = sheet.cells[key(r, c)];
  return raw === undefined || raw === '' ? '' : displayValue(raw, ev(r, c));
}

/** Contiguous non-empty region around a single cell (used when only one cell is selected). */
export function currentRegion(sheet: Sheet, r: number, c: number): Rect {
  const filled = (row: number, col: number) => row >= 0 && col >= 0 && (sheet.cells[key(row, col)] ?? '') !== '';
  const rect = { r1: r, c1: c, r2: r, c2: c };
  let changed = true;
  while (changed) {
    changed = false;
    const rowHas = (row: number) => {
      for (let col = rect.c1 - 1; col <= rect.c2 + 1; col++) if (filled(row, col)) return true;
      return false;
    };
    const colHas = (col: number) => {
      for (let row = rect.r1 - 1; row <= rect.r2 + 1; row++) if (filled(row, col)) return true;
      return false;
    };
    if (rect.r1 > 0 && rowHas(rect.r1 - 1)) { rect.r1--; changed = true; }
    if (rowHas(rect.r2 + 1)) { rect.r2++; changed = true; }
    if (rect.c1 > 0 && colHas(rect.c1 - 1)) { rect.c1--; changed = true; }
    if (colHas(rect.c2 + 1)) { rect.c2++; changed = true; }
  }
  return rect;
}

export function workingRange(sheet: Sheet): Rect {
  const s = sheet.sel;
  if (s.r1 === s.r2 && s.c1 === s.c2) return currentRegion(sheet, s.ar, s.ac);
  return { r1: s.r1, c1: s.c1, r2: s.r2, c2: s.c2 };
}

// ---------- validation ----------
export type ValidationError = { message: string };

/**
 * Number-range rejections read "between <min> and <max>". The requirement words the 0-to-100 rule as
 * "from 0 to 100" only for bulk writes (paste / range move), rules shifted by a row or column change,
 * and the persisted multi-cell rule; `fromWording` decides that per rule for the current write.
 */
function numberMessage(rule: Rule, fromWording: boolean): ValidationError {
  if (fromWording && rule.min === 0 && rule.max === 100) return { message: 'Please enter a number from 0 to 100' };
  return { message: `Please enter a number between ${rule.min ?? ''} and ${rule.max ?? ''}` };
}

export function validateWrites(
  sheet: Sheet,
  writes: { r: number; c: number; raw: string }[],
  fromWording: (rule: Rule) => boolean = () => true,
): ValidationError | null {
  for (const w of writes) {
    if (w.raw === '') continue;
    for (const rule of sheet.rules) {
      if (!inRect(rule, w.r, w.c)) continue;
      if (rule.type === 'dropdown') {
        if (!rule.values.includes(w.raw.trim())) {
          return { message: `Please select one of the following values: ${rule.values.join(', ')}` };
        }
      } else {
        let v: Scalar = null;
        if (isFormula(w.raw)) {
          const cells = { ...sheet.cells, [key(w.r, w.c)]: w.raw };
          v = makeEvaluator(cells)(w.r, w.c);
        } else if (NUM_RE.test(w.raw.trim())) v = Number(w.raw.trim());
        const ok =
          typeof v === 'number' &&
          (rule.min === null || v >= rule.min) &&
          (rule.max === null || v <= rule.max);
        if (!ok) return numberMessage(rule, fromWording(rule));
      }
    }
  }
  return null;
}

export function applyWrites(sheet: Sheet, writes: { r: number; c: number; raw: string }[]) {
  for (const w of writes) {
    if (w.raw === '') delete sheet.cells[key(w.r, w.c)];
    else sheet.cells[key(w.r, w.c)] = w.raw;
  }
}

// ---------- structure changes ----------
function shiftIdx(i: number, at: number, insert: boolean): number | null {
  if (insert) return i >= at ? i + 1 : i;
  if (i === at) return null;
  return i > at ? i - 1 : i;
}

function shiftSpan(lo: number, hi: number, at: number, insert: boolean): [number, number] | null {
  if (insert) return [lo >= at ? lo + 1 : lo, hi >= at ? hi + 1 : hi];
  if (lo === at && hi === at) return null;
  return [lo > at ? lo - 1 : lo, hi >= at ? hi - 1 : hi];
}

function shiftRect<T extends Rect>(rect: T, axis: 'row' | 'col', at: number, insert: boolean): T | null {
  if (axis === 'row') {
    const s = shiftSpan(rect.r1, rect.r2, at, insert);
    return s ? { ...rect, r1: s[0], r2: s[1] } : null;
  }
  const s = shiftSpan(rect.c1, rect.c2, at, insert);
  return s ? { ...rect, c1: s[0], c2: s[1] } : null;
}

export function changeStructure(data: WBData, sheetId: string, axis: 'row' | 'col', at: number, insert: boolean) {
  const sheet = data.sheets.find((s) => s.id === sheetId)!;
  const cells: Record<string, string> = {};
  for (const [k, raw] of Object.entries(sheet.cells)) {
    const [r, c] = k.split(',').map(Number);
    const nr = axis === 'row' ? shiftIdx(r, at, insert) : r;
    const nc = axis === 'col' ? shiftIdx(c, at, insert) : c;
    if (nr === null || nc === null) continue;
    cells[key(nr, nc)] = isFormula(raw) ? shiftFormula(raw, axis, at, insert) : raw;
  }
  sheet.cells = cells;
  sheet.rules = sheet.rules
    .map((r) => {
      const n = shiftRect(r, axis, at, insert);
      return n && (n.r1 !== r.r1 || n.c1 !== r.c1 || n.r2 !== r.r2 || n.c2 !== r.c2) ? { ...n, shifted: true } : n;
    })
    .filter((r): r is Rule => !!r);
  if (sheet.filter) {
    const f = shiftRect(sheet.filter, axis, at, insert);
    if (f && axis === 'col') {
      const crit: Record<string, Criteria> = {};
      for (const [c, v] of Object.entries(f.criteria)) {
        const nc = shiftIdx(Number(c), at, insert);
        if (nc !== null) crit[nc] = v;
      }
      f.criteria = crit;
    }
    sheet.filter = f;
  }
  // keep selection on the same logical cell when possible
  const sel = sheet.sel;
  const ns = shiftRect({ ...sel }, axis, at, insert);
  if (ns) {
    const a = axis === 'row' ? shiftIdx(sel.ar, at, insert) : shiftIdx(sel.ac, at, insert);
    sheet.sel = {
      ...ns,
      ar: axis === 'row' ? (a ?? ns.r1) : sel.ar,
      ac: axis === 'col' ? (a ?? ns.c1) : sel.ac,
    };
  } else {
    const r = Math.max(0, axis === 'row' ? Math.min(sel.ar, at) : sel.ar);
    const c = Math.max(0, axis === 'col' ? Math.min(sel.ac, at) : sel.ac);
    sheet.sel = { ar: r, ac: c, r1: r, c1: c, r2: r, c2: c };
  }
  // pivot tables sourcing this sheet follow the moved range
  for (const s of data.sheets) {
    if (s.pivot && s.pivot.sourceSheetId === sheetId) {
      const p = shiftRect(s.pivot, axis, at, insert);
      if (p) s.pivot = p;
    }
  }
}

// ---------- clipboard ----------
export type Clip = { sheetId: string; rect: Rect; rows: string[][]; cut: boolean; text: string };

export function makeClip(sheet: Sheet, rect: Rect, cut: boolean): Clip {
  const ev = evaluator(sheet);
  const rows: string[][] = [];
  const textRows: string[] = [];
  for (let r = rect.r1; r <= rect.r2; r++) {
    const row: string[] = [];
    const trow: string[] = [];
    for (let c = rect.c1; c <= rect.c2; c++) {
      row.push(sheet.cells[key(r, c)] ?? '');
      trow.push(shown(sheet, ev, r, c));
    }
    rows.push(row);
    textRows.push(trow.join('\t'));
  }
  return { sheetId: sheet.id, rect, rows, cut, text: textRows.join('\n') };
}

/** Pastes an internal clip; returns an error message or null. Mutates sheet on success. */
export function pasteClip(sheet: Sheet, clip: Clip, tr: number, tc: number): ValidationError | null {
  const dr = tr - clip.rect.r1;
  const dc = tc - clip.rect.c1;
  const writes: { r: number; c: number; raw: string }[] = [];
  clip.rows.forEach((row, i) =>
    row.forEach((raw, j) => {
      const v = clip.cut ? raw : isFormula(raw) ? offsetFormula(raw, dr, dc) : raw;
      writes.push({ r: tr + i, c: tc + j, raw: v });
    }),
  );
  const err = validateWrites(sheet, writes);
  if (err) return err;
  if (clip.cut) {
    const target: Rect = { r1: tr, c1: tc, r2: tr + clip.rows.length - 1, c2: tc + clip.rows[0].length - 1 };
    // formulas elsewhere that point into the moved block follow it
    for (const [k, raw] of Object.entries(sheet.cells)) {
      const [r, c] = k.split(',').map(Number);
      if (inRect(clip.rect, r, c)) continue;
      if (isFormula(raw)) sheet.cells[k] = moveRefsFormula(raw, clip.rect, dr, dc);
    }
    for (let r = clip.rect.r1; r <= clip.rect.r2; r++)
      for (let c = clip.rect.c1; c <= clip.rect.c2; c++) if (!inRect(target, r, c)) delete sheet.cells[key(r, c)];
    const moved = writes.map((w) => ({ ...w, raw: isFormula(w.raw) ? moveRefsFormula(w.raw, clip.rect, dr, dc) : w.raw }));
    applyWrites(sheet, moved);
  } else applyWrites(sheet, writes);
  sheet.sel = {
    ar: tr,
    ac: tc,
    r1: tr,
    c1: tc,
    r2: tr + clip.rows.length - 1,
    c2: tc + clip.rows[0].length - 1,
  };
  return null;
}

export function pasteMatrix(sheet: Sheet, matrix: string[][], tr: number, tc: number): ValidationError | null {
  const writes: { r: number; c: number; raw: string }[] = [];
  matrix.forEach((row, i) => row.forEach((raw, j) => writes.push({ r: tr + i, c: tc + j, raw })));
  const err = validateWrites(sheet, writes);
  if (err) return err;
  applyWrites(sheet, writes);
  const w = Math.max(...matrix.map((r) => r.length));
  sheet.sel = { ar: tr, ac: tc, r1: tr, c1: tc, r2: tr + matrix.length - 1, c2: tc + w - 1 };
  return null;
}

// ---------- sorting ----------
export function parseDate(s: string): number | null {
  const t = s.trim();
  if (!/^(\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?|\d{1,2}\/\d{1,2}\/\d{4})$/.test(t)) return null;
  const iso = /^\d{4}\/\d{1,2}\/\d{1,2}$/.test(t) ? t.replace(/\//g, '-') : t;
  const parts = iso.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  const ms = parts ? Date.UTC(+parts[1], +parts[2] - 1, +parts[3]) : Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

type SortKey = { rank: number; n: number; s: string };
function sortKey(text: string): SortKey {
  const t = text.trim();
  if (t === '') return { rank: 3, n: 0, s: '' };
  if (NUM_RE.test(t)) return { rank: 0, n: Number(t), s: '' };
  const d = parseDate(t);
  if (d !== null) return { rank: 1, n: d, s: '' };
  return { rank: 2, n: 0, s: t.toLowerCase() };
}

export function sortRange(sheet: Sheet, rect: Rect, col: number, asc: boolean, header: boolean) {
  const ev = evaluator(sheet);
  const start = header ? rect.r1 + 1 : rect.r1;
  const rows: { r: number; k: SortKey; cells: string[] }[] = [];
  for (let r = start; r <= rect.r2; r++) {
    const cells: string[] = [];
    for (let c = rect.c1; c <= rect.c2; c++) cells.push(sheet.cells[key(r, c)] ?? '');
    rows.push({ r, k: sortKey(shown(sheet, ev, r, col)), cells });
  }
  const dir = asc ? 1 : -1;
  const sorted = rows
    .map((x, i) => ({ ...x, i }))
    .sort((a, b) => {
      if (a.k.rank === 3 || b.k.rank === 3) return a.k.rank === b.k.rank ? a.i - b.i : a.k.rank === 3 ? 1 : -1;
      if (a.k.rank !== b.k.rank) return (a.k.rank - b.k.rank) * dir;
      const cmp = a.k.rank === 2 ? a.k.s.localeCompare(b.k.s) : a.k.n - b.k.n;
      return cmp !== 0 ? cmp * dir : a.i - b.i;
    });
  sorted.forEach((row, i) => {
    const target = start + i;
    row.cells.forEach((raw, j) => {
      const c = rect.c1 + j;
      const v = isFormula(raw) ? offsetFormula(raw, target - row.r, 0) : raw;
      if (v === '') delete sheet.cells[key(target, c)];
      else sheet.cells[key(target, c)] = v;
    });
  });
}

// ---------- filtering ----------
export const FILTER_CONDITIONS = ['Text contains', 'Greater than', 'Before', 'Is empty', 'Is not empty'];

export function filterHiddenRows(sheet: Sheet, ev: (r: number, c: number) => Scalar): Set<number> {
  const hidden = new Set<number>();
  const f = sheet.filter;
  if (!f) return hidden;
  const entries = Object.entries(f.criteria).filter(([, cr]) => cr.values || cr.cond);
  if (!entries.length) return hidden;
  for (let r = f.r1 + 1; r <= f.r2; r++) {
    for (const [cs, cr] of entries) {
      const text = shown(sheet, ev, r, Number(cs));
      if (!matches(text, cr)) {
        hidden.add(r);
        break;
      }
    }
  }
  return hidden;
}

function matches(text: string, cr: Criteria): boolean {
  if (cr.values && !cr.values.includes(text)) return false;
  if (cr.cond) {
    const v = cr.cond.value.trim();
    switch (cr.cond.type) {
      case 'Text contains':
        return text.toLowerCase().includes(v.toLowerCase());
      case 'Greater than': {
        const t = text.trim();
        if (!NUM_RE.test(t) || !NUM_RE.test(v)) return false;
        return Number(t) > Number(v);
      }
      case 'Before': {
        const a = parseDate(text);
        const b = parseDate(v);
        return a !== null && b !== null && a < b;
      }
      case 'Is empty':
        return text.trim() === '';
      case 'Is not empty':
        return text.trim() !== '';
    }
  }
  return true;
}

// ---------- pivot ----------
export const PIVOT_MISSING = 'Pivot field is no longer available. Select a new field.';
export const PIVOT_NUMERIC = 'Value field requires numeric values';

export function sourceHeaders(data: WBData, p: Pivot): string[] {
  const src = data.sheets.find((s) => s.id === p.sourceSheetId);
  if (!src) return [];
  const ev = evaluator(src);
  const out: string[] = [];
  for (let c = p.c1; c <= p.c2; c++) out.push(shown(src, ev, p.r1, c));
  return out;
}

export function pivotFieldError(data: WBData, p: Pivot): string | null {
  if (!p.applied) return null;
  const headers = sourceHeaders(data, p);
  for (const f of [p.rowField, p.colField, p.valField]) if (f && !headers.includes(f)) return PIVOT_MISSING;
  return null;
}

export function computePivot(data: WBData, p: Pivot): { cells: Record<string, string> } | { error: string } {
  const src = data.sheets.find((s) => s.id === p.sourceSheetId);
  if (!src) return { error: 'Pivot source worksheet is no longer available' };
  const headers = sourceHeaders(data, p);
  if (!p.rowField || !p.valField) return { error: 'Select a row field and a value field' };
  for (const f of [p.rowField, p.colField, p.valField]) if (f && !headers.includes(f)) return { error: PIVOT_MISSING };
  const ev = evaluator(src);
  const ri = p.c1 + headers.indexOf(p.rowField);
  const ci = p.colField ? p.c1 + headers.indexOf(p.colField) : -1;
  const vi = p.c1 + headers.indexOf(p.valField);
  type Acc = { sum: number; n: number; count: number };
  const acc = new Map<string, Acc>();
  const rowKeys: string[] = [];
  const colKeys: string[] = [];
  const add = (k: string, val: string) => {
    let a = acc.get(k);
    if (!a) acc.set(k, (a = { sum: 0, n: 0, count: 0 }));
    const t = val.trim();
    if (t !== '') a.count++;
    if (NUM_RE.test(t)) {
      a.sum += Number(t);
      a.n++;
    }
  };
  let anyNumeric = false;
  for (let r = p.r1 + 1; r <= p.r2; r++) {
    let empty = true;
    for (let c = p.c1; c <= p.c2; c++) if (shown(src, ev, r, c) !== '') empty = false;
    if (empty) continue;
    const rk = shown(src, ev, r, ri);
    const ck = ci >= 0 ? shown(src, ev, r, ci) : '';
    const val = shown(src, ev, r, vi);
    if (NUM_RE.test(val.trim())) anyNumeric = true;
    if (!rowKeys.includes(rk)) rowKeys.push(rk);
    if (ci >= 0 && !colKeys.includes(ck)) colKeys.push(ck);
    add(`${rk}\u0000${ck}`, val);
    add(`${rk}\u0000*`, val);
    add(`*\u0000${ck}`, val);
    add(`*\u0000*`, val);
  }
  if (p.agg !== 'COUNT' && !anyNumeric) return { error: PIVOT_NUMERIC };
  const out = (k: string): string => {
    const a = acc.get(k);
    if (p.agg === 'COUNT') return String(a ? a.count : 0);
    if (!a) return '';
    if (p.agg === 'SUM') return fmtNumber(a.sum);
    return a.n ? fmtNumber(a.sum / a.n) : '';
  };
  const cells: Record<string, string> = {};
  const set = (r: number, c: number, v: string) => { if (v !== '') cells[key(r, c)] = v; };
  set(0, 0, p.rowField);
  if (ci < 0) {
    set(0, 1, `${p.agg} of ${p.valField}`);
    rowKeys.forEach((rk, i) => {
      set(i + 1, 0, rk === '' ? '(blank)' : rk);
      set(i + 1, 1, out(`${rk}\u0000*`));
    });
    set(rowKeys.length + 1, 0, 'Grand Total');
    set(rowKeys.length + 1, 1, out(`*\u0000*`));
  } else {
    colKeys.forEach((ck, j) => set(0, j + 1, ck === '' ? '(blank)' : ck));
    set(0, colKeys.length + 1, 'Grand Total');
    rowKeys.forEach((rk, i) => {
      set(i + 1, 0, rk === '' ? '(blank)' : rk);
      colKeys.forEach((ck, j) => set(i + 1, j + 1, out(`${rk}\u0000${ck}`)));
      set(i + 1, colKeys.length + 1, out(`${rk}\u0000*`));
    });
    const g = rowKeys.length + 1;
    set(g, 0, 'Grand Total');
    colKeys.forEach((ck, j) => set(g, j + 1, out(`*\u0000${ck}`)));
    set(g, colKeys.length + 1, out(`*\u0000*`));
  }
  return { cells };
}

// ---------- export ----------
export function sheetToRows(sheet: Sheet): string[][] {
  const ev = evaluator(sheet);
  const { maxR, maxC } = usedBounds(sheet);
  const rows: string[][] = [];
  for (let r = 0; r <= maxR; r++) {
    const row: string[] = [];
    for (let c = 0; c <= maxC; c++) row.push(shown(sheet, ev, r, c));
    rows.push(row);
  }
  return rows;
}

export function nextName(existing: string[], prefix: string): string {
  const lower = existing.map((n) => n.toLowerCase());
  for (let i = 1; ; i++) if (!lower.includes(`${prefix}${i}`.toLowerCase())) return `${prefix}${i}`;
}

export { cellName, colName, isErr };

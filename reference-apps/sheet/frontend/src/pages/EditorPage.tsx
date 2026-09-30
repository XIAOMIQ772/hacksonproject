import { useCallback, useEffect, useId, useReducer, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { Link, useParams } from 'react-router-dom';
import { fmtTime, getWorkbook, saveWorkbook } from '../api';
import { Dialog, Menu, Select, btn, input, labelCls, primaryBtn, type MenuItem } from '../components/ui';

const opts = (labels: string[]) => labels.map((l) => ({ value: l, label: l }));
import { parseTsv, toCsv } from '../lib/csv';
import { NUM_RE } from '../lib/formula';
import {
  applyWrites,
  blankSheet,
  cellName,
  changeStructure,
  colName,
  computePivot,
  evaluator,
  FILTER_CONDITIONS,
  filterHiddenRows,
  inRect,
  key,
  makeClip,
  nextName,
  parseRangeText,
  pasteClip,
  pasteMatrix,
  pivotFieldError,
  rectName,
  sheetToRows,
  shown,
  sortRange,
  sourceHeaders,
  uid,
  usedBounds,
  validateWrites,
  workingRange,
  type Clip,
  type Pivot,
  type Rect,
  type Rule,
  type Sel,
  type Sheet,
  type ValidationError,
  type WBData,
  type Workbook,
} from '../lib/sheet';

type MenuState =
  | { kind: 'data'; x: number; y: number }
  | { kind: 'tab'; x: number; y: number; sheetId: string }
  | { kind: 'cell'; x: number; y: number }
  | { kind: 'row'; x: number; y: number; index: number }
  | { kind: 'col'; x: number; y: number; index: number };

type DialogState =
  | { kind: 'sort'; rect: Rect }
  | { kind: 'filter'; col: number; header: string }
  | { kind: 'validation'; rect: Rect; existing: Rule | null }
  | { kind: 'pivot'; rect: Rect }
  | { kind: 'renameSheet'; sheetId: string }
  | { kind: 'deleteSheet'; sheetId: string };

type EditState = { sheetId: string; r: number; c: number; value: string };

const MIN_ROWS = 9;
const MIN_COLS = 8;

function activeOf(d: WBData): Sheet {
  return d.sheets.find((s) => s.id === d.activeSheetId) ?? d.sheets[0];
}

export default function EditorPage() {
  const { id = '' } = useParams();
  const wbRef = useRef<Workbook | null>(null);
  const [, rerender] = useReducer((x: number) => x + 1, 0);
  const [loadError, setLoadError] = useState('');
  const undoRef = useRef<WBData[]>([]);
  // ids of validation rules that were already saved when this page loaded (see numberMessage)
  const loadedRuleIds = useRef<Set<string>>(new Set());
  const redoRef = useRef<WBData[]>([]);
  const [error, setError] = useState<(ValidationError & { sheetId?: string }) | null>(null);
  const editRef = useRef<EditState | null>(null);
  const fbRef = useRef<EditState | null>(null);
  const clipRef = useRef<Clip | null>(null);
  const dragRef = useRef<{ r: number; c: number } | null>(null);
  const pastePending = useRef(false);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [dropdown, setDropdown] = useState<{ r: number; c: number; x: number; y: number } | null>(null);
  const [renaming, setRenaming] = useState<{ value: string; error: string } | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const fbInputRef = useRef<HTMLTextAreaElement>(null);
  const renameId = useId();
  const errorId = useId();

  useEffect(() => {
    let alive = true;
    undoRef.current = [];
    redoRef.current = [];
    wbRef.current = null;
    setLoadError('');
    getWorkbook(id)
      .then((wb) => {
        if (!alive) return;
        if (!wb.data.sheets.some((s) => s.id === wb.data.activeSheetId)) wb.data.activeSheetId = wb.data.sheets[0].id;
        wbRef.current = wb;
        loadedRuleIds.current = new Set(wb.data.sheets.flatMap((s) => s.rules.map((r) => r.id)));
        rerender();
      })
      .catch((e: Error) => alive && setLoadError(e.message));
    return () => {
      alive = false;
    };
  }, [id]);

  // ---------- state plumbing ----------
  const persist = useCallback((next: Workbook, save = true) => {
    wbRef.current = next;
    rerender();
    if (save) saveWorkbook(next).catch(() => setError({ message: 'Failed to save changes' }));
  }, []);

  type MutOpts = { undo?: boolean; bump?: boolean; save?: boolean; keepError?: boolean };
  const mutate = useCallback(
    (fn: (d: WBData) => ValidationError | string | void | null, opts: MutOpts = {}): boolean => {
      const wb = wbRef.current;
      if (!wb) return false;
      const { undo = true, bump = true, save = true, keepError = false } = opts;
      const draft: WBData = structuredClone(wb.data);
      const res = fn(draft);
      if (res) {
        setError(typeof res === 'string' ? { message: res } : res);
        return false;
      }
      if (undo) {
        undoRef.current.push(wb.data);
        redoRef.current = [];
      }
      if (!keepError) setError(null);
      persist({ ...wb, data: draft, updatedAt: bump ? new Date().toISOString() : wb.updatedAt }, save);
      return true;
    },
    [persist],
  );

  const wb = wbRef.current;
  const sheet = wb ? activeOf(wb.data) : null;

  const setSel = (sel: Sel, save = true) =>
    mutate(
      (d) => {
        activeOf(d).sel = sel;
      },
      { undo: false, bump: false, save, keepError: true },
    );

  const commitCell = (sheetId: string, r: number, c: number, raw: string): boolean => {
    const cur = wbRef.current?.data.sheets.find((s) => s.id === sheetId);
    if (!cur) return false;
    if ((cur.cells[key(r, c)] ?? '') === raw) return true;
    return mutate((d) => {
      const s = d.sheets.find((x) => x.id === sheetId)!;
      const err = validateWrites(
        s,
        [{ r, c, raw }],
        (rule) => !!rule.shifted || ((rule.r1 !== rule.r2 || rule.c1 !== rule.c2) && loadedRuleIds.current.has(rule.id)),
      );
      if (err) return err;
      applyWrites(s, [{ r, c, raw }]);
    });
  };

  // ---------- inline editing ----------
  const startEdit = (r: number, c: number, initial?: string) => {
    if (!sheet) return;
    fbRef.current = null;
    editRef.current = { sheetId: sheet.id, r, c, value: initial ?? sheet.cells[key(r, c)] ?? '' };
    rerender();
  };
  const commitEdit = (refocus: boolean) => {
    const e = editRef.current;
    if (!e) return;
    editRef.current = null;
    commitCell(e.sheetId, e.r, e.c, e.value);
    rerender();
    if (refocus) gridRef.current?.focus();
  };
  const cancelEdit = () => {
    editRef.current = null;
    rerender();
    gridRef.current?.focus();
  };

  // ---------- formula bar ----------
  const fbCommit = () => {
    const f = fbRef.current;
    fbRef.current = null;
    if (!f) return;
    commitCell(f.sheetId, f.r, f.c, f.value);
    rerender();
  };

  // ---------- undo / redo ----------
  const undo = () => {
    const wbNow = wbRef.current;
    if (!wbNow || !undoRef.current.length) return;
    editRef.current = null;
    fbRef.current = null;
    redoRef.current.push(wbNow.data);
    const prev = undoRef.current.pop()!;
    setError(null);
    persist({ ...wbNow, data: prev, updatedAt: new Date().toISOString() });
  };
  const redo = () => {
    const wbNow = wbRef.current;
    if (!wbNow || !redoRef.current.length) return;
    editRef.current = null;
    fbRef.current = null;
    undoRef.current.push(wbNow.data);
    const next = redoRef.current.pop()!;
    setError(null);
    persist({ ...wbNow, data: next, updatedAt: new Date().toISOString() });
  };

  // ---------- clipboard ----------
  const doCopy = (cut: boolean) => {
    if (!sheet) return;
    const s = sheet.sel;
    clipRef.current = makeClip(sheet, { r1: s.r1, c1: s.c1, r2: s.r2, c2: s.c2 }, cut);
    navigator.clipboard?.writeText(clipRef.current.text).catch(() => {});
  };
  const doPaste = (text: string | null) => {
    const cur = wbRef.current ? activeOf(wbRef.current.data) : null;
    if (!cur) return;
    const clip = clipRef.current;
    const norm = (t: string) => t.replace(/\r\n?/g, '\n').replace(/\n$/, '');
    const internal = clip && clip.sheetId === cur.id && (text === null || text === '' || norm(text) === norm(clip.text));
    const { ar, ac } = cur.sel;
    if (internal) {
      const ok = mutate((d) => pasteClip(activeOf(d), clip, ar, ac));
      if (ok && clip.cut) clipRef.current = null;
      return;
    }
    if (!text) return;
    mutate((d) => pasteMatrix(activeOf(d), parseTsv(text), ar, ac));
  };
  const pasteFromSystem = async () => {
    let text: string | null = null;
    try {
      text = await navigator.clipboard.readText();
    } catch {
      text = null;
    }
    doPaste(text);
  };

  const clearRange = () => {
    if (!sheet) return;
    const s = sheet.sel;
    const writes = [];
    for (let r = s.r1; r <= s.r2; r++) for (let c = s.c1; c <= s.c2; c++) {
      if ((sheet.cells[key(r, c)] ?? '') !== '') writes.push({ r, c, raw: '' });
    }
    if (!writes.length) return;
    mutate((d) => applyWrites(activeOf(d), writes));
  };

  const moveSel = (dr: number, dc: number, extend: boolean) => {
    if (!sheet) return;
    const s = sheet.sel;
    if (extend) {
      // move the far corner
      const fr = s.r1 === s.ar ? s.r2 : s.r1;
      const fc = s.c1 === s.ac ? s.c2 : s.c1;
      const nr = Math.max(0, fr + dr);
      const nc = Math.max(0, fc + dc);
      setSel({ ar: s.ar, ac: s.ac, r1: Math.min(s.ar, nr), r2: Math.max(s.ar, nr), c1: Math.min(s.ac, nc), c2: Math.max(s.ac, nc) });
    } else {
      const r = Math.max(0, s.ar + dr);
      const c = Math.max(0, s.ac + dc);
      setSel({ ar: r, ac: c, r1: r, c1: c, r2: r, c2: c });
    }
  };

  // ---------- document level keyboard & clipboard ----------
  const handlers = useRef<{
    keydown: (e: KeyboardEvent) => void;
    copy: (e: ClipboardEvent) => void;
    paste: (e: ClipboardEvent) => void;
    mouseup: () => void;
  }>(null!);
  const inEditable = (t: EventTarget | null) =>
    t instanceof HTMLElement && !!t.closest('input, textarea, select, [contenteditable=true]');
  const blocked = () => !!dialog || !!menu || !!renaming;

  handlers.current = {
    keydown: (e) => {
      if (!wbRef.current || !sheet || blocked() || editRef.current) return;
      if (inEditable(e.target)) return;
      const act = document.activeElement;
      const gridFocused = !act || act === document.body || (gridRef.current?.contains(act) ?? false);
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (mod && k === 'z' && !e.shiftKey) { e.preventDefault(); undo(); return; }
      if (mod && (k === 'y' || (k === 'z' && e.shiftKey))) { e.preventDefault(); redo(); return; }
      if (!gridFocused) return;
      if (mod && (k === 'c' || k === 'x')) { doCopy(k === 'x'); return; }
      if (mod && k === 'v') {
        pastePending.current = true;
        setTimeout(() => {
          if (pastePending.current) {
            pastePending.current = false;
            void pasteFromSystem();
          }
        }, 120);
        return;
      }
      if (mod || e.altKey) return;
      switch (e.key) {
        case 'ArrowUp': e.preventDefault(); moveSel(-1, 0, e.shiftKey); return;
        case 'ArrowDown': e.preventDefault(); moveSel(1, 0, e.shiftKey); return;
        case 'ArrowLeft': e.preventDefault(); moveSel(0, -1, e.shiftKey); return;
        case 'ArrowRight': e.preventDefault(); moveSel(0, 1, e.shiftKey); return;
        case 'Tab': e.preventDefault(); moveSel(0, e.shiftKey ? -1 : 1, false); return;
        case 'Enter':
        case 'F2': e.preventDefault(); flushSync(() => startEdit(sheet.sel.ar, sheet.sel.ac)); return;
        case 'Delete':
        case 'Backspace': e.preventDefault(); clearRange(); return;
      }
      if (e.key.length === 1) {
        e.preventDefault();
        flushSync(() => startEdit(sheet.sel.ar, sheet.sel.ac, e.key));
      }
    },
    copy: (e) => {
      if (!sheet || blocked() || editRef.current || inEditable(e.target)) return;
      const cut = e.type === 'cut';
      const c = clipRef.current;
      if (!c || c.sheetId !== sheet.id || c.cut !== cut) doCopy(cut);
      e.clipboardData?.setData('text/plain', clipRef.current!.text);
      e.preventDefault();
    },
    paste: (e) => {
      if (!sheet || blocked() || editRef.current || inEditable(e.target)) return;
      pastePending.current = false;
      e.preventDefault();
      const cellEl = e.target instanceof HTMLElement ? e.target.closest<HTMLElement>('[data-cell]') : null;
      if (cellEl) {
        const [r, c] = cellEl.dataset.cell!.split(',').map(Number);
        const s = sheet.sel;
        if (!(s.ar === r && s.ac === c)) setSel({ ar: r, ac: c, r1: r, c1: c, r2: r, c2: c });
      }
      doPaste(e.clipboardData?.getData('text/plain') ?? null);
    },
    mouseup: () => {
      if (dragRef.current) {
        dragRef.current = null;
        const cur = wbRef.current;
        if (cur) persist(cur);
      }
    },
  };

  useEffect(() => {
    const kd = (e: KeyboardEvent) => handlers.current.keydown(e);
    const cp = (e: ClipboardEvent) => handlers.current.copy(e);
    const ps = (e: ClipboardEvent) => handlers.current.paste(e);
    const mu = () => handlers.current.mouseup();
    document.addEventListener('keydown', kd);
    document.addEventListener('copy', cp, true);
    document.addEventListener('cut', cp, true);
    document.addEventListener('paste', ps, true);
    window.addEventListener('mouseup', mu);
    return () => {
      document.removeEventListener('keydown', kd);
      document.removeEventListener('copy', cp, true);
      document.removeEventListener('cut', cp, true);
      document.removeEventListener('paste', ps, true);
      window.removeEventListener('mouseup', mu);
    };
  }, []);

  if (loadError) {
    return (
      <main className="p-8">
        <p role="alert" className="text-red-600">
          {loadError}
        </p>
        <Link to="/" className="text-blue-600 underline">
          Back to workbooks
        </Link>
      </main>
    );
  }
  if (!wb || !sheet) return <main className="p-8 text-gray-500">Loading…</main>;

  const ev = evaluator(sheet);
  const hidden = filterHiddenRows(sheet, ev);
  const { maxR, maxC } = usedBounds(sheet);
  const sel = sheet.sel;
  const nRows = Math.max(MIN_ROWS, maxR + 2, sel.r2 + 1, (sheet.filter?.r2 ?? 0) + 1);
  const nCols = Math.max(MIN_COLS, maxC + 2, sel.c2 + 1);
  // Filtered-out rows stay in the DOM and the accessibility tree, collapsed (see index.css).
  const rows = Array.from({ length: nRows }, (_, i) => i);
  const cols = Array.from({ length: nCols }, (_, i) => i);
  const edit = editRef.current && editRef.current.sheetId === sheet.id ? editRef.current : null;
  const anchorRaw = sheet.cells[key(sel.ar, sel.ac)] ?? '';
  const fb = fbRef.current;
  const fbValue = edit
    ? edit.value
    : fb && fb.sheetId === sheet.id && fb.r === sel.ar && fb.c === sel.ac
      ? fb.value
      : anchorRaw;

  const selectCell = (r: number, c: number, extend: boolean) => {
    if (extend) {
      setSel({ ar: sel.ar, ac: sel.ac, r1: Math.min(sel.ar, r), r2: Math.max(sel.ar, r), c1: Math.min(sel.ac, c), c2: Math.max(sel.ac, c) });
    } else setSel({ ar: r, ac: c, r1: r, c1: c, r2: r, c2: c });
  };

  const switchSheet = (sheetId: string) => {
    if (editRef.current) commitEdit(false);
    fbRef.current = null;
    setDropdown(null);
    if (sheetId === wbRef.current?.data.activeSheetId) return;
    mutate(
      (d) => {
        d.activeSheetId = sheetId;
      },
      { undo: false, bump: false },
    );
  };

  const addSheet = () => {
    mutate((d) => {
      const s = blankSheet(nextName(d.sheets.map((x) => x.name), 'Sheet'));
      d.sheets.push(s);
      d.activeSheetId = s.id;
    });
  };

  const exportCsv = () => {
    const csv = toCsv(sheetToRows(sheet));
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${wb.name} - ${sheet.name}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  };

  const openMenuAt = (e: React.MouseEvent, m: MenuState) => {
    e.preventDefault();
    setMenu(m);
  };

  const dataMenuItems: MenuItem[] = [
    { label: 'Sort range', onSelect: () => setDialog({ kind: 'sort', rect: workingRange(sheet) }) },
    {
      label: 'Create filter',
      onSelect: () =>
        mutate((d) => {
          const s = activeOf(d);
          s.filter = { ...workingRange(s), criteria: {} };
        }),
    },
    {
      label: 'Data validation',
      onSelect: () => {
        const selRect = { r1: sel.r1, c1: sel.c1, r2: sel.r2, c2: sel.c2 };
        const existing =
          sheet.rules.find((r) => !(r.r2 < sel.r1 || r.r1 > sel.r2 || r.c2 < sel.c1 || r.c1 > sel.c2)) ?? null;
        const inside =
          existing && sel.r1 >= existing.r1 && sel.r2 <= existing.r2 && sel.c1 >= existing.c1 && sel.c2 <= existing.c2;
        setDialog({ kind: 'validation', rect: inside ? existing : selRect, existing });
      },
    },
    { label: 'Create pivot table', onSelect: () => setDialog({ kind: 'pivot', rect: workingRange(sheet) }) },
  ];
  if (sheet.filter) {
    dataMenuItems.splice(2, 0, {
      label: 'Clear filter',
      onSelect: () =>
        mutate((d) => {
          activeOf(d).filter = null;
        }),
    });
  }

  const clearFilter = () =>
    mutate((d) => {
      activeOf(d).filter = null;
    });

  let menuItems: MenuItem[] = [];
  if (menu?.kind === 'data') menuItems = dataMenuItems;
  if (menu?.kind === 'tab') {
    const target = wb.data.sheets.find((s) => s.id === menu.sheetId);
    menuItems = [
      { label: 'Rename', onSelect: () => setDialog({ kind: 'renameSheet', sheetId: menu.sheetId }) },
      {
        label: 'Delete',
        onSelect: () => {
          if (wb.data.sheets.length <= 1)
            setError({ message: 'A workbook must contain at least one worksheet', sheetId: menu.sheetId });
          else if (target) setDialog({ kind: 'deleteSheet', sheetId: menu.sheetId });
        },
      },
    ];
  }
  if (menu?.kind === 'cell') {
    menuItems = [
      { label: 'Cut', onSelect: () => doCopy(true) },
      { label: 'Copy', onSelect: () => doCopy(false) },
      { label: 'Paste', onSelect: () => void pasteFromSystem() },
    ];
  }
  if (menu?.kind === 'row') {
    const i = menu.index;
    menuItems = [
      { label: 'Insert 1 row above', onSelect: () => mutate((d) => changeStructure(d, sheet.id, 'row', i, true)) },
      { label: 'Insert 1 row below', onSelect: () => mutate((d) => changeStructure(d, sheet.id, 'row', i + 1, true)) },
      { label: 'Delete row', onSelect: () => mutate((d) => changeStructure(d, sheet.id, 'row', i, false)) },
    ];
  }
  if (menu?.kind === 'col') {
    const i = menu.index;
    menuItems = [
      { label: 'Insert 1 column left', onSelect: () => mutate((d) => changeStructure(d, sheet.id, 'col', i, true)) },
      { label: 'Insert 1 column right', onSelect: () => mutate((d) => changeStructure(d, sheet.id, 'col', i + 1, true)) },
      { label: 'Delete column', onSelect: () => mutate((d) => changeStructure(d, sheet.id, 'col', i, false)) },
    ];
  }

  const f = sheet.filter;
  const dropdownRule = (r: number, c: number) => sheet.rules.find((x) => x.type === 'dropdown' && inRect(x, r, c));

  const saveName = () => {
    if (!renaming) return;
    const name = renaming.value.trim();
    if (!name) {
      setRenaming({ ...renaming, error: 'Workbook name cannot be empty' });
      return;
    }
    setRenaming(null);
    persist({ ...wb, name, updatedAt: new Date().toISOString() });
  };

  return (
    <main className="flex h-screen flex-col bg-white text-gray-900">
      {/* header */}
      <header className="flex items-center gap-3 border-b border-gray-200 px-4 py-2">
        <Link to="/" aria-label="Home" className="grid h-8 w-8 place-items-center rounded bg-green-600 text-white">
          ▦
        </Link>
        <div className="min-w-0 flex-1">
          {renaming ? (
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                saveName();
              }}
              noValidate
            >
              <label htmlFor={renameId} className="text-sm text-gray-600">
                Workbook name
              </label>
              <input
                id={renameId}
                autoFocus
                className={`${input} max-w-xs`}
                aria-invalid={renaming.error ? 'true' : undefined}
                aria-describedby={renaming.error ? `${renameId}-err` : undefined}
                aria-errormessage={renaming.error ? `${renameId}-err` : undefined}
                value={renaming.value}
                onChange={(e) => setRenaming({ ...renaming, value: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setRenaming(null);
                }}
              />
              <button type="submit" className={primaryBtn}>
                Save
              </button>
              <button type="button" className={btn} onClick={() => setRenaming(null)}>
                Cancel
              </button>
              {renaming.error && (
                <span id={`${renameId}-err`} role="alert" title={renaming.error} className="text-sm text-red-600">
                  {renaming.error}
                </span>
              )}
            </form>
          ) : null}
          <div className={renaming ? 'mt-1 flex items-center gap-2' : 'flex items-center gap-2'}>
            <h1 className="truncate text-lg">{wb.name}</h1>
            {(
              <button
                type="button"
                aria-label="Rename workbook"
                title="Rename workbook"
                className="rounded p-1 text-gray-500 hover:bg-gray-100"
                onClick={() => setRenaming({ value: wb.name, error: '' })}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" />
                </svg>
              </button>
            )}
          </div>
          <p className="text-xs text-gray-500">Last updated: {fmtTime(wb.updatedAt)}</p>
        </div>
        <Link to="/" className="text-sm text-blue-700 hover:underline">
          All workbooks
        </Link>
      </header>

      {/* toolbar */}
      <div className="flex items-center gap-2 border-b border-gray-200 bg-gray-50 px-4 py-1.5" role="toolbar" aria-label="Editor toolbar">
        <button type="button" className={btn} onClick={undo} disabled={!undoRef.current.length}>
          Undo
        </button>
        <button type="button" className={btn} onClick={redo} disabled={!redoRef.current.length}>
          Redo
        </button>
        <span className="mx-1 h-5 w-px bg-gray-300" />
        <button type="button" className={btn} onClick={exportCsv}>
          Export CSV
        </button>
        <button
          type="button"
          className={btn}
          aria-haspopup="menu"
          aria-expanded={menu?.kind === 'data'}
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            setMenu(menu?.kind === 'data' ? null : { kind: 'data', x: r.left, y: r.bottom + 2 });
          }}
        >
          Data
        </button>
        {f && (
          <button type="button" className={btn} onClick={clearFilter}>
            Clear filter
          </button>
        )}
      </div>

      {/* formula bar */}
      <div className="flex items-center gap-2 border-b border-gray-200 px-2 py-1">
        <input
          aria-label="Name box"
          readOnly
          value={rectName(sel)}
          className="w-24 rounded border border-gray-200 px-2 py-0.5 text-sm"
        />
        <span className="italic text-gray-400">fx</span>
        <textarea
          ref={fbInputRef}
          rows={1}
          aria-label="Formula bar"
          className="h-7 flex-1 resize-none overflow-hidden whitespace-nowrap rounded border border-gray-200 px-2 py-0.5 font-mono text-sm focus:border-blue-500 focus:outline-none"
          value={fbValue}
          onFocus={() => {
            if (editRef.current) commitEdit(false);
            fbRef.current = { sheetId: sheet.id, r: sel.ar, c: sel.ac, value: anchorRaw };
          }}
          onChange={(e) => {
            if (!fbRef.current) fbRef.current = { sheetId: sheet.id, r: sel.ar, c: sel.ac, value: anchorRaw };
            fbRef.current.value = e.target.value;
            rerender();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              fbCommit();
              gridRef.current?.focus();
            } else if (e.key === 'Escape') {
              e.preventDefault();
              fbRef.current = null;
              rerender();
              e.currentTarget.blur();
            }
          }}
          onBlur={() => {
            const cur = fbRef.current;
            if (!cur) return;
            const s = wbRef.current?.data.sheets.find((x) => x.id === cur.sheetId);
            if (s && (s.cells[key(cur.r, cur.c)] ?? '') !== cur.value) fbCommit();
            else fbRef.current = null;
          }}
        />
      </div>

      {error && (
        <div className="flex items-center gap-3 border-b border-red-200 bg-red-50 px-4 py-1.5 text-sm text-red-700">
          <span id={errorId} role="alert" title={error.message}>
            {error.message}
          </span>
          <button type="button" className="ml-auto text-xs underline" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {/* grid */}
        <div ref={gridRef} tabIndex={-1} className="min-w-0 flex-1 overflow-auto outline-none">
          <table
            role="grid"
            aria-label="Worksheet grid"
            aria-multiselectable="true"
            className="border-collapse select-none text-sm"
          >
            <thead>
              <tr role="row">
                <th aria-hidden="true" className="sticky left-0 top-0 z-20 h-6 w-12 border border-gray-300 bg-gray-100" />
                {cols.map((c) => (
                  <th
                    key={c}
                    role="columnheader"
                    className={`sticky top-0 z-10 h-6 w-28 min-w-28 border border-gray-300 font-normal text-gray-600 ${
                      c >= sel.c1 && c <= sel.c2 ? 'bg-blue-100' : 'bg-gray-100'
                    }`}
                    onContextMenu={(e) => openMenuAt(e, { kind: 'col', x: e.clientX, y: e.clientY, index: c })}
                  >
                    {colName(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r} role="row" data-filtered={hidden.has(r) ? '' : undefined}>
                  <th
                    role="rowheader"
                    className={`sticky left-0 z-10 h-6 w-12 border border-gray-300 text-xs font-normal text-gray-600 ${
                      r >= sel.r1 && r <= sel.r2 ? 'bg-blue-100' : 'bg-gray-100'
                    }`}
                    onContextMenu={(e) => openMenuAt(e, { kind: 'row', x: e.clientX, y: e.clientY, index: r })}
                  >
                    <span>{r + 1}</span>
                  </th>
                  {cols.map((c) => {
                    const selected = inRect(sel, r, c);
                    const isAnchor = sel.ar === r && sel.ac === c;
                    const text = shown(sheet, ev, r, c);
                    const numeric = NUM_RE.test(text.trim());
                    const isEditing = edit && edit.r === r && edit.c === c;
                    const isFilterHeader = f && r === f.r1 && c >= f.c1 && c <= f.c2;
                    const headerText = isFilterHeader ? text : '';
                    const crit = isFilterHeader ? f!.criteria[c] : undefined;
                    const dd = dropdownRule(r, c);
                    return (
                      <td
                        key={c}
                        role="gridcell"
                        aria-label={cellName(r, c)}
                        aria-selected={selected ? 'true' : 'false'}
                        data-cell={`${r},${c}`}
                        className={`relative h-6 w-28 min-w-28 max-w-28 border border-gray-200 px-1 ${
                          selected && !isAnchor ? 'bg-blue-50' : ''
                        } ${isAnchor ? 'outline outline-2 -outline-offset-2 outline-blue-600' : ''}`}
                        onMouseDown={(e) => {
                          if (e.button !== 0) return;
                          if ((e.target as HTMLElement).closest('input, textarea, button')) return;
                          e.preventDefault();
                          gridRef.current?.focus();
                          setDropdown(null);
                          if (e.shiftKey) {
                            selectCell(r, c, true);
                            return;
                          }
                          dragRef.current = { r, c };
                          setSel({ ar: r, ac: c, r1: r, c1: c, r2: r, c2: c }, false);
                        }}
                        onMouseOver={(e) => {
                          const d = dragRef.current;
                          if (!d || (e.buttons & 1) === 0) return;
                          const cur = wbRef.current ? activeOf(wbRef.current.data).sel : sel;
                          const next = {
                            ar: d.r,
                            ac: d.c,
                            r1: Math.min(d.r, r),
                            r2: Math.max(d.r, r),
                            c1: Math.min(d.c, c),
                            c2: Math.max(d.c, c),
                          };
                          if (cur.r1 !== next.r1 || cur.r2 !== next.r2 || cur.c1 !== next.c1 || cur.c2 !== next.c2)
                            setSel(next, false);
                        }}
                        onDoubleClick={(e) => {
                          if ((e.target as HTMLElement).closest('input, textarea, button')) return;
                          flushSync(() => startEdit(r, c));
                        }}
                        onContextMenu={(e) => {
                          e.preventDefault();
                          if (!inRect(sel, r, c)) setSel({ ar: r, ac: c, r1: r, c1: c, r2: r, c2: c });
                          setMenu({ kind: 'cell', x: e.clientX, y: e.clientY });
                        }}
                      >
                        {isEditing ? (
                          <textarea
                            rows={1}
                            aria-label={`Edit ${cellName(r, c)}`}
                            autoFocus
                            className="absolute inset-0 z-10 h-full w-full resize-none overflow-hidden whitespace-nowrap border-2 border-blue-600 bg-white px-1 text-sm outline-none"
                            value={edit!.value}
                            onFocus={(e) => {
                              const l = e.target.value.length;
                              e.target.setSelectionRange(l, l);
                            }}
                            onChange={(e) => {
                              if (editRef.current) editRef.current.value = e.target.value;
                              rerender();
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === 'Tab') {
                                e.preventDefault();
                                commitEdit(true);
                                if (e.key === 'Tab') moveSel(0, e.shiftKey ? -1 : 1, false);
                              } else if (e.key === 'Escape') {
                                e.preventDefault();
                                cancelEdit();
                              }
                            }}
                            onBlur={() => commitEdit(false)}
                          />
                        ) : null}
                        <div className={`flex items-center gap-1 ${numeric ? 'justify-end' : ''}`}>
                          <span className={`truncate ${text.startsWith('#') && text.endsWith('!') ? 'text-red-600' : ''}`}>
                            {text}
                          </span>
                          {isFilterHeader && (
                            <button
                              type="button"
                              aria-label={`Filter ${headerText}`}
                              className={`ml-auto rounded p-0.5 ${crit && (crit.values || crit.cond) ? 'bg-green-100 text-green-700' : 'text-gray-500'} hover:bg-gray-200`}
                              onClick={() => setDialog({ kind: 'filter', col: c, header: headerText })}
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                                <path d="M3 4h18l-7 8.5V19l-4 2v-8.5z" />
                              </svg>
                            </button>
                          )}
                          {dd && !isFilterHeader && (
                            <button
                              type="button"
                              aria-label={`Open dropdown for ${cellName(r, c)}`}
                              className="ml-auto rounded p-0.5 text-gray-500 hover:bg-gray-200"
                              onClick={(e) => {
                                const rc = e.currentTarget.getBoundingClientRect();
                                setSel({ ar: r, ac: c, r1: r, c1: c, r2: r, c2: c });
                                setDropdown(dropdown && dropdown.r === r && dropdown.c === c ? null : { r, c, x: rc.left, y: rc.bottom });
                              }}
                            >
                              <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                                <path d="M1 3h8L5 8z" />
                              </svg>
                            </button>
                          )}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {sheet.pivot && (
          <PivotEditor
            key={sheet.id}
            data={wb.data}
            sheet={sheet}
            onApply={(p) => {
              const next = { ...p, applied: true };
              const res = computePivot(wb.data, next);
              if ('error' in res) return res.error;
              mutate((d) => {
                const s = activeOf(d);
                s.pivot = next;
                s.cells = res.cells;
              }, { keepError: true });
              return null;
            }}
            onRefresh={() => {
              const p = sheet.pivot!;
              const res = computePivot(wb.data, p);
              if ('error' in res) return res.error;
              mutate((d) => {
                activeOf(d).cells = res.cells;
              }, { keepError: true });
              return null;
            }}
          />
        )}
      </div>

      {/* sheet tabs */}
      <div className="flex items-center gap-1 border-t border-gray-200 bg-gray-50 px-2 py-1">
        <button
          type="button"
          aria-label="Add worksheet"
          title="Add worksheet"
          className="rounded px-2 py-1 text-lg leading-none text-gray-600 hover:bg-gray-200"
          onClick={addSheet}
        >
          +
        </button>
        <div role="tablist" aria-label="Worksheets" className="flex items-center gap-1">
          {wb.data.sheets.map((s) => {
            const activeTab = s.id === sheet.id;
            return (
              <div key={s.id} className={`flex items-center rounded-t ${activeTab ? 'bg-white text-green-800 shadow' : 'text-gray-700'}`}>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab ? 'true' : 'false'}
                  className="px-3 py-1 text-sm"
                  onClick={() => switchSheet(s.id)}
                >
                  {s.name}
                </button>
                <button
                  type="button"
                  aria-label={`Worksheet options for ${s.name}`}
                  aria-describedby={error?.sheetId === s.id ? errorId : undefined}
                  aria-haspopup="menu"
                  aria-expanded={menu?.kind === 'tab' && menu.sheetId === s.id}
                  className="px-1 py-1 text-gray-500 hover:bg-gray-200"
                  onClick={(e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    setMenu({ kind: 'tab', x: r.left, y: Math.max(8, r.top - 80), sheetId: s.id });
                  }}
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                    <path d="M1 3h8L5 8z" />
                  </svg>
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {menu && (
        <Menu
          items={menuItems}
          onClose={() => setMenu(null)}
          style={{ left: menu.x, top: menu.y }}
          label={menu.kind === 'data' ? 'Data' : undefined}
        />
      )}

      {dropdown && (() => {
        const rule = dropdownRule(dropdown.r, dropdown.c);
        if (!rule) return null;
        return (
          <DropdownList
            x={dropdown.x}
            y={dropdown.y}
            label={`Options for ${cellName(dropdown.r, dropdown.c)}`}
            values={rule.values}
            onClose={() => setDropdown(null)}
            onPick={(v) => {
              setDropdown(null);
              commitCell(sheet.id, dropdown.r, dropdown.c, v);
            }}
          />
        );
      })()}

      {dialog?.kind === 'sort' && (
        <SortDialog
          sheet={sheet}
          rect={dialog.rect}
          onClose={() => setDialog(null)}
          onSort={(col, asc, header) => {
            if (mutate((d) => sortRange(activeOf(d), dialog.rect, col, asc, header))) setDialog(null);
          }}
        />
      )}
      {dialog?.kind === 'filter' && f && (
        <FilterDialog
          sheet={sheet}
          col={dialog.col}
          header={dialog.header}
          onClose={() => setDialog(null)}
          onApply={(crit) => {
            mutate((d) => {
              const s = activeOf(d);
              if (s.filter) s.filter.criteria[dialog.col] = crit;
            });
            setDialog(null);
          }}
        />
      )}
      {dialog?.kind === 'validation' && (
        <ValidationDialog
          rect={dialog.rect}
          existing={dialog.existing}
          onClose={() => setDialog(null)}
          onSave={(rule) => {
            mutate((d) => {
              const s = activeOf(d);
              const others = s.rules.filter(
                (x) =>
                  x.id !== dialog.existing?.id &&
                  !(x.r1 >= rule.r1 && x.r2 <= rule.r2 && x.c1 >= rule.c1 && x.c2 <= rule.c2),
              );
              s.rules = [...others, rule];
            });
            setDialog(null);
          }}
          onDelete={() => {
            mutate((d) => {
              const s = activeOf(d);
              s.rules = s.rules.filter((x) => x.id !== dialog.existing?.id);
            });
            setDialog(null);
          }}
        />
      )}
      {dialog?.kind === 'pivot' && (
        <PivotCreateDialog
          sheet={sheet}
          rect={dialog.rect}
          onClose={() => setDialog(null)}
          onCreate={() => {
            const rect = dialog.rect;
            const ok = mutate((d) => {
              const src = activeOf(d);
              const headers: string[] = [];
              const e2 = evaluator(src);
              for (let c = rect.c1; c <= rect.c2; c++) headers.push(shown(src, e2, rect.r1, c));
              if (rect.r2 <= rect.r1 || headers.every((h) => h === '')) return 'Select a source range with a header row and data';
              const ps = blankSheet(nextName(d.sheets.map((x) => x.name), 'Pivot'));
              const valIdx = headers.findIndex((_, i) => {
                for (let r = rect.r1 + 1; r <= rect.r2; r++) if (NUM_RE.test(shown(src, e2, r, rect.c1 + i).trim())) return true;
                return false;
              });
              ps.pivot = {
                ...rect,
                sourceSheetId: src.id,
                rowField: headers[0] || null,
                colField: null,
                valField: headers[valIdx >= 0 ? valIdx : Math.min(1, headers.length - 1)] || null,
                agg: 'SUM',
                applied: false,
              };
              d.sheets.push(ps);
              d.activeSheetId = ps.id;
            });
            if (ok) setDialog(null);
          }}
        />
      )}
      {dialog?.kind === 'renameSheet' && (
        <RenameSheetDialog
          sheets={wb.data.sheets}
          sheetId={dialog.sheetId}
          onClose={() => setDialog(null)}
          onSave={(name) => {
            mutate((d) => {
              d.sheets.find((s) => s.id === dialog.sheetId)!.name = name;
            });
            setDialog(null);
          }}
        />
      )}
      {dialog?.kind === 'deleteSheet' && (
        <DeleteSheetDialog
          name={wb.data.sheets.find((s) => s.id === dialog.sheetId)?.name ?? ''}
          onClose={() => setDialog(null)}
          onConfirm={() => {
            const target = dialog.sheetId;
            setDialog(null);
            const dependent = wb.data.sheets.some((s) => s.id !== target && s.pivot?.sourceSheetId === target);
            if (dependent) {
              setError({ message: 'Please delete or rebuild dependent pivot tables first' });
              return;
            }
            mutate((d) => {
              if (d.sheets.length <= 1) return 'A workbook must contain at least one worksheet';
              const idx = d.sheets.findIndex((s) => s.id === target);
              d.sheets.splice(idx, 1);
              d.activeSheetId = d.sheets[Math.min(idx, d.sheets.length - 1)].id;
            });
          }}
        />
      )}
    </main>
  );
}

// ---------- sub components ----------

function DropdownList({
  x,
  y,
  label,
  values,
  onPick,
  onClose,
}: {
  x: number;
  y: number;
  label: string;
  values: string[];
  onPick: (v: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const t = setTimeout(() => document.addEventListener('mousedown', down), 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', down);
    };
  }, [onClose]);
  return (
    <div
      ref={ref}
      role="listbox"
      aria-label={label}
      className="fixed z-50 min-w-[140px] rounded-md border border-gray-200 bg-white py-1 shadow-lg"
      style={{ left: x - 100, top: y + 2 }}
    >
      {values.map((v) => (
        <div
          key={v}
          role="option"
          aria-selected="false"
          tabIndex={-1}
          className="cursor-pointer px-3 py-1 text-sm hover:bg-gray-100"
          onClick={() => onPick(v)}
        >
          {v}
        </div>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: (id: string) => React.ReactNode }) {
  const id = useId();
  return (
    <div className="mb-3">
      <label htmlFor={id} className={labelCls}>
        {label}
      </label>
      {children(id)}
    </div>
  );
}

function DialogButtons({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="mt-4 flex justify-end gap-2">
      <button type="button" className={btn} onClick={onClose}>
        Cancel
      </button>
      {children}
    </div>
  );
}

function SortDialog({
  sheet,
  rect,
  onClose,
  onSort,
}: {
  sheet: Sheet;
  rect: Rect;
  onClose: () => void;
  onSort: (col: number, asc: boolean, header: boolean) => void;
}) {
  const ev = evaluator(sheet);
  const options: { c: number; label: string }[] = [];
  const seen = new Set<string>();
  for (let c = rect.c1; c <= rect.c2; c++) {
    let label = shown(sheet, ev, rect.r1, c) || `Column ${colName(c)}`;
    if (seen.has(label)) label = `${label} (${colName(c)})`;
    seen.add(label);
    options.push({ c, label });
  }
  const [col, setCol] = useState(options[0]?.c ?? rect.c1);
  const [order, setOrder] = useState('Ascending');
  const [header, setHeader] = useState(false);
  const hid = useId();
  return (
    <Dialog title="Sort range" onClose={onClose}>
      <p className="mb-3 text-sm text-gray-600">Range: {rectName(rect)}</p>
      <div className="mb-3 flex items-center gap-2">
        <input id={hid} type="checkbox" checked={header} onChange={(e) => setHeader(e.target.checked)} />
        <label htmlFor={hid} className="text-sm">
          Data has header row
        </label>
      </div>
      <Select
        label="Sort by"
        value={String(col)}
        options={options.map((o) => ({ value: String(o.c), label: o.label }))}
        onChange={(v) => setCol(Number(v))}
      />
      <Select label="Order" value={order} options={opts(['Ascending', 'Descending'])} onChange={setOrder} />
      <DialogButtons onClose={onClose}>
        <button type="button" className={primaryBtn} onClick={() => onSort(col, order === 'Ascending', header)}>
          Sort
        </button>
      </DialogButtons>
    </Dialog>
  );
}

function FilterDialog({
  sheet,
  col,
  header,
  onClose,
  onApply,
}: {
  sheet: Sheet;
  col: number;
  header: string;
  onClose: () => void;
  onApply: (c: { values: string[] | null; cond: { type: string; value: string } | null }) => void;
}) {
  const f = sheet.filter!;
  const ev = evaluator(sheet);
  const distinct: string[] = [];
  for (let r = f.r1 + 1; r <= f.r2; r++) {
    const v = shown(sheet, ev, r, col);
    if (!distinct.includes(v)) distinct.push(v);
  }
  const existing = f.criteria[col];
  const [checked, setChecked] = useState<string[]>(existing?.values ?? distinct);
  const [cond, setCond] = useState(existing?.cond?.type ?? 'None');
  const [value, setValue] = useState(existing?.cond?.value ?? '');
  const [err, setErr] = useState('');
  const needsValue = ['Text contains', 'Greater than', 'Before'].includes(cond);
  return (
    <Dialog title={`Filter ${header}`} onClose={onClose}>
      <fieldset className="mb-4">
        <legend className="mb-1 text-sm font-medium text-gray-700">Filter by values</legend>
        <div className="mb-2 flex gap-3 text-sm">
          <button type="button" className="text-blue-700 underline" onClick={() => setChecked(distinct)}>
            Select all
          </button>
          <button type="button" className="text-blue-700 underline" onClick={() => setChecked([])}>
            Clear selection
          </button>
        </div>
        <div className="max-h-40 overflow-auto rounded border border-gray-200 p-2">
          {distinct.map((v) => (
            <CheckRow
              key={v}
              label={v === '' ? '(Blanks)' : v}
              checked={checked.includes(v)}
              onChange={(on) => setChecked(on ? [...checked, v] : checked.filter((x) => x !== v))}
            />
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend className="mb-1 text-sm font-medium text-gray-700">Filter by condition</legend>
        <Select label="Condition" value={cond} options={opts(['None', ...FILTER_CONDITIONS])} onChange={setCond} />
        <Field label="Value">
          {(id) => <input id={id} className={input} value={value} onChange={(e) => setValue(e.target.value)} />}
        </Field>
      </fieldset>
      {err && (
        <p role="alert" className="text-sm text-red-600">
          {err}
        </p>
      )}
      <DialogButtons onClose={onClose}>
        <button
          type="button"
          className={primaryBtn}
          onClick={() => {
            if (needsValue && value.trim() === '') {
              setErr('Enter a value for this condition');
              return;
            }
            const all = distinct.every((v) => checked.includes(v));
            onApply({
              values: all ? null : distinct.filter((v) => checked.includes(v)),
              cond: cond === 'None' ? null : { type: cond, value: needsValue ? value : '' },
            });
          }}
        >
          Apply
        </button>
      </DialogButtons>
    </Dialog>
  );
}

function CheckRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (on: boolean) => void }) {
  const id = useId();
  return (
    <div className="flex items-center gap-2 py-0.5 text-sm">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <label htmlFor={id}>{label}</label>
    </div>
  );
}

function ValidationDialog({
  rect,
  existing,
  onClose,
  onSave,
  onDelete,
}: {
  rect: Rect;
  existing: Rule | null;
  onClose: () => void;
  onSave: (r: Rule) => void;
  onDelete: () => void;
}) {
  const [range, setRange] = useState(rectName(rect));
  const [type, setType] = useState<'Dropdown' | 'Number range'>(existing?.type === 'number' ? 'Number range' : 'Dropdown');
  const [values, setValues] = useState(existing?.type === 'dropdown' ? existing.values.join(', ') : '');
  const [min, setMin] = useState(existing?.type === 'number' && existing.min !== null ? String(existing.min) : '');
  const [max, setMax] = useState(existing?.type === 'number' && existing.max !== null ? String(existing.max) : '');
  const [err, setErr] = useState('');

  const save = () => {
    const rr = parseRangeText(range);
    if (!rr) return setErr('Enter a valid range');
    if (type === 'Dropdown') {
      const list = values
        .split(',')
        .map((v) => v.trim())
        .filter((v) => v !== '');
      if (!list.length) return setErr('Enter at least one allowed value');
      onSave({ ...rr, id: existing?.id ?? uid(), type: 'dropdown', values: [...new Set(list)], min: null, max: null });
    } else {
      if (!NUM_RE.test(min.trim()) || !NUM_RE.test(max.trim())) return setErr('Minimum and maximum must be numbers');
      const lo = Number(min.trim());
      const hi = Number(max.trim());
      if (lo > hi) return setErr('Minimum must not be greater than maximum');
      onSave({ ...rr, id: existing?.id ?? uid(), type: 'number', values: [], min: lo, max: hi });
    }
  };

  return (
    <Dialog title="Data validation" onClose={onClose}>
      <Field label="Apply to range">
        {(id) => <input id={id} className={input} value={range} onChange={(e) => setRange(e.target.value)} />}
      </Field>
      <Select
        label="Rule type"
        value={type}
        options={opts(['Dropdown', 'Number range'])}
        onChange={(v) => setType(v as typeof type)}
      />
      {type === 'Dropdown' ? (
        <Field label="Allowed values">
          {(id) => (
            <input
              id={id}
              className={input}
              placeholder="e.g. Open, Closed"
              value={values}
              onChange={(e) => setValues(e.target.value)}
            />
          )}
        </Field>
      ) : (
        <div className="flex gap-3">
          <div className="flex-1">
            <Field label="Minimum">
              {(id) => <input id={id} className={input} value={min} onChange={(e) => setMin(e.target.value)} />}
            </Field>
          </div>
          <div className="flex-1">
            <Field label="Maximum">
              {(id) => <input id={id} className={input} value={max} onChange={(e) => setMax(e.target.value)} />}
            </Field>
          </div>
        </div>
      )}
      {err && (
        <p role="alert" className="text-sm text-red-600">
          {err}
        </p>
      )}
      <div className="mt-4 flex items-center gap-2">
        {existing && (
          <button type="button" className={`${btn} text-red-700`} onClick={onDelete}>
            Delete rule
          </button>
        )}
        <span className="flex-1" />
        <button type="button" className={btn} onClick={onClose}>
          Cancel
        </button>
        <button type="button" className={primaryBtn} onClick={save}>
          Save
        </button>
      </div>
    </Dialog>
  );
}

function PivotCreateDialog({
  sheet,
  rect,
  onClose,
  onCreate,
}: {
  sheet: Sheet;
  rect: Rect;
  onClose: () => void;
  onCreate: () => void;
}) {
  const id = useId();
  void sheet;
  return (
    <Dialog title="Create pivot table" onClose={onClose}>
      <p className="mb-3 text-sm text-gray-700">Source range: {rectName(rect)}</p>
      <fieldset className="mb-2">
        <legend className="mb-1 text-sm text-gray-700">Insert to</legend>
        <div className="flex items-center gap-2 text-sm">
          <input id={id} type="radio" name="pivot-dest" defaultChecked />
          <label htmlFor={id}>New worksheet</label>
        </div>
      </fieldset>
      <DialogButtons onClose={onClose}>
        <button type="button" className={primaryBtn} onClick={onCreate}>
          Create
        </button>
      </DialogButtons>
    </Dialog>
  );
}

function PivotEditor({
  data,
  sheet,
  onApply,
  onRefresh,
}: {
  data: WBData;
  sheet: Sheet;
  onApply: (p: Pivot) => string | null;
  onRefresh: () => string | null;
}) {
  const p = sheet.pivot!;
  const headers = sourceHeaders(data, p).filter((h) => h !== '');
  const [rowField, setRowField] = useState(p.rowField ?? '');
  const [colField, setColField] = useState(p.colField ?? '');
  const [valField, setValField] = useState(p.valField ?? '');
  const [agg, setAgg] = useState<Pivot['agg']>(p.agg);
  const [localErr, setLocalErr] = useState<string | null>(null);
  const fieldErr = pivotFieldError(data, p);
  const shownErr = localErr ?? fieldErr;
  const src = data.sheets.find((s) => s.id === p.sourceSheetId);
  const fieldsFor = (v: string) => (headers.includes(v) || v === '' ? headers : [v, ...headers]);
  return (
    <section role="region" aria-label="Pivot table editor" className="w-72 shrink-0 overflow-auto border-l border-gray-200 bg-gray-50 p-4">
      <h2 className="mb-2 text-base font-medium">Pivot table editor</h2>
      <p className="mb-3 text-xs text-gray-600">
        Source: {src ? `${src.name}!` : ''}
        {rectName(p)}
      </p>
      <Select label="Rows" value={rowField} options={opts(fieldsFor(rowField))} onChange={setRowField} />
      <Select
        label="Columns"
        value={colField}
        options={[{ value: '', label: 'None' }, ...opts(fieldsFor(colField))]}
        onChange={setColField}
      />
      <Select label="Values" value={valField} options={opts(fieldsFor(valField))} onChange={setValField} />
      <Select
        label="Summarize by"
        value={agg}
        options={opts(['SUM', 'COUNT', 'AVERAGE'])}
        onChange={(v) => setAgg(v as Pivot['agg'])}
      />
      {shownErr && (
        <p role="alert" className="mb-2 text-sm text-red-600">
          {shownErr}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={primaryBtn}
          onClick={() => {
            if (!rowField || !valField) {
              setLocalErr('Select a row field and a value field');
              return;
            }
            setLocalErr(
              onApply({ ...p, rowField, colField: colField || null, valField, agg }),
            );
          }}
        >
          Apply
        </button>
        <button type="button" className={btn} onClick={() => setLocalErr(onRefresh())}>
          Refresh pivot table
        </button>
      </div>
    </section>
  );
}

function RenameSheetDialog({
  sheets,
  sheetId,
  onClose,
  onSave,
}: {
  sheets: Sheet[];
  sheetId: string;
  onClose: () => void;
  onSave: (name: string) => void;
}) {
  const current = sheets.find((s) => s.id === sheetId)?.name ?? '';
  const [value, setValue] = useState(current);
  const [err, setErr] = useState('');
  const errId = useId();
  // A rejected name is not kept: the text box shows the original name again next to the error.
  const reject = (message: string) => {
    setErr(message);
    setValue(current);
  };
  const save = () => {
    const name = value.trim();
    if (!name) return reject('Worksheet name cannot be empty');
    if (sheets.some((s) => s.id !== sheetId && s.name.toLowerCase() === name.toLowerCase()))
      return reject('Worksheet name already exists');
    onSave(name);
  };
  return (
    <Dialog title="Rename worksheet" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
        noValidate
      >
        <Field label="Worksheet name">
          {(id) => (
            <input
              id={id}
              className={input}
              aria-invalid={err ? 'true' : undefined}
              aria-describedby={err ? errId : undefined}
              aria-errormessage={err ? errId : undefined}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          )}
        </Field>
        {err && (
          <p id={errId} role="alert" title={err} className="text-sm text-red-600">
            {err}
          </p>
        )}
        <DialogButtons onClose={onClose}>
          <button type="submit" className={primaryBtn}>
            Save
          </button>
        </DialogButtons>
      </form>
    </Dialog>
  );
}

function DeleteSheetDialog({ name, onClose, onConfirm }: { name: string; onClose: () => void; onConfirm: () => void }) {
  return (
    <Dialog title="Delete worksheet" onClose={onClose}>
      <p className="text-sm text-gray-700">
        Delete worksheet “{name}”? Its data, formulas, filters, validation rules and pivot results will be removed.
      </p>
      <DialogButtons onClose={onClose}>
        <button type="button" className="rounded-md bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700" onClick={onConfirm}>
          Delete worksheet
        </button>
      </DialogButtons>
    </Dialog>
  );
}

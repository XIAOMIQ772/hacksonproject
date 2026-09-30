import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { ApiError } from '../api';

// Rule 2.4/2.5: while a popup that repeats a page-level name is open, the page-level control is removed
// from the DOM so the name resolves to one element. 'search': pickers with a "Search" textbox hide the
// global "Search" box; 'settings': the account menu's "Settings" link hides the repository "Settings" tab.
const hiders: Record<string, number> = { search: 0, settings: 0 };
const hiderListeners = new Set<() => void>();
export function useHidden(key: 'search' | 'settings'): boolean {
  const [, force] = useState(0);
  useEffect(() => {
    const l = () => force((n) => n + 1);
    hiderListeners.add(l);
    return () => { hiderListeners.delete(l); };
  }, []);
  return hiders[key] > 0;
}
export function useHide(key: 'search' | 'settings', active: boolean) {
  useEffect(() => {
    if (!active) return;
    hiders[key] += 1;
    hiderListeners.forEach((l) => l());
    return () => { hiders[key] -= 1; hiderListeners.forEach((l) => l()); };
  }, [key, active]);
}

// Loads data for a page; `reload` re-runs the loader after a write.
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const seq = useRef(0);
  const reload = useCallback(async () => {
    const n = ++seq.current;
    try {
      const d = await fn();
      if (n === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (n === seq.current) { setError(e as ApiError); setData(null); }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, reload };
}

export function LoadError({ error }: { error: ApiError }) {
  const msg = error.status === 401 ? 'Sign in required' : error.status === 404 ? error.message || 'Not found' : error.message;
  return <p className="py-6 text-lg">{msg}</p>;
}

export function FieldError({ id, msg }: { id: string; msg?: string }) {
  if (!msg) return null;
  return <p id={id} role="alert" className="text-sm text-red-700">{msg}</p>;
}

type FieldProps = {
  label: string; value: string; onChange: (v: string) => void; error?: string;
  type?: string; textarea?: boolean; autoFocus?: boolean; name?: string; autoComplete?: string; rows?: number;
};
export function Field({ label, value, onChange, error, type = 'text', textarea, autoFocus, name, autoComplete, rows = 4 }: FieldProps) {
  const id = useId();
  const errId = `${id}-err`;
  const common = {
    id, value, name, autoFocus, autoComplete,
    'aria-invalid': error ? true : undefined,
    'aria-describedby': error ? errId : undefined,
    className: 'border rounded px-2 py-1 w-full',
  };
  return (
    <div className="mb-3">
      <label htmlFor={id} className="block font-semibold text-sm mb-1">{label}</label>
      {textarea
        ? <textarea {...common} rows={rows} onChange={(e) => onChange(e.target.value)} />
        : <input {...common} type={type} onChange={(e) => onChange(e.target.value)} />}
      <FieldError id={errId} msg={error} />
    </div>
  );
}

export function errorsOf(e: unknown): Record<string, string> {
  if (e instanceof ApiError) return Object.keys(e.fields).length ? e.fields : { _: e.message };
  return { _: String((e as Error)?.message || e) };
}

// Closes a popup on outside mousedown or Escape.
export function useDismiss(open: boolean, close: () => void, ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) close(); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    document.addEventListener('mousedown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); };
  }, [open, close, ref]);
}

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(document.activeElement);
  useEffect(() => {
    const el = ref.current?.querySelector<HTMLElement>('input,textarea,button');
    el?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', key);
    const prev = opener.current;
    return () => { document.removeEventListener('keydown', key); (prev as HTMLElement | null)?.focus?.(); };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/30 pt-24">
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={id} className="bg-white border rounded shadow-lg p-4 w-[28rem] max-w-full">
        <h2 id={id} className="text-lg font-semibold mb-3">{title}</h2>
        {children}
      </div>
    </div>
  );
}

export type Option = { value: string; label: string };

// ARIA combobox: button with role=combobox opening a listbox of clickable options.
export function Combobox({ label, value, options, onChange, hideLabel }: { label: string; value: string; options: Option[]; onChange: (v: string) => void; hideLabel?: boolean }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, ref);
  const current = options.find((o) => o.value === value);
  return (
    <div className="mb-3 relative inline-block" ref={ref}>
      <span id={`${id}-l`} className={hideLabel ? 'sr-only' : 'block font-semibold text-sm mb-1'}>{label}</span>
      <button
        type="button" role="combobox" aria-labelledby={`${id}-l`} aria-expanded={open} aria-haspopup="listbox" aria-controls={`${id}-lb`}
        className="border rounded px-2 py-1 min-w-32 text-left bg-white"
        onClick={() => setOpen((o) => !o)}
      >
        {current?.label ?? 'Select'} <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul id={`${id}-lb`} role="listbox" className="absolute z-30 mt-1 bg-white border rounded shadow min-w-40">
          {options.map((o) => (
            <li key={o.value} role="option" aria-selected={o.value === value} className="px-3 py-1 cursor-pointer hover:bg-blue-50"
              onClick={() => { onChange(o.value); setOpen(false); }}>
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export type MenuItem = { label: string; onSelect: () => void };
export function MenuButton({ label, items, buttonText }: { label: string; items: MenuItem[]; buttonText?: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, ref);
  return (
    <div className="relative inline-block" ref={ref}>
      <button type="button" aria-haspopup="menu" aria-expanded={open} aria-label={buttonText ? label : undefined}
        className="border rounded px-2 py-1 bg-white" onClick={() => setOpen((o) => !o)}>
        {buttonText ?? label}
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-1 bg-white border rounded shadow min-w-48">
          {items.map((it) => (
            <button key={it.label} type="button" role="menuitem" className="block w-full text-left px-3 py-1 hover:bg-blue-50"
              onClick={() => { setOpen(false); it.onSelect(); }}>
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Popover picker used by the sidebar (Assignees, Labels, Milestone, Reviewers).
export function Picker({ label, search, options, onPick, empty, hideGlobalSearch }: {
  label: string; search?: { label: string; value: string; onChange: (v: string) => void };
  options: { name: string; selected?: boolean }[]; onPick: (name: string) => Promise<void> | void; empty?: string; hideGlobalSearch?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, ref);
  useHide('search', open && !!hideGlobalSearch);
  return (
    <div className="relative" ref={ref}>
      <button type="button" aria-expanded={open} aria-haspopup="listbox" className="font-semibold text-sm hover:text-blue-700" onClick={() => setOpen((o) => !o)}>
        {label} <span aria-hidden="true">⚙</span>
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 bg-white border rounded shadow w-64 p-2">
          {search && (
            <input aria-label={search.label} autoFocus className="border rounded px-2 py-1 w-full mb-2" value={search.value} onChange={(e) => search.onChange(e.target.value)} />
          )}
          <ul role="listbox">
            {options.map((o) => (
              <li key={o.name} role="option" aria-selected={!!o.selected} className="px-2 py-1 cursor-pointer hover:bg-blue-50"
                onClick={async () => { setOpen(false); await onPick(o.name); }}>
                {o.selected && <span aria-hidden="true">✓ </span>}{o.name}
              </li>
            ))}
          </ul>
          {!options.length && <p className="text-sm text-gray-600 px-2">{empty || 'No matches'}</p>}
        </div>
      )}
    </div>
  );
}

export function Badge({ children }: { children: React.ReactNode }) {
  return <span className="inline-block border rounded-full px-2 text-xs text-gray-700 align-middle">{children}</span>;
}

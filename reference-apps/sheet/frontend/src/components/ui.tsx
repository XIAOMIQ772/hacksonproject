import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>('input:not([type=hidden]), select, textarea, button');
    first?.focus();
  }, []);
  // The backdrop does not capture pointer events: a click on the page behind the dialog reaches its
  // target (tabs, cells, toolbar) and closes the dialog instead of being swallowed by the overlay.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) closeRef.current();
    };
    const t = setTimeout(() => document.addEventListener('mousedown', down), 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', down);
    };
  }, []);
  return (
    <div className="pointer-events-none fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/30 py-24">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        className="pointer-events-auto w-[420px] max-w-[95vw] rounded-lg bg-white p-5 shadow-xl"
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            onClose();
          }
        }}
      >
        <h2 id={id} className="mb-4 text-lg font-medium text-gray-900">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

export type MenuItem = { label: string; onSelect: () => void; disabled?: boolean };

export function Menu({
  items,
  onClose,
  style,
  label,
}: {
  items: MenuItem[];
  onClose: () => void;
  style?: React.CSSProperties;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    // defer so the opening click does not immediately close the menu
    const t = setTimeout(() => {
      document.addEventListener('mousedown', down);
      document.addEventListener('keydown', key);
    }, 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', down);
      document.removeEventListener('keydown', key);
    };
  }, [onClose]);
  return (
    <div
      ref={ref}
      role="menu"
      aria-label={label}
      className="fixed z-50 min-w-[190px] rounded-md border border-gray-200 bg-white py-1 shadow-lg"
      style={style}
      onMouseDown={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
    >
      {items.map((it) => (
        <button
          key={it.label}
          type="button"
          role="menuitem"
          disabled={it.disabled}
          className="block w-full px-4 py-1.5 text-left text-sm text-gray-800 hover:bg-gray-100 disabled:text-gray-400"
          onClick={() => {
            onClose();
            it.onSelect();
          }}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

export type Option = { value: string; label: string };

/**
 * ARIA combobox + listbox (select-only pattern). Clicking the combobox opens a visible
 * listbox whose options use role="option" with their visible label as accessible name.
 */
export function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (v: string) => void;
}) {
  const base = useId();
  const labelId = `${base}-label`;
  const btnId = `${base}-combo`;
  const listId = `${base}-list`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const wrap = useRef<HTMLDivElement>(null);
  const current = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', down);
    return () => document.removeEventListener('mousedown', down);
  }, [open]);

  const show = () => {
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  };
  const choose = (o: Option) => {
    setOpen(false);
    if (o.value !== value) onChange(o.value);
  };

  return (
    <div ref={wrap} className="mb-3">
      <label id={labelId} htmlFor={btnId} className={labelCls}>
        {label}
      </label>
      {/* input[type=button]: exposes both a value (toHaveValue) and text (toHaveText) */}
      <div className="relative">
        <input
          id={btnId}
          type="button"
          role="combobox"
          aria-labelledby={labelId}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={open ? `${listId}-${active}` : undefined}
          value={current?.label ?? ''}
          className={`${input} cursor-pointer bg-white pr-6 text-left`}
          onClick={() => (open ? setOpen(false) : show())}
          onKeyDown={(e) => {
            if (!open) {
              if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                show();
              }
              return;
            }
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(options.length - 1, a + 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (options[active]) choose(options[active]); }
            else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setOpen(false); }
            else if (e.key === 'Tab') setOpen(false);
          }}
        />
        <svg className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2" width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
          <path d="M1 3h8L5 8z" />
        </svg>
      </div>
      <ul
        id={listId}
        role="listbox"
        hidden={!open}
        className="mt-1 max-h-48 overflow-auto rounded-md border border-gray-200 bg-white py-1 shadow"
      >
        {options.map((o, i) => (
          <li
            key={o.value}
            id={`${listId}-${i}`}
            role="option"
            aria-selected={o.value === value}
            className={`cursor-pointer px-3 py-1 text-sm ${i === active ? 'bg-gray-100' : ''} ${o.value === value ? 'font-medium' : ''}`}
            onMouseDown={(e) => e.preventDefault()}
            onMouseEnter={() => setActive(i)}
            onClick={() => choose(o)}
          >
            {o.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

export const btn =
  'rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-800 hover:bg-gray-50 disabled:opacity-40';
export const primaryBtn = 'rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700';
export const input = 'w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none';
export const labelCls = 'mb-1 block text-sm text-gray-700';

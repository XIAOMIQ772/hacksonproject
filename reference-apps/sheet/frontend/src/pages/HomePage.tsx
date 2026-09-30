import { useEffect, useId, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { createWorkbook, fmtTime, listWorkbooks, type WorkbookSummary } from '../api';
import { Dialog, btn, labelCls, primaryBtn } from '../components/ui';
import { parseCsv } from '../lib/csv';
import { blankSheet, key } from '../lib/sheet';

function HomePage() {
  const [items, setItems] = useState<WorkbookSummary[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [importing, setImporting] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    listWorkbooks()
      .then(setItems)
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="flex items-center gap-3 border-b border-gray-200 bg-white px-6 py-3">
        <span className="grid h-8 w-8 place-items-center rounded bg-green-600 text-lg font-bold text-white">▦</span>
        <h1 className="text-xl text-gray-800">Sheets</h1>
      </header>
      <div className="mx-auto w-full max-w-5xl px-6 py-6">
        <div className="mb-6 flex gap-3">
          <button type="button" className={primaryBtn} onClick={() => navigate('/new')}>
            New blank workbook
          </button>
          <button type="button" className={btn} onClick={() => setImporting(true)}>
            Import CSV
          </button>
        </div>
        <section aria-label="Workbooks" className="rounded-lg border border-gray-200 bg-white">
          <div className="flex border-b border-gray-200 px-4 py-2 text-sm font-medium text-gray-600">
            <span className="flex-1">Name</span>
            <span className="w-64">Date modified</span>
          </div>
          {loadError && (
            <p role="alert" className="p-4 text-sm text-red-600">
              {loadError}
            </p>
          )}
          {items === null && !loadError && <p className="p-4 text-sm text-gray-500">Loading…</p>}
          <ul>
            {items?.map((wb) => (
              <li key={wb.id} className="flex items-center border-b border-gray-100 px-4 py-2.5 last:border-0">
                <span className="flex-1">
                  <Link to={`/workbooks/${wb.id}`} className="text-gray-900 hover:underline">
                    {wb.name}
                  </Link>
                </span>
                <span className="w-64 text-sm text-gray-600">Last updated: {fmtTime(wb.updatedAt)}</span>
              </li>
            ))}
          </ul>
          {items?.length === 0 && <p className="p-4 text-sm text-gray-500">No workbooks yet.</p>}
        </section>
      </div>
      {importing && <ImportDialog onClose={() => setImporting(false)} onDone={(id) => navigate(`/workbooks/${id}`)} />}
    </main>
  );
}

function ImportDialog({ onClose, onDone }: { onClose: () => void; onDone: (id: string) => void }) {
  const id = useId();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setError('');
    if (!file) {
      setError('Please choose a CSV file');
      return;
    }
    setBusy(true);
    try {
      const text = await file.text();
      const rows = parseCsv(text);
      if (!rows) {
        setError('Invalid CSV file format. Import failed.');
        return;
      }
      const sheet = blankSheet('Sheet1');
      rows.forEach((row, r) =>
        row.forEach((v, c) => {
          // CSV text is kept literally: a leading = or ' is protected so it is not parsed as a formula.
          if (v !== '') sheet.cells[key(r, c)] = /^[=']/.test(v) ? `'${v}` : v;
        }),
      );
      const name = file.name.replace(/\.csv$/i, '').trim() || 'Imported workbook';
      const wb = await createWorkbook(name, { activeSheetId: sheet.id, sheets: [sheet] });
      onDone(wb.id);
    } catch {
      setError('Invalid CSV file format. Import failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog title="Import CSV" onClose={onClose}>
      <label htmlFor={id} className={labelCls}>
        CSV file
      </label>
      <input
        id={id}
        type="file"
        accept=".csv,text/csv"
        className="mb-3 block w-full text-sm"
        onChange={(e) => {
          setFile(e.target.files?.[0] ?? null);
          setError('');
        }}
      />
      {error && (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" className={btn} onClick={onClose}>
          Cancel
        </button>
        <button type="button" className={primaryBtn} disabled={busy} onClick={confirm}>
          Confirm import
        </button>
      </div>
    </Dialog>
  );
}

export default HomePage;

import { useId, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { createWorkbook } from '../api';
import { btn, input, labelCls, primaryBtn } from '../components/ui';

function CreatePage() {
  const id = useId();
  const [name, setName] = useState('Untitled spreadsheet');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (!name.trim()) {
      setError('Workbook name cannot be empty');
      return;
    }
    setBusy(true);
    try {
      const wb = await createWorkbook(name.trim());
      navigate(`/workbooks/${wb.id}`);
    } catch (err) {
      setError((err as Error).message || 'Failed to create workbook');
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="mx-auto mt-16 w-full max-w-md rounded-lg border border-gray-200 bg-white p-6">
        <h1 className="mb-4 text-xl text-gray-900">Create workbook</h1>
        <form onSubmit={submit} noValidate>
          <label htmlFor={id} className={labelCls}>
            Workbook name
          </label>
          <input id={id} className={input} value={name} onChange={(e) => setName(e.target.value)} />
          {error && (
            <p role="alert" className="mt-2 text-sm text-red-600">
              {error}
            </p>
          )}
          <div className="mt-4 flex justify-end gap-2">
            <Link to="/" className={btn}>
              Cancel
            </Link>
            <button type="submit" className={primaryBtn} disabled={busy}>
              Create
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}

export default CreatePage;

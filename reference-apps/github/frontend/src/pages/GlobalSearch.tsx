import { Link, useSearchParams } from 'react-router-dom';
import { get, enc, ago } from '../api';
import { useLoad, Badge } from '../components/ui';

type R = { owner: string; name: string; fullName: string; description: string; visibility: string; updatedAt: string };

export default function GlobalSearch() {
  const [params] = useSearchParams();
  const q = params.get('q') || '';
  const { data } = useLoad(() => get<{ results: R[] }>(`/search/repos?q=${enc(q)}`), [q]);
  return (
    <div className="flex gap-6">
      <nav className="w-48 shrink-0">
        <h2 className="font-semibold mb-2">Filter by</h2>
        <Link to={`/search?q=${enc(q)}&type=repositories`} aria-current="page" className="block py-1 font-semibold">Repositories</Link>
      </nav>
      <section className="flex-1">
        <h1 className="text-xl mb-3">Repository results</h1>
        {data && data.results.length === 0 && <p>No results</p>}
        <ul>
          {(data?.results || []).map((r) => (
            <li key={r.fullName} className="border rounded p-3 mb-2">
              <Link className="text-blue-700 font-semibold" to={`/${enc(r.owner)}/${enc(r.name)}`}>{r.name}</Link>{' '}
              <Badge>{r.visibility === 'private' ? 'Private' : 'Public'}</Badge>
              <p className="text-sm text-gray-600">{r.fullName}</p>
              {r.description && <p>{r.description}</p>}
              <p className="text-sm text-gray-600">Updated {ago(r.updatedAt)}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

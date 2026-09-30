import { Link } from 'react-router-dom';
import { get, enc } from '../api';
import { useSession } from '../session';
import { useLoad } from '../components/ui';

type RepoSummary = { owner: string; name: string; fullName: string; visibility: string; description: string };

export default function Home() {
  const { user, orgs } = useSession();
  const { data } = useLoad(async () => (user ? get<{ repos: RepoSummary[] }>(`/owners/${enc(user.username)}`) : null), [user?.username]);
  if (!user) {
    return (
      <section>
        <h1 className="text-3xl font-semibold mb-2">Build and ship software together</h1>
        <p className="mb-4">Sign in to collaborate on repositories, issues, and pull requests. Use the search box to find public repositories.</p>
      </section>
    );
  }
  return (
    <div className="flex gap-8">
      <aside className="w-72">
        <div className="flex items-center justify-between mb-2">
          <h2 className="font-semibold">Top repositories</h2>
          <Link to="/new" className="bg-green-700 text-white rounded px-2 py-0.5 text-sm">New repository</Link>
        </div>
        <ul>
          {(data?.repos || []).map((r) => (
            <li key={r.fullName} className="py-1"><Link className="text-blue-700" to={`/${enc(r.owner)}/${enc(r.name)}`}>{r.name}</Link></li>
          ))}
        </ul>
        {orgs.length > 0 && (
          <>
            <h2 className="font-semibold mt-4 mb-2">Organizations</h2>
            <ul>
              {orgs.map((o) => <li key={o.login} className="py-1"><Link className="text-blue-700" to={`/${enc(o.login)}`}>{o.displayName}</Link></li>)}
            </ul>
          </>
        )}
      </aside>
      <section>
        <h1 className="text-2xl mb-2">Dashboard</h1>
        <p>Welcome back. Pick a repository to continue working.</p>
      </section>
    </div>
  );
}

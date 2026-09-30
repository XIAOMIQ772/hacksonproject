import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { api, enc } from '../api';
import { useSession } from '../session';
import { Dialog, useDismiss, useHidden, useHide } from './ui';

const RESERVED = new Set(['login', 'signup', 'password_reset', 'settings', 'organizations', 'orgs', 'search', 'new', 'logout']);

// Repository context of the current URL, if any (the top search is scoped to it).
export function repoFromPath(pathname: string): { owner: string; repo: string } | null {
  const [owner, repo] = pathname.split('/').filter(Boolean).map(decodeURIComponent);
  if (!owner || !repo || RESERVED.has(owner)) return null;
  return { owner, repo };
}

export default function Header() {
  const { user, orgs, refresh } = useSession();
  const loc = useLocation();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const repo = repoFromPath(loc.pathname);
  const searchHidden = useHidden('search');
  const onSearchPage = loc.pathname === '/search' || /\/search$/.test(loc.pathname);
  const [q, setQ] = useState(onSearchPage ? params.get('q') || '' : '');
  useEffect(() => { setQ(onSearchPage ? params.get('q') || '' : ''); }, [loc.pathname, loc.search]); // eslint-disable-line react-hooks/exhaustive-deps
  const [menu, setMenu] = useState(false);
  const [confirmOut, setConfirmOut] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const closeMenu = useCallback(() => setMenu(false), []);
  useDismiss(menu, closeMenu, menuRef);
  useHide('settings', menu);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const term = q.trim();
    if (repo) nav(`/${enc(repo.owner)}/${enc(repo.repo)}/search?q=${enc(term)}&type=code`);
    else nav(`/search?q=${enc(term)}&type=repositories`);
  };

  const signOut = async () => {
    await api('POST', '/logout');
    setConfirmOut(false);
    await refresh();
    nav('/', { replace: true });
  };

  return (
    <header className="bg-gray-900 text-white px-4 py-2 flex items-center gap-4">
      <Link to="/" aria-label="Homepage" className="font-bold text-lg">GitHub</Link>
      {searchHidden ? <div className="flex-1 max-w-md" /> : <form role="search" onSubmit={submit} className="flex-1 max-w-md">
        <input type="search" aria-label="Search" placeholder={repo ? 'Search this repository' : 'Search or jump to...'}
          className="w-full rounded px-2 py-1 text-black bg-white" value={q} onChange={(e) => setQ(e.target.value)} />
      </form>}
      <div className="ml-auto flex items-center gap-3">
        {!user && (
          <>
            <Link to="/login" className="hover:underline">Sign in</Link>
            <Link to="/signup" className="border border-white rounded px-2 py-0.5">Sign up</Link>
          </>
        )}
        {user && (
          <div className="relative" ref={menuRef}>
            <button type="button" aria-label="Account menu" aria-haspopup="true" aria-expanded={menu} onClick={() => setMenu((m) => !m)}
              className="border border-gray-500 rounded px-2 py-0.5">
              <span>{user.username}</span> <span aria-hidden="true">▾</span>
            </button>
            {menu && (
              <div className="absolute right-0 mt-1 w-64 bg-white text-black border rounded shadow z-30 p-2">
                <p className="text-sm text-gray-600 px-2">Signed in as <strong>{user.username}</strong></p>
                <hr className="my-1" />
                <Link to="/organizations" className="block px-2 py-1 hover:bg-blue-50" onClick={closeMenu}>Your organizations</Link>
                <Link to="/settings" className="block px-2 py-1 hover:bg-blue-50" onClick={closeMenu}>Settings</Link>
                {orgs.length > 0 && (
                  <ul className="px-2 py-1 text-sm">
                    {orgs.map((o) => <li key={o.login} className="text-gray-700">{o.login}</li>)}
                  </ul>
                )}
                <hr className="my-1" />
                <a href="/logout" className="block px-2 py-1 hover:bg-blue-50"
                  onClick={(e) => { e.preventDefault(); setMenu(false); setConfirmOut(true); }}>Sign out</a>
              </div>
            )}
          </div>
        )}
      </div>
      {confirmOut && (
        <Dialog title="Sign out" onClose={() => setConfirmOut(false)}>
          <div className="text-black">
            <p className="mb-3">Signing out ends only the session in this browser. Other browsers stay signed in.</p>
            <div className="flex gap-2">
              <button type="button" className="bg-red-700 text-white rounded px-3 py-1" onClick={signOut}>Confirm sign out</button>
              <button type="button" className="border rounded px-3 py-1" onClick={() => setConfirmOut(false)}>Cancel</button>
            </div>
          </div>
        </Dialog>
      )}
    </header>
  );
}

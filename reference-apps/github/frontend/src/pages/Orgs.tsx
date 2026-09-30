import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, get, enc, ago } from '../api';
import { useSession } from '../session';
import { Badge, Combobox, Dialog, Field, FieldError, LoadError, MenuButton, errorsOf, useLoad } from '../components/ui';
import { SignInRequired } from './Settings';

const btn = 'bg-green-700 text-white rounded px-3 py-1 font-semibold';

export function YourOrgs() {
  const { user, orgs, refresh } = useSession();
  useLoad(() => refresh(), []);
  if (!user) return <SignInRequired />;
  return (
    <section className="max-w-2xl">
      <div className="flex items-center justify-between mb-3">
        <h1 className="text-2xl">Your organizations</h1>
        <Link className={btn} to="/organizations/new">New organization</Link>
      </div>
      {orgs.length === 0 && <p>You are not a member of any organizations.</p>}
      <ul>
        {orgs.map((o) => (
          <li key={o.login} className="border-b py-2">
            <Link className="text-blue-700 font-semibold" to={`/${enc(o.login)}`}>{o.login}</Link>
            <span className="ml-2 text-gray-600">{o.displayName}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function NewOrg() {
  const { user, refresh } = useSession();
  const nav = useNavigate();
  const [login, setLogin] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});
  if (!user) return <SignInRequired />;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api('POST', '/orgs', { login, displayName });
      await refresh();
      nav(`/${enc(r.login)}`);
    } catch (ex) {
      setErrs(errorsOf(ex));
    }
  };
  return (
    <section className="max-w-md">
      <h1 className="text-2xl mb-4">Set up your organization</h1>
      <form onSubmit={submit} noValidate>
        <Field label="Organization name" value={login} onChange={setLogin} error={errs.login} />
        <Field label="Display name" value={displayName} onChange={setDisplayName} error={errs.displayName} />
        <FieldError id="org-err" msg={errs._} />
        <button type="submit" className={btn}>Create organization</button>
      </form>
    </section>
  );
}

function OrgHeader({ login, displayName, active }: { login: string; displayName: string; active: string }) {
  const tab = (name: string, to: string) => (
    <Link to={to} aria-current={active === name ? 'page' : undefined} className={`px-3 py-2 ${active === name ? 'border-b-2 border-orange-500 font-semibold' : ''}`}>{name}</Link>
  );
  return (
    <div className="mb-4">
      <h1 className="text-2xl font-semibold">{login}</h1>
      <p className="text-gray-600">{displayName}</p>
      <nav className="flex gap-2 border-b mt-2">
        {tab('Repositories', `/orgs/${enc(login)}/repositories`)}
        {tab('Teams', `/orgs/${enc(login)}/teams`)}
        {tab('People', `/orgs/${enc(login)}/people`)}
      </nav>
    </div>
  );
}

type RepoRow = { owner: string; name: string; description: string; visibility: string; updatedAt: string };
type OwnerData = { type: 'org' | 'user'; login: string; displayName?: string; repos: RepoRow[] };

export function OwnerPage() {
  const params = useParams();
  const login = (params.owner || params.org) as string;
  const [sp, setSp] = useSearchParams();
  const q = sp.get('q') || '';
  const type = sp.get('type') || 'all';
  const { data, error } = useLoad(() => get<OwnerData>(`/owners/${enc(login)}`), [login]);
  if (error) return <LoadError error={error} />;
  if (!data) return null;
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  const rows = data.repos.filter((r) => r.name.toLowerCase().includes(q.trim().toLowerCase()) && (type === 'all' || r.visibility === type));
  const typeLink = (t: string, label: string) => {
    const next = new URLSearchParams(sp);
    if (t === 'all') next.delete('type'); else next.set('type', t);
    return <Link to={`?${next}`} replace aria-current={type === t ? 'page' : undefined} className={`block py-1 px-2 ${type === t ? 'bg-gray-100 font-semibold' : ''}`}>{label}</Link>;
  };
  return (
    <div>
      {data.type === 'org' ? <OrgHeader login={data.login} displayName={data.displayName || ''} active="Repositories" /> : <h1 className="text-2xl font-semibold mb-4">{data.login}</h1>}
      <div className="flex gap-6">
        <nav className="w-40 shrink-0">
          {typeLink('all', 'All')}
          {typeLink('public', 'Public')}
          {typeLink('private', 'Private')}
        </nav>
        <section className="flex-1">
          <h2 className="text-lg font-semibold mb-2">Repositories</h2>
          <label htmlFor="find-repo" className="sr-only">Find a repository</label>
          <input id="find-repo" className="border rounded px-2 py-1 w-full mb-3" placeholder="Find a repository..." value={q} onChange={(e) => setParam('q', e.target.value)} />
          {rows.length === 0 && <p>No repositories matched your search.</p>}
          <ul>
            {rows.map((r) => (
              <li key={r.name} className="border-b py-2">
                <Link className="text-blue-700 font-semibold" to={`/${enc(r.owner)}/${enc(r.name)}`}>{r.name}</Link>{' '}
                <Badge>{r.visibility === 'private' ? 'Private' : 'Public'}</Badge>
                {r.description && <p className="text-sm">{r.description}</p>}
                <p className="text-xs text-gray-600">Updated {ago(r.updatedAt)}</p>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

type TeamRow = { name: string; description: string; parent: string | null; members: number };

function TeamTree({ teams, parent, org }: { teams: TeamRow[]; parent: string | null; org: string }) {
  const kids = teams.filter((t) => t.parent === parent);
  if (!kids.length) return null;
  return (
    <ul className={parent ? 'ml-6' : ''}>
      {kids.map((t) => (
        <li key={t.name} className="py-1">
          <Link className="text-blue-700 font-semibold" to={`/orgs/${enc(org)}/teams/${enc(t.name)}`}>{t.name}</Link>
          <span className="ml-2 text-sm text-gray-600">{t.parent ? `Parent team: ${t.parent}` : 'Top-level team'} · {t.members} members</span>
          <TeamTree teams={teams} parent={t.name} org={org} />
        </li>
      ))}
    </ul>
  );
}

export function Teams() {
  const { org } = useParams() as { org: string };
  const { data, error } = useLoad(() => get(`/orgs/${enc(org)}/teams`), [org]);
  if (error) return <LoadError error={error} />;
  if (!data) return null;
  return (
    <div>
      <OrgHeader login={data.org.login} displayName={data.org.displayName} active="Teams" />
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-semibold">Teams</h2>
        {data.canManage && <Link className={btn} to={`/orgs/${enc(org)}/new-team`}>New team</Link>}
      </div>
      {data.teams.length === 0 && <p>No teams yet.</p>}
      <TeamTree teams={data.teams} parent={null} org={org} />
    </div>
  );
}

export function NewTeam() {
  const { org } = useParams() as { org: string };
  const nav = useNavigate();
  const { data } = useLoad(() => get(`/orgs/${enc(org)}/teams`), [org]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [parent, setParent] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api('POST', `/orgs/${enc(org)}/teams`, { name: name.trim(), description, parent });
      nav(`/orgs/${enc(org)}/teams/${enc(name.trim())}`);
    } catch (ex) {
      setErrs(errorsOf(ex));
    }
  };
  return (
    <section className="max-w-md">
      <h1 className="text-2xl mb-4">Create new team</h1>
      <form onSubmit={submit} noValidate>
        <Field label="Team name" value={name} onChange={setName} error={errs.name} />
        <Field label="Description" value={description} onChange={setDescription} />
        <Combobox label="Parent team" value={parent} onChange={setParent}
          options={[{ value: '', label: 'No parent team' }, ...((data?.teams || []) as TeamRow[]).map((t) => ({ value: t.name, label: t.name }))]} />
        <FieldError id="parent-err" msg={errs.parent} />
        <FieldError id="team-err" msg={errs._} />
        <div><button type="submit" className={btn}>Create team</button></div>
      </form>
    </section>
  );
}

export function TeamPage({ tab }: { tab: 'overview' | 'members' | 'settings' }) {
  const { org, team } = useParams() as { org: string; team: string };
  const { data, error, reload } = useLoad(() => get(`/orgs/${enc(org)}/teams/${enc(team)}`), [org, team]);
  const [adding, setAdding] = useState(false);
  const [username, setUsername] = useState('');
  const [addErr, setAddErr] = useState('');
  const [parent, setParent] = useState<string | null>(null);
  const [parentErr, setParentErr] = useState('');
  const [saved, setSaved] = useState(false);
  if (error) return <LoadError error={error} />;
  if (!data) return null;
  const base = `/orgs/${enc(org)}/teams/${enc(team)}`;
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api('POST', `${base}/members`, { username: username.trim() });
      setAdding(false); setUsername(''); setAddErr('');
      await reload();
    } catch (ex) {
      setAddErr(errorsOf(ex).username || errorsOf(ex)._);
    }
  };
  const remove = async (u: string) => {
    await api('DELETE', `${base}/members/${enc(u)}`);
    await reload();
  };
  const saveParent = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api('PUT', `${base}/parent`, { parent: parent ?? data.parent ?? '' });
      setParentErr(''); setSaved(true);
      await reload();
    } catch (ex) {
      setSaved(false);
      setParentErr(errorsOf(ex).parent || errorsOf(ex)._);
    }
  };
  const link = (name: string, to: string, key: string) => (
    <Link to={to} aria-current={tab === key ? 'page' : undefined} className={`px-3 py-2 ${tab === key ? 'border-b-2 border-orange-500 font-semibold' : ''}`}>{name}</Link>
  );
  return (
    <div>
      <p className="text-sm"><Link className="text-blue-700" to={`/orgs/${enc(org)}/teams`}>{data.org.displayName}</Link></p>
      <h1 className="text-2xl font-semibold">{`${data.org.login}/${data.name}`}</h1>
      {data.description && <p className="text-gray-600">{data.description}</p>}
      <p className="text-sm mt-1">{data.parent ? <>Parent team: <span>{data.parent}</span></> : 'Top-level team'}</p>
      {data.children.length > 0 && <p className="text-sm">Child teams: {data.children.join(', ')}</p>}
      <nav className="flex gap-2 border-b mt-2 mb-4">
        {link('Members', `${base}/members`, 'members')}
        {link('Settings', `${base}/settings`, 'settings')}
      </nav>
      {tab !== 'settings' && (
        <section>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-lg font-semibold">Team members</h2>
            {data.canManage && tab === 'members' && !adding && <button type="button" className={btn} onClick={() => setAdding(true)}>Add member</button>}
          </div>
          {adding && (
            <form onSubmit={add} noValidate className="border rounded p-3 mb-3">
              <Field label="Username" value={username} onChange={setUsername} error={addErr} autoFocus />
              <div className="flex gap-2">
                <button type="submit" className={btn}>Add member</button>
                <button type="button" className="border rounded px-3 py-1" onClick={() => { setAdding(false); setAddErr(''); }}>Cancel</button>
              </div>
            </form>
          )}
          {data.members.length === 0 && <p>This team has no members.</p>}
          <ul>
            {data.members.map((m: string) => (
              <li key={m} className="border-b py-2 flex items-center justify-between">
                <span>{m}</span>
                {data.canManage && tab === 'members' && <button type="button" className="border rounded px-2 text-sm" onClick={() => remove(m)}>{`Remove ${m}`}</button>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {tab === 'settings' && (
        <section className="max-w-md">
          <h2 className="text-lg font-semibold mb-2">Team settings</h2>
          {!data.canManage && <p>Only organization owners can change team settings.</p>}
          {data.canManage && (
            <form onSubmit={saveParent} noValidate>
              <label htmlFor="parent-team" className="block font-semibold text-sm mb-1">Parent team</label>
              {/* REQ-2-2-2 explicitly requires a native select for "Parent team". */}
              <select id="parent-team" className="border rounded px-2 py-1 mb-2" value={parent ?? data.parent ?? ''}
                aria-invalid={parentErr ? true : undefined} aria-describedby={parentErr ? 'parent-team-err' : undefined}
                onChange={(e) => { setParent(e.target.value); setSaved(false); }}>
                <option value="" label="No parent team" />
                {data.allTeams.map((t: string) => <option key={t} value={t} label={t} />)}
              </select>
              <FieldError id="parent-team-err" msg={parentErr} />
              <div><button type="submit" className={btn}>Save</button></div>
              {saved && <p role="status" className="text-green-800 mt-2">Team settings saved</p>}
            </form>
          )}
        </section>
      )}
    </div>
  );
}

export function People() {
  const { org } = useParams() as { org: string };
  const { data, error, reload } = useLoad(() => get(`/orgs/${enc(org)}/people`), [org]);
  const [adding, setAdding] = useState(false);
  const [login, setLogin] = useState('');
  const [role, setRole] = useState('Member');
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [removing, setRemoving] = useState<string | null>(null);
  const [removeErr, setRemoveErr] = useState('');
  if (error) return <LoadError error={error} />;
  if (!data) return null;
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api('POST', `/orgs/${enc(org)}/people`, { login: login.trim(), role });
      setAdding(false); setLogin(''); setRole('Member'); setErrs({});
      await reload();
    } catch (ex) {
      setErrs(errorsOf(ex));
    }
  };
  const remove = async () => {
    try {
      await api('DELETE', `/orgs/${enc(org)}/people/${enc(removing as string)}`);
      setRemoving(null); setRemoveErr('');
      await reload();
    } catch (ex) {
      setRemoveErr(errorsOf(ex)._);
    }
  };
  return (
    <div>
      <OrgHeader login={data.org.login} displayName={data.org.displayName} active="People" />
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-semibold">People</h2>
        {data.canManage && !adding && <button type="button" className={btn} onClick={() => setAdding(true)}>Add member</button>}
      </div>
      {adding && (
        <form onSubmit={add} noValidate className="border rounded p-3 mb-3 max-w-md">
          <Field label="Username or email" value={login} onChange={setLogin} error={errs.login} autoFocus />
          <Combobox label="Role" value={role} onChange={setRole} options={[{ value: 'Member', label: 'Member' }, { value: 'Owner', label: 'Owner' }]} />
          <FieldError id="role-err" msg={errs.role || errs._} />
          <div className="flex gap-2">
            <button type="submit" className={btn}>Add member</button>
            <button type="button" className="border rounded px-3 py-1" onClick={() => { setAdding(false); setErrs({}); }}>Cancel</button>
          </div>
        </form>
      )}
      <ul>
        {data.members.map((m: { username: string; role: string }) => (
          <li key={m.username} className="border-b py-2 flex items-center justify-between">
            <span><span className="font-semibold">{m.username}</span> <span className="ml-2 text-sm text-gray-600">{m.role}</span></span>
            {data.canManage && m.username !== data.me && (
              <MenuButton label={`Member menu ${m.username}`} buttonText="⋯" items={[{ label: 'Remove from organization', onSelect: () => setRemoving(m.username) }]} />
            )}
          </li>
        ))}
      </ul>
      {removing && (
        <Dialog title={`Remove ${removing} from ${data.org.login}`} onClose={() => { setRemoving(null); setRemoveErr(''); }}>
          <p className="mb-3">This removes the member from the organization, its teams, and direct repository access.</p>
          <FieldError id="remove-err" msg={removeErr} />
          <div className="flex gap-2">
            <button type="button" className="bg-red-700 text-white rounded px-3 py-1" onClick={remove}>Remove</button>
            <button type="button" className="border rounded px-3 py-1" onClick={() => setRemoving(null)}>Cancel</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

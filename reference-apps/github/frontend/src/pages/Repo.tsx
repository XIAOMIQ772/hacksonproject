import { createContext, useCallback, useContext, useRef, useState } from 'react';
import { Link, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, get, enc, encPath, ago } from '../api';
import { useSession } from '../session';
import { Badge, Dialog, Field, FieldError, LoadError, MenuButton, Combobox, errorsOf, useDismiss, useHide, useHidden, useLoad } from '../components/ui';
import { Issues, NewIssue, IssuePage, Pulls, Compare, PullPage } from './Work';

export type Perms = { role: string | null; signedIn: boolean; read: boolean; write: boolean; triage: boolean; maintain: boolean; admin: boolean };
export type RepoData = {
  owner: string; name: string; fullName: string; description: string; visibility: string; defaultBranch: string;
  forkOf: { owner: string; name: string; fullName: string } | null; perms: Perms; branches: string[];
  openIssues: number; openPulls: number; protections: { branch: string; requireApproval: boolean; requireCheck: boolean }[]; canFork: boolean;
};

type Ctx = { repo: RepoData; base: string; reload: () => Promise<void> };
const RepoContext = createContext<Ctx>(null as unknown as Ctx);
export const useRepo = () => useContext(RepoContext);
export const btn = 'bg-green-700 text-white rounded px-3 py-1 font-semibold disabled:opacity-50';
export const btn2 = 'border rounded px-3 py-1 bg-white disabled:opacity-50';

export default function RepoRoutes() {
  const { owner, repo: name } = useParams() as { owner: string; repo: string };
  const { user } = useSession();
  const { data, error, reload } = useLoad(() => get<RepoData>(`/repos/${enc(owner)}/${enc(name)}`), [owner, name, user?.username]);
  if (error) return <p className="py-6 text-lg">{error.status === 404 ? 'Access denied' : error.message}</p>;
  if (!data) return null;
  const base = `/${enc(data.owner)}/${enc(data.name)}`;
  return (
    <RepoContext.Provider value={{ repo: data, base, reload }}>
      <Routes>
        <Route path="search" element={<RepoShell nav={false}><RepoSearch /></RepoShell>} />
        <Route path="*" element={<RepoShell nav><RepoBody /></RepoShell>} />
      </Routes>
    </RepoContext.Provider>
  );
}

function RepoBody() {
  return (
    <Routes>
      <Route index element={<CodeView />} />
      <Route path="tree/*" element={<CodeView />} />
      <Route path="blob/*" element={<CodeView />} />
      <Route path="commits/*" element={<CommitsPage />} />
      <Route path="commits" element={<CommitsPage />} />
      <Route path="commit/:sha" element={<CommitPage />} />
      <Route path="new/*" element={<NewFile />} />
      <Route path="fork" element={<ForkPage />} />
      <Route path="settings" element={<SettingsPage tab="general" />} />
      <Route path="settings/access" element={<SettingsPage tab="access" />} />
      <Route path="settings/branches" element={<SettingsPage tab="branches" />} />
      <Route path="issues" element={<Issues />} />
      <Route path="issues/new" element={<NewIssue />} />
      <Route path="issues/:n" element={<IssuePage />} />
      <Route path="pulls" element={<Pulls />} />
      <Route path="compare" element={<Compare />} />
      <Route path="compare/*" element={<Compare />} />
      <Route path="pull/:n" element={<PullPage tab="conversation" />} />
      <Route path="pull/:n/commits" element={<PullPage tab="commits" />} />
      <Route path="pull/:n/files" element={<PullPage tab="files" />} />
      <Route path="*" element={<p>Not found</p>} />
    </Routes>
  );
}

function RepoShell({ nav, children }: { nav: boolean; children: React.ReactNode }) {
  const { repo, base } = useRepo();
  const loc = useLocation();
  const navigate = useNavigate();
  const rest = loc.pathname.slice(base.length);
  const settingsHidden = useHidden('settings');
  const section = /^\/(issues)/.test(rest) ? 'Issues' : /^\/(pulls|pull\/|compare)/.test(rest) ? 'Pull requests' : /^\/settings/.test(rest) ? 'Settings' : 'Code';
  const tab = (label: string, to: string, count?: number) => (
    <span className={`px-3 py-2 ${section === label ? 'border-b-2 border-orange-500 font-semibold' : ''}`}>
      <Link to={to} aria-current={section === label ? 'page' : undefined}>{label}</Link>
      {count !== undefined && <span className="ml-1 text-xs bg-gray-200 rounded-full px-1.5">{count}</span>}
    </span>
  );
  return (
    <div>
      <div className="flex items-center gap-3 mb-1">
        <h1 className="text-xl">{`${repo.owner}/${repo.name}`}</h1>
        <Badge>{repo.visibility === 'private' ? 'Private' : 'Public'}</Badge>
        <div className="ml-auto">
          {repo.canFork && <button type="button" className={btn2} onClick={() => navigate(`${base}/fork`)}>Fork</button>}
        </div>
      </div>
      {repo.forkOf && (
        <p className="text-sm text-gray-600">Forked from <Link className="text-blue-700" to={`/${enc(repo.forkOf.owner)}/${enc(repo.forkOf.name)}`}>{repo.forkOf.name}</Link></p>
      )}
      {nav && (
        <nav className="flex gap-1 border-b mt-2 mb-4">
          {tab('Code', base)}
          {tab('Issues', `${base}/issues`, repo.openIssues)}
          {tab('Pull requests', `${base}/pulls`, repo.openPulls)}
          {repo.perms.admin && !settingsHidden && tab('Settings', `${base}/settings`)}
        </nav>
      )}
      {!nav && <div className="border-b mt-2 mb-4" />}
      {children}
    </div>
  );
}

// ---------------- Code ----------------
function BranchSelector({ current, onSelect }: { current: string; onSelect: (branch: string) => void }) {
  const { repo, base, reload } = useRepo();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [err, setErr] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => { setOpen(false); setQ(''); setErr(''); }, []);
  useDismiss(open, close, ref);
  const term = q.trim();
  const matches = repo.branches.filter((b) => b.toLowerCase().includes(term.toLowerCase()));
  const valid = /^[A-Za-z0-9._/-]+$/.test(term) && !term.includes('..') && !term.includes('//') && !/^[/.-]/.test(term) && !/[/.]$/.test(term) && !term.endsWith('.lock') && !term.split('/').some((s) => s.startsWith('.'));
  const canCreate = repo.perms.write && term && valid && !repo.branches.includes(term);
  const create = async () => {
    try {
      await api('POST', `/repos/${enc(repo.owner)}/${enc(repo.name)}/branches`, { name: term, from: current });
      await reload();
      close();
      onSelect(term);
    } catch (ex) {
      setErr(errorsOf(ex).name || errorsOf(ex)._);
    }
  };
  return (
    <div className="relative inline-block" ref={ref}>
      <button type="button" aria-haspopup="listbox" aria-expanded={open} className={btn2} onClick={() => (open ? close() : setOpen(true))}>
        {`Branch ${current}`}
      </button>
      {open && (
        <div className="absolute z-30 mt-1 bg-white border rounded shadow w-72 p-2">
          <p className="font-semibold text-sm mb-1">Switch branches</p>
          <input aria-label="Find branch" autoFocus className="border rounded px-2 py-1 w-full mb-2" placeholder="Find or create a branch..." value={q}
            onChange={(e) => { setQ(e.target.value); setErr(''); }}
            onKeyDown={(e) => { if (e.key === 'Enter' && canCreate && !matches.length) create(); }} />
          <ul role="listbox" className="max-h-64 overflow-auto">
            {matches.map((b) => (
              <li key={b} role="option" aria-selected={b === current} className="px-2 py-1 cursor-pointer hover:bg-blue-50"
                onClick={() => { close(); onSelect(b); }}>
                {b === current && <span aria-hidden="true">✓ </span>}{b}{b === repo.defaultBranch && <span aria-hidden="true" className="ml-2 text-xs text-gray-500">default</span>}
              </li>
            ))}
            {canCreate && (
              <li role="option" aria-selected={false} className="px-2 py-1 cursor-pointer hover:bg-blue-50 border-t" onClick={create}>
                {`Create branch: ${term}`}
              </li>
            )}
          </ul>
          {canCreate && <p className="text-xs text-gray-600 px-2">{`from ${current}`}</p>}
          {term && !matches.length && <p className="text-sm px-2">No matching branch</p>}
          {term && !valid && <p role="alert" className="text-sm text-red-700 px-2">Invalid branch</p>}
          {err && <p role="alert" className="text-sm text-red-700 px-2">{err}</p>}
        </div>
      )}
    </div>
  );
}

function CloneMenu() {
  const { repo } = useRepo();
  const [open, setOpen] = useState(false);
  const [proto, setProto] = useState<'HTTPS' | 'SSH'>('HTTPS');
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, ref);
  const value = proto === 'HTTPS' ? `https://${location.host}/${repo.owner}/${repo.name}.git` : `git@${location.hostname}:${repo.owner}/${repo.name}.git`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = value;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    setCopied(true);
  };
  return (
    <div className="relative inline-block" ref={ref}>
      <button type="button" aria-haspopup="dialog" aria-expanded={open} className={btn} onClick={() => { setOpen((o) => !o); setCopied(false); }}>Code</button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 bg-white border rounded shadow w-96 p-3">
          <p className="font-semibold mb-2">Clone</p>
          <div role="tablist" aria-label="Clone protocol" className="flex gap-2 border-b mb-2">
            {(['HTTPS', 'SSH'] as const).map((p) => (
              <button key={p} type="button" role="tab" aria-selected={proto === p} className={`px-2 py-1 ${proto === p ? 'border-b-2 border-orange-500 font-semibold' : ''}`}
                onClick={() => { setProto(p); setCopied(false); }}>{p}</button>
            ))}
          </div>
          <div role="tabpanel" className="flex gap-2 items-center">
            <input readOnly aria-label="Clone URL" className="border rounded px-2 py-1 flex-1 font-mono text-sm" value={value} />
            <button type="button" className={btn2} onClick={copy}>Copy clone value</button>
          </div>
          {copied && <p role="status" className="text-green-800 text-sm mt-2">Copied</p>}
        </div>
      )}
    </div>
  );
}

type Contents = {
  empty?: boolean; branch: string; path: string; type: 'dir' | 'file'; content?: string; readme?: string | null;
  entries?: { name: string; type: string; path: string }[]; lastCommit: { sha: string; short: string; message: string; author: string; time: string } | null; commitCount: number;
};

function Highlight({ text, q }: { text: string; q: string }) {
  if (!q) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  const lower = text.toLowerCase();
  const needle = q.toLowerCase();
  let i = 0;
  let k = 0;
  for (let at = lower.indexOf(needle); at >= 0; at = lower.indexOf(needle, i)) {
    parts.push(text.slice(i, at), <mark key={k++}>{text.slice(at, at + q.length)}</mark>);
    i = at + q.length;
  }
  parts.push(text.slice(i));
  return <>{parts}</>;
}

export function FileLines({ content, q = '' }: { content: string; q?: string }) {
  const lines = content.replace(/\n$/, '').split('\n');
  return (
    <div className="border rounded font-mono text-sm overflow-auto">
      {lines.map((l, i) => (
        <div key={i} className="flex">
          <span aria-hidden="true" className="w-10 text-right pr-2 text-gray-400 select-none">{i + 1}</span>
          <span className="whitespace-pre">{q ? <Highlight text={l} q={q} /> : l}</span>
        </div>
      ))}
    </div>
  );
}

function CodeView() {
  const { repo, base } = useRepo();
  const params = useParams();
  const loc = useLocation();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const spec = params['*'] ? decodeURIComponent(params['*']) : '';
  const isBlob = loc.pathname.startsWith(`${base}/blob/`);
  const { data, error } = useLoad(() => get<Contents>(`/repos/${enc(repo.owner)}/${enc(repo.name)}/contents?spec=${enc(spec)}`), [repo.fullName, spec, repo.branches.length, repo.defaultBranch]);
  if (error) return <LoadError error={error} />;
  if (!data) return null;
  if (data.empty) {
    return <section><h2 className="text-lg font-semibold">This repository is empty.</h2><p>Clone it with the Code button to get started.</p><div className="mt-2"><CloneMenu /></div></section>;
  }
  const crumbs = data.path ? data.path.split('/') : [];
  const switchBranch = (b: string) => nav(`${base}/tree/${encPath(b)}`);
  return (
    <section>
      {repo.description && <p className="mb-3">{repo.description}</p>}
      <div className="flex items-center gap-2 mb-3">
        <BranchSelector current={data.branch} onSelect={switchBranch} />
        <span className="text-sm text-gray-600">{repo.branches.length} branches</span>
        <div className="ml-auto flex gap-2">
          {repo.perms.write && (
            <MenuButton label="Add file" items={[{ label: 'Create new file', onSelect: () => nav(`${base}/new/${encPath(data.branch)}${data.type === 'dir' && data.path ? `?dir=${enc(data.path)}` : ''}`) }]} />
          )}
          {!data.path && <CloneMenu />}
        </div>
      </div>
      {crumbs.length > 0 && (
        <nav className="mb-2 text-sm">
          <Link className="text-blue-700" to={`${base}/tree/${encPath(data.branch)}`}>{repo.name}</Link>
          {crumbs.map((c, i) => (
            <span key={i}> / {i < crumbs.length - 1 ? <Link className="text-blue-700" to={`${base}/tree/${encPath(data.branch)}/${encPath(crumbs.slice(0, i + 1).join('/'))}`}>{c}</Link> : <strong>{c}</strong>}</span>
          ))}
        </nav>
      )}
      <div className="border rounded-t px-3 py-2 bg-gray-50 flex items-center gap-3 text-sm">
        {data.lastCommit && (
          <>
            <span>{data.lastCommit.author}</span>
            <Link className="text-gray-800 hover:text-blue-700" to={`${base}/commit/${data.lastCommit.sha}`} aria-label={`Latest commit ${data.lastCommit.short}`}>{data.lastCommit.message}</Link>
            <span className="text-gray-600">{ago(data.lastCommit.time)}</span>
          </>
        )}
        <span className="ml-auto">
          <Link className="text-blue-700" to={`${base}/commits/${encPath(data.branch)}${data.type === 'file' ? `?path=${enc(data.path)}` : ''}`}>Commits</Link>
          {data.type === 'dir' && <span className="ml-1 text-gray-600">({data.commitCount})</span>}
        </span>
      </div>
      {data.type === 'dir' && (
        <table className="w-full border border-t-0 mb-4">
          <tbody>
            {data.entries!.map((e) => (
              <tr key={e.path} className="border-t">
                <td className="px-3 py-1">
                  <span aria-hidden="true" className="mr-2">{e.type === 'dir' ? '📁' : '📄'}</span>
                  <Link className="text-blue-700 hover:underline" to={`${base}/${e.type === 'dir' ? 'tree' : 'blob'}/${encPath(data.branch)}/${encPath(e.path)}`}>{e.name}</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data.type === 'dir' && data.readme != null && (
        <article className="border rounded p-3">
          <h2 className="font-semibold mb-2">README.md</h2>
          <div className="whitespace-pre-wrap">{data.readme}</div>
        </article>
      )}
      {data.type === 'file' && (
        <div className="mt-2">
          <h2 className="font-semibold mb-2">{crumbs[crumbs.length - 1]}</h2>
          <FileLines content={data.content || ''} q={isBlob ? sp.get('q') || '' : ''} />
        </div>
      )}
    </section>
  );
}

type CommitRow = { sha: string; short: string; message: string; author: string; time: string };

function CommitsPage() {
  const { repo, base } = useRepo();
  const params = useParams();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const branch = params['*'] ? decodeURIComponent(params['*']) : repo.defaultBranch;
  const path = sp.get('path') || '';
  const { data, error } = useLoad(() => get<{ commits: CommitRow[] }>(`/repos/${enc(repo.owner)}/${enc(repo.name)}/commits?ref=${enc(branch)}${path ? `&path=${enc(path)}` : ''}`), [repo.fullName, branch, path]);
  if (error) return <LoadError error={error} />;
  if (!data) return null;
  return (
    <section>
      <h2 className="text-lg font-semibold mb-2">{path ? `History for ${path}` : 'Commit history'}</h2>
      <div className="mb-3"><BranchSelector current={branch} onSelect={(b) => nav(`${base}/commits/${encPath(b)}`)} /></div>
      <ul className="border rounded">
        {data.commits.map((c) => (
          <li key={c.sha} className="border-b last:border-b-0 px-3 py-2">
            <Link className="font-semibold hover:text-blue-700" to={`${base}/commit/${c.sha}`}>{c.message}</Link>
            <div className="text-sm text-gray-600 flex gap-2">
              <span>{c.author}</span>
              <span>committed</span>
              <span>{ago(c.time)}</span>
              <code className="ml-auto">{c.short}</code>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export type DiffFile = { path: string; status: string; additions: number; deletions: number; lines: { type: string; oldNo?: number; newNo?: number; text: string }[] };

export function DiffStat({ diff }: { diff: { files: DiffFile[]; additions: number; deletions: number } }) {
  return (
    <div className="flex gap-4 items-baseline mb-3">
      <p><strong>Changed files</strong> <span>{diff.files.length}</span></p>
      <p>{`${diff.additions} additions, ${diff.deletions} deletions`}</p>
    </div>
  );
}

export function DiffView({ files, renderAfter, lineAction }: {
  files: DiffFile[];
  renderAfter?: (path: string, key: string) => React.ReactNode;
  lineAction?: (path: string, key: string) => React.ReactNode;
}) {
  return (
    <div>
      {files.map((f) => (
        <section key={f.path} className="border rounded mb-3">
          <h3 className="bg-gray-50 px-3 py-1 font-mono text-sm border-b flex gap-3">
            <span>{f.path}</span>
            <span aria-hidden="true" className="text-green-700">+{f.additions}</span>
            <span aria-hidden="true" className="text-red-700">-{f.deletions}</span>
          </h3>
          <div className="font-mono text-sm">
            {f.lines.map((l, i) => {
              const key = l.type === 'del' ? `L${l.oldNo}` : `R${l.newNo}`;
              return (
                <div key={i}>
                  <div className={`flex ${l.type === 'add' ? 'bg-green-50' : l.type === 'del' ? 'bg-red-50' : ''}`}>
                    <span className="w-8 shrink-0">{l.type !== 'ctx' && lineAction ? lineAction(f.path, key) : null}</span>
                    <span aria-hidden="true" className="w-10 text-right pr-2 text-gray-400">{l.oldNo ?? ''}</span>
                    <span aria-hidden="true" className="w-10 text-right pr-2 text-gray-400">{l.newNo ?? ''}</span>
                    <span aria-hidden="true" className="w-4">{l.type === 'add' ? '+' : l.type === 'del' ? '-' : ' '}</span>
                    <span className="whitespace-pre">{l.text}</span>
                  </div>
                  {renderAfter && l.type !== 'ctx' ? renderAfter(f.path, key) : null}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function CommitPage() {
  const { repo, base } = useRepo();
  const { sha } = useParams() as { sha: string };
  const { data, error } = useLoad(() => get(`/repos/${enc(repo.owner)}/${enc(repo.name)}/commit/${enc(sha)}`), [repo.fullName, sha]);
  if (error) return <LoadError error={error} />;
  if (!data) return null;
  return (
    <section>
      <h2 className="text-xl font-semibold mb-1">{data.message}</h2>
      <p className="text-sm text-gray-600 mb-1"><span>{data.author}</span> committed <span>{ago(data.time)}</span></p>
      <p className="text-sm mb-3">
        Commit <code>{data.sha}</code>
        {data.parents.map((p: string) => <span key={p}> · Parent <Link className="text-blue-700 font-mono" to={`${base}/commit/${p}`}>{p.slice(0, 7)}</Link></span>)}
      </p>
      <DiffStat diff={data.diff} />
      <DiffView files={data.diff.files} />
    </section>
  );
}

function NewFile() {
  const { repo, base, reload } = useRepo();
  const params = useParams();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const branch = params['*'] ? decodeURIComponent(params['*']) : repo.defaultBranch;
  const [path, setPath] = useState(sp.get('dir') ? `${sp.get('dir')}/` : '');
  const [content, setContent] = useState('');
  const [message, setMessage] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});
  if (!repo.perms.write) return <p>You need write access to add files.</p>;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api('POST', `/repos/${enc(repo.owner)}/${enc(repo.name)}/files`, { branch, path, content, message });
      await reload();
      nav(`${base}/blob/${encPath(r.branch)}/${encPath(r.path)}`);
    } catch (ex) {
      setErrs(errorsOf(ex));
    }
  };
  return (
    <section className="max-w-3xl">
      <h2 className="text-lg font-semibold mb-2">Create new file</h2>
      <p className="text-sm mb-3">{`in ${repo.name} on ${branch}`}</p>
      <form onSubmit={submit} noValidate>
        <Field label="File name" value={path} onChange={setPath} error={errs.path} />
        <Field label="File contents" textarea rows={10} value={content} onChange={setContent} />
        <Field label="Commit message" value={message} onChange={setMessage} error={errs.message} />
        <FieldError id="file-branch-err" msg={errs.branch || errs._} />
        <button type="submit" className={btn}>Commit changes</button>
      </form>
    </section>
  );
}

function ForkPage() {
  const { repo } = useRepo();
  const { user, orgs } = useSession();
  const nav = useNavigate();
  const [owner, setOwner] = useState(user?.username || '');
  const [name, setName] = useState(repo.name);
  const [visibility, setVisibility] = useState(repo.visibility);
  const [errs, setErrs] = useState<Record<string, string>>({});
  if (!user) return <p>Sign in to fork this repository.</p>;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api('POST', `/repos/${enc(repo.owner)}/${enc(repo.name)}/forks`, { owner, name, visibility });
      nav(`/${enc(r.owner)}/${enc(r.name)}`);
    } catch (ex) {
      setErrs(errorsOf(ex));
    }
  };
  return (
    <section className="max-w-xl">
      <h2 className="text-lg font-semibold mb-2">Create a new fork</h2>
      <form onSubmit={submit} noValidate>
        <Combobox label="Owner" value={owner} onChange={setOwner} options={[user.username, ...orgs.map((o) => o.login)].map((o) => ({ value: o, label: o }))} />
        <FieldError id="fork-owner-err" msg={errs.owner} />
        <Field label="Repository name" value={name} onChange={setName} error={errs.name} />
        <fieldset className="mb-3">
          <legend className="font-semibold text-sm mb-1">Visibility</legend>
          <label className="block"><input type="radio" name="fork-vis" disabled={repo.visibility === 'private'} checked={visibility === 'public'} onChange={() => setVisibility('public')} /> Public</label>
          <label className="block"><input type="radio" name="fork-vis" checked={visibility === 'private'} onChange={() => setVisibility('private')} /> Private</label>
        </fieldset>
        <FieldError id="fork-err" msg={errs._} />
        <button type="submit" className={btn}>Create fork</button>
      </form>
    </section>
  );
}

// ---------------- Repository code search ----------------
type SearchResult = { path: string; name: string; branch: string; language: string; matches: { lineNo: number; text: string }[] };

function RepoSearch() {
  const { repo, base } = useRepo();
  const [sp, setSp] = useSearchParams();
  const q = sp.get('q') || '';
  const path = sp.get('path') || '';
  const lang = sp.get('lang') || '';
  const { data } = useLoad(() => get<{ results: SearchResult[] }>(`/repos/${enc(repo.owner)}/${enc(repo.name)}/search?q=${enc(q)}&path=${enc(path)}&lang=${enc(lang)}`), [repo.fullName, q, path, lang]);
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  return (
    <div className="flex gap-6">
      <nav className="w-48 shrink-0">
        <Link to={`${base}/search?q=${enc(q)}&type=code`} aria-current="page" className="block py-1 px-2 bg-gray-100 font-semibold">Code</Link>
        <div className="mt-3 text-sm">
          <label className="block">Path<input className="border rounded px-1 w-full" value={path} onChange={(e) => setParam('path', e.target.value)} /></label>
          <label className="block mt-2">Language<input className="border rounded px-1 w-full" value={lang} onChange={(e) => setParam('lang', e.target.value)} /></label>
        </div>
        <p className="mt-3 text-sm"><Link className="text-blue-700" to={base}>{`Back to ${repo.name}`}</Link></p>
      </nav>
      <section className="flex-1">
        <h2 className="text-lg font-semibold mb-2">Code results</h2>
        {data && data.results.length === 0 && <p>No code results</p>}
        {(data?.results || []).map((r) => (
          <article key={r.path} className="border rounded mb-3">
            <div className="px-3 py-2 bg-gray-50 border-b text-sm">
              <Link className="text-blue-700 font-semibold" to={`${base}/blob/${encPath(r.branch)}/${encPath(r.path)}?q=${enc(q)}`}>{r.name}</Link>
              <span className="ml-2 text-gray-600">{r.path}</span>
              <span className="ml-2 text-gray-600">{`on ${r.branch}`}</span>
              <span className="ml-2 text-gray-600">{r.language}</span>
            </div>
            <div className="font-mono text-sm px-3 py-1">
              {r.matches.map((m) => (
                <div key={m.lineNo} className="flex"><span aria-hidden="true" className="w-8 text-gray-400">{m.lineNo}</span><span className="whitespace-pre"><Highlight text={m.text} q={q} /></span></div>
              ))}
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}

// ---------------- Settings ----------------
function SettingsPage({ tab }: { tab: 'general' | 'access' | 'branches' }) {
  const { repo, base } = useRepo();
  const link = (label: string, to: string, key: string) => (
    <li><Link to={to} aria-current={tab === key ? 'page' : undefined} className={`block py-1 px-2 ${tab === key ? 'bg-gray-100 font-semibold' : ''}`}>{label}</Link></li>
  );
  if (!repo.perms.admin) return <p>You need admin access to change repository settings.</p>;
  return (
    <div className="flex gap-6">
      <nav className="w-48 shrink-0">
        <ul>
          {link('General', `${base}/settings`, 'general')}
          {link('Manage access', `${base}/settings/access`, 'access')}
          {link('Branches', `${base}/settings/branches`, 'branches')}
        </ul>
      </nav>
      <section className="flex-1">
        {tab === 'general' && <GeneralSettings />}
        {tab === 'access' && <AccessSettings />}
        {tab === 'branches' && <BranchSettings />}
      </section>
    </div>
  );
}

function GeneralSettings() {
  const { repo, reload } = useRepo();
  const [open, setOpen] = useState(false);
  const [vis, setVis] = useState(repo.visibility === 'private' ? 'public' : 'private');
  const [err, setErr] = useState('');
  const confirm = async () => {
    try {
      await api('PUT', `/repos/${enc(repo.owner)}/${enc(repo.name)}/visibility`, { visibility: vis });
      setOpen(false);
      await reload();
    } catch (ex) {
      setErr(errorsOf(ex)._);
    }
  };
  return (
    <div>
      <h2 className="text-lg font-semibold mb-2">General</h2>
      <p className="mb-4">Repository name: {repo.name}</p>
      <section className="border border-red-400 rounded p-3">
        <h3 className="font-semibold text-red-700 mb-2">Danger Zone</h3>
        <div className="flex items-center justify-between">
          <div>
            <p className="font-semibold">Change repository visibility</p>
            <p className="text-sm">{`This repository is currently ${repo.visibility}.`}</p>
          </div>
          <button type="button" className={btn2} onClick={() => { setVis(repo.visibility === 'private' ? 'public' : 'private'); setOpen(true); }}>Change visibility</button>
        </div>
      </section>
      {open && (
        <Dialog title="Change repository visibility" onClose={() => setOpen(false)}>
          <p className="mb-2 text-sm">Changing visibility changes who can see this repository.</p>
          <fieldset className="mb-3">
            <legend className="sr-only">Visibility</legend>
            <label className="block"><input type="radio" name="vis" checked={vis === 'public'} onChange={() => setVis('public')} /> Public</label>
            <label className="block"><input type="radio" name="vis" checked={vis === 'private'} onChange={() => setVis('private')} /> Private</label>
          </fieldset>
          <FieldError id="vis-err" msg={err} />
          <div className="flex gap-2">
            <button type="button" className="bg-red-700 text-white rounded px-3 py-1" onClick={confirm}>Confirm visibility</button>
            <button type="button" className={btn2} onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

const ROLE_OPTS = ['Read', 'Triage', 'Write', 'Maintain', 'Admin'];

function GrantRow({ g, onSave }: { g: { subjectType: string; name: string; role: string }; onSave: (role: string) => Promise<void> }) {
  const [role, setRole] = useState(g.role);
  const label = g.role.charAt(0).toUpperCase() + g.role.slice(1);
  return (
    <tr aria-label={`${g.name} ${label}`} className="border-t">
      <td className="px-2 py-1">{g.name}</td>
      <td className="px-2 py-1 text-sm text-gray-600">{g.subjectType === 'team' ? 'Team' : 'Member'}</td>
      <td className="px-2 py-1">{label}</td>
      <td className="px-2 py-1">
        {/* REQ-2-3 explicitly requires a native select labeled "Role" in each existing grant row. */}
        <select aria-label="Role" className="border rounded px-1" value={role} onChange={(e) => setRole(e.target.value)}>
          {ROLE_OPTS.map((r) => <option key={r} value={r.toLowerCase()} label={r} />)}
        </select>
      </td>
      <td className="px-2 py-1"><button type="button" className={btn2} onClick={() => onSave(role)}>Save</button></td>
    </tr>
  );
}

function AccessSettings() {
  const { repo } = useRepo();
  const path = `/repos/${enc(repo.owner)}/${enc(repo.name)}/access`;
  const { data, reload } = useLoad(() => get(path), [path]);
  const [picking, setPicking] = useState(false);
  const [q, setQ] = useState('');
  const [subject, setSubject] = useState<{ subjectType: string; name: string } | null>(null);
  const [role, setRole] = useState('read');
  const [err, setErr] = useState('');
  useHide('search', picking);
  const { data: cands } = useLoad(() => (picking ? get(`${path}/candidates?q=${enc(q)}`) : Promise.resolve(null)), [picking, q]);
  const save = async (s: { subjectType: string; name: string }, r: string) => {
    try {
      await api('POST', path, { ...s, role: r });
      setErr('');
      await reload();
      return true;
    } catch (ex) {
      setErr(errorsOf(ex).subject || errorsOf(ex).role || errorsOf(ex)._);
      return false;
    }
  };
  const add = async () => {
    if (!subject) { setErr('Select a member or team'); return; }
    if (await save(subject, role)) { setPicking(false); setSubject(null); setQ(''); setRole('read'); }
  };
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-semibold">Manage access</h2>
        {!picking && <button type="button" className={btn} onClick={() => setPicking(true)}>Add people or teams</button>}
      </div>
      {picking && (
        <div className="border rounded p-3 mb-3 max-w-lg">
          <label className="block font-semibold text-sm mb-1" htmlFor="access-search">Search</label>
          <input id="access-search" autoFocus className="border rounded px-2 py-1 w-full mb-2" value={q} onChange={(e) => { setQ(e.target.value); setSubject(null); }} />
          <ul role="listbox" className="mb-2 max-h-48 overflow-auto">
            {(cands?.candidates || []).map((c: { subjectType: string; name: string }) => (
              <li key={`${c.subjectType}:${c.name}`} role="option" aria-selected={subject?.name === c.name && subject?.subjectType === c.subjectType}
                className={`px-2 py-1 cursor-pointer hover:bg-blue-50 ${subject?.name === c.name && subject?.subjectType === c.subjectType ? 'bg-blue-100' : ''}`}
                onClick={() => setSubject(c)}>
                {c.name}<span aria-hidden="true" className="ml-2 text-xs text-gray-500">{c.subjectType === 'team' ? 'team' : 'member'}</span>
              </li>
            ))}
          </ul>
          {subject && <p className="text-sm mb-2">{`Selected: ${subject.name}`}</p>}
          <Combobox label="Role" value={role} onChange={setRole} options={ROLE_OPTS.map((r) => ({ value: r.toLowerCase(), label: r }))} />
          <FieldError id="access-err" msg={err} />
          <div className="flex gap-2">
            <button type="button" className={btn} onClick={add}>Add</button>
            <button type="button" className={btn2} onClick={() => { setPicking(false); setErr(''); }}>Cancel</button>
          </div>
        </div>
      )}
      {!picking && err && <FieldError id="access-row-err" msg={err} />}
      {/* The grant list is hidden while the picker is open so its per-row "Role" selects do not compete with the picker's Role combobox. */}
      {!picking && <table className="w-full border">
        <caption className="text-left font-semibold py-1">Direct access</caption>
        <tbody>
          {(data?.grants || []).map((g: { subjectType: string; name: string; role: string }) => (
            <GrantRow key={`${g.subjectType}:${g.name}:${g.role}`} g={g} onSave={async (r) => { await save(g, r); }} />
          ))}
        </tbody>
      </table>}
      {!picking && data && data.grants.length === 0 && <p className="mt-2">No one has direct access yet.</p>}
    </div>
  );
}

function BranchSettings() {
  const { repo, reload } = useRepo();
  const [def, setDef] = useState(repo.defaultBranch);
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [rule, setRule] = useState({ branch: '', requireApproval: false, requireCheck: false });
  const [err, setErr] = useState('');
  const [defSaved, setDefSaved] = useState(false);
  const rp = `/repos/${enc(repo.owner)}/${enc(repo.name)}`;
  const saveDefault = async () => {
    await api('PUT', `${rp}/default-branch`, { branch: def });
    setConfirming(false);
    setDefSaved(true);
    await reload();
  };
  const saveRule = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api('POST', `${rp}/protections`, { ...rule, original: editing === '' ? '' : editing });
      setEditing(null);
      setErr('');
      await reload();
    } catch (ex) {
      setErr(errorsOf(ex).branch || errorsOf(ex)._);
    }
  };
  return (
    <div>
      <h2 className="text-lg font-semibold mb-2">Default branch</h2>
      <p className="text-sm mb-2">The default branch is shown when the repository is opened.</p>
      <div className="flex items-end gap-2 mb-6">
        <div>
          <label htmlFor="default-branch" className="block font-semibold text-sm mb-1">Default branch</label>
          {/* REQ-4-3-3 explicitly requires a native select for "Default branch". */}
          <select id="default-branch" className="border rounded px-2 py-1" value={def} onChange={(e) => { setDef(e.target.value); setDefSaved(false); }}>
            {repo.branches.map((b) => <option key={b} value={b} label={b} />)}
          </select>
        </div>
        <button type="button" className={btn2} onClick={() => setConfirming(true)}>Update</button>
        {defSaved && <p role="status" className="text-green-800 text-sm">{`Default branch is ${repo.defaultBranch}`}</p>}
      </div>
      {confirming && (
        <Dialog title="Change default branch" onClose={() => setConfirming(false)}>
          <p className="mb-3">{`Change the default branch from ${repo.defaultBranch} to ${def}?`}</p>
          <div className="flex gap-2">
            <button type="button" className="bg-red-700 text-white rounded px-3 py-1" onClick={saveDefault}>Confirm</button>
            <button type="button" className={btn2} onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        </Dialog>
      )}
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-semibold">Branch protection rules</h2>
        {editing === null && (
          <button type="button" className={btn2} onClick={() => { setRule({ branch: '', requireApproval: false, requireCheck: false }); setEditing(''); setErr(''); }}>Add branch protection rule</button>
        )}
      </div>
      {editing !== null && (
        <form onSubmit={saveRule} noValidate className="border rounded p-3 mb-3 max-w-md">
          <Field label="Branch name pattern" value={rule.branch} onChange={(v) => setRule((r) => ({ ...r, branch: v }))} error={err} autoFocus />
          <label className="block"><input type="checkbox" checked={rule.requireApproval} onChange={(e) => setRule((r) => ({ ...r, requireApproval: e.target.checked }))} /> Require 1 approval</label>
          <label className="block mb-3"><input type="checkbox" checked={rule.requireCheck} onChange={(e) => setRule((r) => ({ ...r, requireCheck: e.target.checked }))} /> Require status check test</label>
          <div className="flex gap-2">
            <button type="submit" className={btn}>{editing === '' ? 'Create' : 'Save changes'}</button>
            <button type="button" className={btn2} onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </form>
      )}
      {repo.protections.length === 0 && <p>No branch protection rules.</p>}
      <ul>
        {repo.protections.map((p) => (
          <li key={p.branch} className="border rounded p-2 mb-2 flex items-center gap-3">
            <strong>{p.branch}</strong>
            {p.requireApproval && <span className="text-sm">1 approval</span>}
            {p.requireCheck && <span className="text-sm">Require status check test</span>}
            {editing === null && (
              <button type="button" aria-label={`Edit ${p.branch}`} className={`${btn2} ml-auto text-sm`}
                onClick={() => { setRule({ branch: p.branch, requireApproval: p.requireApproval, requireCheck: p.requireCheck }); setEditing(p.branch); setErr(''); }}>Edit</button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

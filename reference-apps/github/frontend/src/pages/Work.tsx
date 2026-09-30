import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, get, enc, encPath, ago } from '../api';
import { Badge, Combobox, Dialog, Field, FieldError, LoadError, MenuButton, Picker, errorsOf, useLoad } from '../components/ui';
import { useRepo, btn, btn2, DiffStat, DiffView } from './Repo';

const REACTIONS: [string, string][] = [['+1', '👍'], ['-1', '👎'], ['laugh', '😄'], ['hooray', '🎉'], ['heart', '❤️']];

function useParamState() {
  const [sp, setSp] = useSearchParams();
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  return [sp, set] as const;
}

// ================= Issues =================
export function Issues() {
  const { repo, base } = useRepo();
  const [sp, set] = useParamState();
  const state = sp.get('state') === 'closed' ? 'closed' : 'open';
  const q = sp.get('q') || '';
  const label = sp.get('label') || '';
  const { data, error } = useLoad(() => get(`/repos/${enc(repo.owner)}/${enc(repo.name)}/issues?state=${state}&q=${enc(q)}&label=${enc(label)}`), [repo.fullName, state, q, label]);
  const stateLink = (s: string, text: string, count?: number) => {
    const next = new URLSearchParams(sp);
    next.set('state', s);
    return (
      <span className={state === s ? 'font-semibold' : ''}>
        <Link to={`?${next}`} replace aria-current={state === s ? 'page' : undefined}>{text}</Link>
        {count !== undefined && <span className="ml-1 text-sm text-gray-600">{count}</span>}
      </span>
    );
  };
  if (error) return <LoadError error={error} />;
  return (
    <section>
      <div className="flex items-center gap-3 mb-3">
        <input type="search" aria-label="Search issues" className="border rounded px-2 py-1 flex-1" placeholder="Search all issues" value={q} onChange={(e) => set('q', e.target.value)} />
        {data?.canCreate && <Link className={btn} to={`${base}/issues/new`}>New issue</Link>}
      </div>
      <div className="border rounded">
        <div className="bg-gray-50 px-3 py-2 flex items-center gap-4 border-b">
          {stateLink('open', 'Open', data?.openCount)}
          {stateLink('closed', 'Closed', data?.closedCount)}
          <div className="ml-auto">
            <Combobox label="Label" hideLabel value={label} onChange={(v) => set('label', v)}
              options={[{ value: '', label: 'All labels' }, ...(data?.labels || []).map((l: string) => ({ value: l, label: l }))]} />
          </div>
        </div>
        {data && data.rows.length === 0 && <p className="px-3 py-4">No results matched your search.</p>}
        <ul>
          {(data?.rows || []).map((i: { number: number; title: string; state: string; author: string; labels: string[]; updatedAt: string }) => (
            <li key={i.number} className="border-b last:border-b-0 px-3 py-2">
              <Link className="font-semibold hover:text-blue-700" to={`${base}/issues/${i.number}`}>{i.title}</Link>
              {i.labels.map((l) => <span key={l} className="ml-2"><Badge>{l}</Badge></span>)}
              <p className="text-sm text-gray-600">{`#${i.number} · ${i.state === 'open' ? 'Open' : 'Closed'} · opened by ${i.author} · updated ${ago(i.updatedAt)}`}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function NewIssue() {
  const { repo, base, reload } = useRepo();
  const nav = useNavigate();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});
  if (!repo.perms.write) return <p>You need write access to open issues in this repository.</p>;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api('POST', `/repos/${enc(repo.owner)}/${enc(repo.name)}/issues`, { title, body });
      await reload();
      nav(`${base}/issues/${r.number}`);
    } catch (ex) {
      setErrs(errorsOf(ex));
    }
  };
  return (
    <section className="max-w-2xl">
      <h2 className="text-lg font-semibold mb-2">Create new issue</h2>
      <form onSubmit={submit} noValidate>
        <Field label="Title" value={title} onChange={setTitle} error={errs.title} />
        <Field label="Description" textarea value={body} onChange={setBody} />
        <FieldError id="issue-err" msg={errs._} />
        <button type="submit" className={btn}>Submit new issue</button>
      </form>
    </section>
  );
}

type TimelineItem = { kind: 'comment' | 'event'; id: string; author?: string; actor?: string; body?: string; text?: string; createdAt: string; reactions?: Record<string, { count: number; mine: boolean }> };

function Reactions({ reactions, canReact, onToggle, target }: { reactions: Record<string, { count: number; mine: boolean }>; canReact: boolean; onToggle: (c: string) => void; target: string }) {
  return (
    <div className="flex gap-2 items-center mt-2">
      {REACTIONS.filter(([k]) => reactions[k]).map(([k, emoji]) => (
        <button key={k} type="button" aria-pressed={reactions[k].mine} disabled={!canReact} aria-label={`${k} reaction ${reactions[k].count}`}
          className={`border rounded-full px-2 text-sm ${reactions[k].mine ? 'bg-blue-50 border-blue-400' : ''}`} onClick={() => onToggle(k)}>
          {emoji} {reactions[k].count}
        </button>
      ))}
      {canReact && <MenuButton label={`Add reaction to ${target}`} buttonText="☺" items={REACTIONS.map(([k, emoji]) => ({ label: `${emoji} ${k}`, onSelect: () => onToggle(k) }))} />}
    </div>
  );
}

function Timeline({ items, canReact, onReact }: { items: TimelineItem[]; canReact: boolean; onReact: (id: string, c: string) => void }) {
  return (
    <div>
      {items.map((t) => (t.kind === 'comment' ? (
        <article key={t.id} className="border rounded mb-3">
          <header className="bg-gray-50 px-3 py-1 border-b text-sm"><strong>{t.author}</strong> commented {ago(t.createdAt)}</header>
          <div className="px-3 py-2 whitespace-pre-wrap">{t.body}</div>
          <div className="px-3 pb-2"><Reactions reactions={t.reactions || {}} canReact={canReact} onToggle={(c) => onReact(t.id, c)} target={`comment by ${t.author}`} /></div>
        </article>
      ) : (
        <article key={t.id} className="text-sm text-gray-700 mb-3 pl-4">
          <strong>{t.actor}</strong> <span>{t.text}</span> <span className="text-gray-500">{ago(t.createdAt)}</span>
        </article>
      )))}
    </div>
  );
}

function CommentForm({ onSubmit }: { onSubmit: (body: string) => Promise<void> }) {
  const [body, setBody] = useState('');
  const [err, setErr] = useState('');
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!body.trim()) { setErr('Comment is required'); return; }
    try {
      await onSubmit(body);
      setBody('');
      setErr('');
    } catch (ex) {
      setErr(errorsOf(ex).body || errorsOf(ex)._);
    }
  };
  return (
    <form onSubmit={submit} noValidate className="border rounded p-3 mt-4">
      <Field label="Comment" textarea value={body} onChange={(v) => { setBody(v); }} error={err} />
      <button type="submit" className={btn}>Comment</button>
    </form>
  );
}

function SidebarSection({ title, picker, children }: { title: string; picker?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="border-b py-3">
      {picker || <p className="font-semibold text-sm">{title}</p>}
      <div className="text-sm mt-1">{children}</div>
    </div>
  );
}

function MilestonePicker({ current, options, onSet, can }: { current: string | null; options: string[]; onSet: (t: string | null) => Promise<void>; can: boolean }) {
  return (
    <SidebarSection title="Milestone" picker={can ? (
      <Picker label="Milestone" options={[{ name: 'None', selected: !current }, ...options.map((m) => ({ name: m, selected: m === current }))]}
        onPick={(n) => onSet(n === 'None' ? null : n)} />
    ) : undefined}>
      {current ? <span>{current}</span> : <span className="text-gray-600">No milestone</span>}
    </SidebarSection>
  );
}

export function IssuePage() {
  const { repo, reload: reloadRepo } = useRepo();
  const { n } = useParams() as { n: string };
  const ip = `/repos/${enc(repo.owner)}/${enc(repo.name)}/issues/${n}`;
  const { data, error, reload } = useLoad(() => get(ip), [ip]);
  const [editTitle, setEditTitle] = useState<string | null>(null);
  const [editBody, setEditBody] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [aq, setAq] = useState('');
  const { data: assignable } = useLoad(() => get(`/repos/${enc(repo.owner)}/${enc(repo.name)}/assignable?q=${enc(aq)}`), [repo.fullName, aq]);
  if (error) return <LoadError error={error} />;
  if (!data) return null;
  // Edit forms close as soon as Save is clicked so the page layout settles before the next action;
  // a rejected save reopens the form with the attempted value and the error.
  const patch = async (body: Record<string, string>, field: string) => {
    if (field === 'title') setEditTitle(null);
    if (field === 'body') setEditBody(null);
    try {
      await api('PATCH', ip, body);
      setErrs({});
      await reload();
      await reloadRepo();
    } catch (ex) {
      if (field === 'title') setEditTitle(body.title);
      if (field === 'body') setEditBody(body.body);
      setErrs({ [field]: errorsOf(ex)[field] || errorsOf(ex)._ });
    }
  };
  const act = async (method: string, path: string, body?: object) => { await api(method, `${ip}${path}`, body); await reload(); };
  const react = async (targetType: string, targetId: string, content: string) => {
    await api('POST', `/repos/${enc(repo.owner)}/${enc(repo.name)}/reactions`, { targetType, targetId, content });
    await reload();
  };
  return (
    <div>
      <div className="flex items-start gap-3 mb-2">
        {editTitle === null ? (
          <>
            <h2 className="text-2xl flex-1">{data.title}</h2>
            <span className="text-2xl text-gray-500">{`#${data.number}`}</span>
            {data.perms.edit && <button type="button" className={btn2} onClick={() => { setEditTitle(data.title); setErrs({}); }}>Edit issue title</button>}
          </>
        ) : (
          <form className="flex-1" noValidate onSubmit={(e) => { e.preventDefault(); patch({ title: editTitle }, 'title'); }}>
            <Field label="Issue title" value={editTitle} onChange={setEditTitle} error={errs.title} autoFocus />
            <div className="flex gap-2">
              <button type="submit" className={btn}>Save issue title</button>
              <button type="button" className={btn2} onClick={() => { setEditTitle(null); setErrs({}); }}>Cancel</button>
            </div>
          </form>
        )}
      </div>
      <p className="mb-4 flex items-center gap-2">
        <span className={`rounded-full px-3 py-0.5 text-white ${data.state === 'open' ? 'bg-green-700' : 'bg-purple-700'}`}>{data.state === 'open' ? 'Open' : 'Closed'}</span>
        <span className="text-sm text-gray-600">{`${data.author} opened this issue ${ago(data.createdAt)}`}</span>
      </p>
      <div className="flex gap-6">
        <div className="flex-1">
          <section className="border rounded mb-4">
            <header className="bg-gray-50 px-3 py-1 border-b text-sm flex items-center">
              <span><strong>{data.author}</strong> wrote</span>
              {data.perms.edit && editBody === null && <button type="button" className={`${btn2} ml-auto text-xs`} onClick={() => { setEditBody(data.body); setErrs({}); }}>Edit issue description</button>}
            </header>
            {editBody === null ? (
              <div className="px-3 py-2 whitespace-pre-wrap">{data.body || <em className="text-gray-500">No description provided.</em>}</div>
            ) : (
              <form className="p-3" noValidate onSubmit={(e) => { e.preventDefault(); patch({ body: editBody }, 'body'); }}>
                <Field label="Issue description" textarea value={editBody} onChange={setEditBody} error={errs.body} autoFocus />
                <div className="flex gap-2">
                  <button type="submit" className={btn}>Save issue description</button>
                  <button type="button" className={btn2} onClick={() => setEditBody(null)}>Cancel</button>
                </div>
              </form>
            )}
            <div className="px-3 pb-2"><Reactions reactions={data.reactions} canReact={data.perms.react} onToggle={(c) => react('issue', data.id, c)} target="issue" /></div>
          </section>
          <h3 className="font-semibold mb-2">Activity</h3>
          <Timeline items={data.timeline} canReact={data.perms.react} onReact={(id, c) => react('comment', id, c)} />
          {data.perms.triage && (
            <div className="mt-2">
              {data.state === 'open'
                ? <button type="button" className={btn2} onClick={() => patch({ state: 'closed' }, 'state')}>Close issue</button>
                : <button type="button" className={btn2} onClick={() => patch({ state: 'open' }, 'state')}>Reopen issue</button>}
            </div>
          )}
          {data.perms.comment && <CommentForm onSubmit={async (body) => { await api('POST', `${ip}/comments`, { body }); await reload(); }} />}
        </div>
        <aside className="w-64 shrink-0">
          <SidebarSection title="Assignees" picker={data.perms.triage ? (
            <Picker label="Assignees" search={{ label: 'Search assignees', value: aq, onChange: setAq }}
              options={(assignable?.users || []).map((u: string) => ({ name: u, selected: data.assignees.includes(u) }))}
              onPick={async (u) => { await act('POST', '/assignees', { username: u }); setAq(''); }} />
          ) : undefined}>
            {data.assignees.length ? data.assignees.map((a: string) => <div key={a}>{a}</div>) : <span className="text-gray-600">No one assigned</span>}
          </SidebarSection>
          <SidebarSection title="Labels" picker={data.perms.triage ? (
            <Picker label="Labels" options={data.repoLabels.map((l: string) => ({ name: l, selected: data.labels.includes(l) }))}
              onPick={(l) => act('POST', '/labels', { name: l })} />
          ) : undefined}>
            {data.labels.length ? data.labels.map((l: string) => <span key={l} className="mr-1"><Badge>{l}</Badge></span>) : <span className="text-gray-600">None yet</span>}
          </SidebarSection>
          <MilestonePicker current={data.milestone} options={data.repoMilestones} can={data.perms.triage} onSet={(t) => act('PUT', '/milestone', { title: t })} />
        </aside>
      </div>
    </div>
  );
}

// ================= Pull requests =================
export function Pulls() {
  const { repo, base } = useRepo();
  const [sp, set] = useParamState();
  const state = sp.get('state') || 'open';
  const author = sp.get('author') || '';
  const { data, error } = useLoad(() => get(`/repos/${enc(repo.owner)}/${enc(repo.name)}/pulls?state=${enc(state)}&author=${enc(author)}`), [repo.fullName, state, author]);
  if (error) return <LoadError error={error} />;
  const stateLink = (s: string, text: string, count?: number) => {
    const next = new URLSearchParams(sp);
    next.set('state', s);
    return (
      <span className={state === s ? 'font-semibold' : ''}>
        <Link to={`?${next}`} replace aria-current={state === s ? 'page' : undefined}>{text}</Link>
        {count !== undefined && <span className="ml-1 text-sm text-gray-600">{count}</span>}
      </span>
    );
  };
  return (
    <section>
      <div className="flex items-center gap-3 mb-3">
        <label className="text-sm">Author <input className="border rounded px-2 py-1 ml-1" value={author} onChange={(e) => set('author', e.target.value)} /></label>
        <div className="ml-auto">{data?.canCreate && <Link className={btn} to={`${base}/compare`}>New pull request</Link>}</div>
      </div>
      <div className="border rounded">
        <div className="bg-gray-50 px-3 py-2 flex items-center gap-4 border-b">
          {stateLink('open', 'Open', data?.counts.open)}
          {stateLink('closed', 'Closed', data?.counts.closed)}
          {stateLink('merged', 'Merged', data?.counts.merged)}
          {stateLink('draft', 'Draft', data?.counts.draft)}
        </div>
        {data && data.rows.length === 0 && <p className="px-3 py-4">No pull requests matched your search.</p>}
        <ul>
          {(data?.rows || []).map((p: { number: number; title: string; author: string; status: string; base: string; head: string; updatedAt: string }) => (
            <li key={p.number} className="border-b last:border-b-0 px-3 py-2">
              <Link className="font-semibold hover:text-blue-700" to={`${base}/pull/${p.number}`}>{p.title}</Link>
              <span className="ml-2"><Badge>{p.status}</Badge></span>
              <p className="text-sm text-gray-600">{`#${p.number} opened by ${p.author} · ${p.head} → ${p.base} · updated ${ago(p.updatedAt)}`}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function Compare() {
  const { repo, base, reload: reloadRepo } = useRepo();
  const params = useParams();
  const nav = useNavigate();
  const spec = params['*'] ? decodeURIComponent(params['*']) : '';
  const [b0, h0] = spec.includes('...') ? spec.split('...') : [repo.defaultBranch, spec || repo.defaultBranch];
  const [baseB, setBaseB] = useState(b0);
  const [headB, setHeadB] = useState(h0);
  const cp = `/repos/${enc(repo.owner)}/${enc(repo.name)}/compare?base=${enc(baseB)}&head=${enc(headB)}`;
  const { data } = useLoad(() => get(cp), [cp]);
  const [form, setForm] = useState<null | 'normal' | 'draft'>(null);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});
  const noChanges = baseB === headB || (data && data.identical);
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api('POST', `/repos/${enc(repo.owner)}/${enc(repo.name)}/pulls`, { base: baseB, head: headB, title, body, draft: form === 'draft' });
      await reloadRepo();
      nav(`${base}/pull/${r.number}`);
    } catch (ex) {
      setErrs(errorsOf(ex));
    }
  };
  const sel = (label: string, value: string, set: (v: string) => void) => (
    <label className="text-sm font-semibold">
      {label}
      {/* REQ-6-2-2 explicitly requires native selects named base and compare. */}
      <select className="border rounded px-1 ml-1 font-normal" value={value} onChange={(e) => { set(e.target.value); setForm(null); }}>
        {repo.branches.map((b) => <option key={b} value={b} label={b} />)}
      </select>
    </label>
  );
  return (
    <section>
      <h2 className="text-xl mb-1">Comparing changes</h2>
      <p className="text-sm text-gray-600 mb-3">Choose two branches to see what changed or to start a new pull request.</p>
      <div className="flex items-center gap-3 border rounded p-2 bg-gray-50 mb-3">
        {sel('base', baseB, setBaseB)}
        <span aria-hidden="true">←</span>
        {sel('compare', headB, setHeadB)}
        <button type="button" className={btn2} onClick={() => nav(`${base}/compare/${encPath(baseB)}...${encPath(headB)}`, { replace: true })}>Compare changes</button>
      </div>
      {noChanges && <p className="mb-3 font-semibold">No changes</p>}
      {!noChanges && data && (
        <div className="mb-3">
          <p><strong>Commit summary</strong> <span>{`${data.commits.length} ${data.commits.length === 1 ? 'commit' : 'commits'}`}</span></p>
        </div>
      )}
      {repo.perms.write && form === null && (
        <div className="flex gap-2 mb-4">
          <button type="button" className={btn} disabled={!!noChanges || !data} onClick={() => { setForm('normal'); setErrs({}); }}>Create pull request</button>
          <button type="button" className={btn2} disabled={!!noChanges || !data} onClick={() => { setForm('draft'); setErrs({}); }}>Create draft pull request</button>
        </div>
      )}
      {!repo.perms.write && <p className="mb-3 text-sm">You need write access to create a pull request.</p>}
      {form && !noChanges && (
        <form onSubmit={create} noValidate className="border rounded p-3 mb-4 max-w-2xl">
          <Field label="Title" value={title} onChange={setTitle} error={errs.title} autoFocus />
          <Field label="Description" textarea value={body} onChange={setBody} error={errs.body} />
          <FieldError id="pr-create-err" msg={errs.base || errs._} />
          <div className="flex gap-2">
            <button type="submit" className={btn}>{form === 'draft' ? 'Create draft pull request' : 'Create pull request'}</button>
            <button type="button" className={btn2} onClick={() => setForm(null)}>Cancel</button>
          </div>
        </form>
      )}
      {!noChanges && data && (
        <>
          <ul className="mb-3 text-sm">
            {data.commits.map((c: { sha: string; message: string; author: string }) => <li key={c.sha}>{`${c.message} — ${c.author}`}</li>)}
          </ul>
          <DiffStat diff={data.diff} />
          <DiffView files={data.diff.files} />
        </>
      )}
    </section>
  );
}

type PR = any; // eslint-disable-line @typescript-eslint/no-explicit-any

const DECISION: Record<string, string> = { approve: 'Approved', request_changes: 'Changes requested', comment: 'Commented' };

export function PullPage({ tab }: { tab: 'conversation' | 'commits' | 'files' }) {
  const { repo, base, reload: reloadRepo } = useRepo();
  const { n } = useParams() as { n: string };
  const pp = `/repos/${enc(repo.owner)}/${enc(repo.name)}/pulls/${n}`;
  const { data, error, reload } = useLoad<PR>(() => get(pp), [pp]);
  const [rq, setRq] = useState('');
  const { data: cands } = useLoad(() => get(`${pp}/reviewer-candidates?q=${enc(rq)}`), [pp, rq]);
  const [merging, setMerging] = useState(false);
  const [mergeErr, setMergeErr] = useState('');
  const [readyOpen, setReadyOpen] = useState(false);
  const [checkStatus, setCheckStatus] = useState<string | null>(null);
  if (error) return <LoadError error={error} />;
  if (!data) return null;
  const act = async (method: string, path: string, body?: object) => { await api(method, `${pp}${path}`, body); await reload(); await reloadRepo(); };
  const tabLink = (label: string, to: string, key: string, count?: number) => (
    <span className={`px-3 py-2 ${tab === key ? 'border-b-2 border-orange-500 font-semibold' : ''}`}>
      <Link to={to} aria-current={tab === key ? 'page' : undefined}>{label}</Link>
      {count !== undefined && <span className="ml-1 text-xs bg-gray-200 rounded-full px-1.5">{count}</span>}
    </span>
  );
  const statusColor = { Open: 'bg-green-700', Draft: 'bg-gray-500', Closed: 'bg-red-700', Merged: 'bg-purple-700' }[data.status as string];
  const doMerge = async () => {
    try {
      await act('POST', '/merge');
      setMerging(false);
      setMergeErr('');
    } catch (ex) {
      setMergeErr(errorsOf(ex)._ || errorsOf(ex).merge);
    }
  };
  return (
    <div>
      <div className="flex items-start gap-3">
        <h2 className="text-2xl flex-1">{data.title}</h2>
        <span className="text-2xl text-gray-500">{`#${data.number}`}</span>
      </div>
      <p className="my-2 flex items-center gap-2 text-sm">
        <span className={`rounded-full px-3 py-0.5 text-white text-base ${statusColor}`}>{data.status}</span>
        <span>{data.author}</span>
        <span>{data.status === 'Merged' ? 'merged commits into' : 'wants to merge into'}</span>
        <code className="bg-blue-50 px-1">{data.base}</code>
        <span>from</span>
        <code className="bg-blue-50 px-1">{data.head}</code>
      </p>
      <nav className="flex gap-1 border-b mb-4">
        {tabLink('Conversation', `${base}/pull/${data.number}`, 'conversation')}
        {tabLink('Commits', `${base}/pull/${data.number}/commits`, 'commits', data.commits.length)}
        {tabLink('Files changed', `${base}/pull/${data.number}/files`, 'files', data.diff.files.length)}
      </nav>
      <Reviews data={data} />
      {tab === 'conversation' && (
        <div className="flex gap-6">
          <div className="flex-1">
            <section className="border rounded mb-4">
              <header className="bg-gray-50 px-3 py-1 border-b text-sm"><strong>{data.author}</strong> opened this pull request {ago(data.createdAt)}</header>
              <div className="px-3 py-2 whitespace-pre-wrap">{data.body || <em className="text-gray-500">No description provided.</em>}</div>
            </section>
            <Timeline items={data.timeline} canReact={false} onReact={() => {}} />
            {data.reviewComments.filter((c: { pending: boolean }) => !c.pending).length > 0 && (
              <section className="mb-3">
                <h3 className="font-semibold text-sm">Review comments</h3>
                {data.reviewComments.filter((c: { pending: boolean }) => !c.pending).map((c: { id: string; author: string; path: string; body: string }) => (
                  <p key={c.id} className="text-sm">{`${c.author} on ${c.path}: `}{c.body}</p>
                ))}
              </section>
            )}
            <section className="border rounded p-3 mb-3">
              <h3 className="font-semibold">Checks</h3>
              <p>{`test: ${data.check.status}`}</p>
              {data.check.setBy && <p className="text-sm text-gray-600">{`Set by ${data.check.setBy} ${ago(data.check.time)}`} <time dateTime={data.check.time}>{new Date(data.check.time).toLocaleString()}</time></p>}
              {data.perms.checks && (
                <div className="flex items-end gap-2 mt-2">
                  <Combobox label="test status" value={checkStatus ?? data.check.status} onChange={setCheckStatus}
                    options={['pending', 'success', 'failure'].map((s) => ({ value: s, label: s }))} />
                  <button type="button" className={`${btn2} mb-3`} onClick={async () => { await act('PUT', '/checks', { status: checkStatus ?? data.check.status }); setCheckStatus(null); }}>Save</button>
                </div>
              )}
            </section>
            {data.state === 'open' && (
              <section className="border rounded p-3 mb-3">
                <h3 className="font-semibold mb-1">Merge</h3>
                {data.draft && <p className="text-sm">This pull request is still a work in progress. Draft pull requests cannot be merged.</p>}
                <ul className="text-sm mb-2">
                  {data.merge.met.map((m: string) => <li key={m}><span aria-hidden="true">✓ </span>{m}</li>)}
                  {data.merge.reasons.map((m: string) => <li key={m} className="text-red-700"><span aria-hidden="true">✗ </span>{m}</li>)}
                </ul>
                {!data.perms.merge && <p className="text-sm text-gray-600 mb-2">Only Maintain, Admin, or organization Owner can merge.</p>}
                <fieldset className="mb-2 text-sm">
                  <legend className="sr-only">Merge method</legend>
                  <label><input type="radio" name="merge-method" checked readOnly /> Create a merge commit</label>
                </fieldset>
                {!merging && (
                  <button type="button" className={btn} disabled={!data.merge.mergeable || !data.perms.merge} onClick={() => setMerging(true)}>Merge pull request</button>
                )}
                {merging && (
                  <div className="flex gap-2">
                    <button type="button" className={btn} onClick={doMerge}>Confirm merge</button>
                    <button type="button" className={btn2} onClick={() => setMerging(false)}>Cancel</button>
                  </div>
                )}
                <FieldError id="merge-err" msg={mergeErr} />
              </section>
            )}
            {data.state === 'merged' && (
              <p className="border rounded p-3 mb-3">{`${data.mergedBy} merged commit ${data.mergeSha?.slice(0, 7)} into ${data.base} ${ago(data.mergedAt)}`}</p>
            )}
            <div className="flex gap-2 mb-3">
              {data.perms.ready && <button type="button" className={btn2} onClick={() => setReadyOpen(true)}>Ready for review</button>}
              {data.perms.closeReopen && data.state === 'open' && <button type="button" className={btn2} onClick={() => act('PATCH', '', { state: 'closed' })}>Close pull request</button>}
              {data.perms.closeReopen && data.state === 'closed' && <button type="button" className={btn2} onClick={() => act('PATCH', '', { state: 'open' })}>Reopen pull request</button>}
            </div>
            {readyOpen && (
              <Dialog title="Ready for review" onClose={() => setReadyOpen(false)}>
                <p className="mb-3">Mark this pull request as ready for review?</p>
                <div className="flex gap-2">
                  <button type="button" className={btn} onClick={async () => { setReadyOpen(false); await act('PATCH', '', { ready: true }); }}>Confirm</button>
                  <button type="button" className={btn2} onClick={() => setReadyOpen(false)}>Cancel</button>
                </div>
              </Dialog>
            )}
            {data.perms.comment && <CommentForm onSubmit={async (body) => { await act('POST', '/comments', { body }); }} />}
          </div>
          <aside className="w-64 shrink-0">
            <SidebarSection title="Reviewers" picker={data.perms.reviewers ? (
              <Picker label="Reviewers" hideGlobalSearch search={{ label: 'Search', value: rq, onChange: setRq }}
                options={(cands?.users || []).map((u: string) => ({ name: u, selected: data.reviewers.includes(u) }))}
                onPick={async (u) => { if (!data.reviewers.includes(u)) await act('POST', '/reviewers', { username: u }); setRq(''); }} />
            ) : undefined}>
              {data.reviewers.length === 0 && <span className="text-gray-600">No reviews requested</span>}
              {data.reviewers.map((u: string) => (
                <div key={u} className="flex items-center justify-between">
                  <span>{u}</span>
                  {data.perms.reviewers && <button type="button" aria-label={`Remove ${u}`} className="text-xs border rounded px-1" onClick={() => act('DELETE', `/reviewers/${enc(u)}`)}>Remove</button>}
                </div>
              ))}
            </SidebarSection>
            <MilestonePicker current={data.milestone} options={data.repoMilestones} can={data.perms.triage} onSet={(t) => act('PUT', '/milestone', { title: t })} />
          </aside>
        </div>
      )}
      {tab === 'commits' && (
        <section>
          <p className="mb-2"><strong>Commit summary</strong> <span>{`${data.commits.length} ${data.commits.length === 1 ? 'commit' : 'commits'}`}</span></p>
          <ul className="border rounded">
            {data.commits.map((c: { sha: string; short: string; message: string; author: string; time: string }) => (
              <li key={c.sha} className="border-b last:border-b-0 px-3 py-2">
                <Link className="font-semibold hover:text-blue-700" to={`${base}/commit/${c.sha}`}>{c.message}</Link>
                <p className="text-sm text-gray-600">{`${c.author} committed ${ago(c.time)} · ${c.short}`}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      {tab === 'files' && <FilesTab data={data} act={act} />}
    </div>
  );
}

function Reviews({ data }: { data: PR }) {
  if (!data.reviews.length) return null;
  return (
    <section className="border rounded p-3 mb-4">
      <h3 className="font-semibold text-sm mb-1">Reviews</h3>
      {data.reviews.map((r: { reviewer: string; decision: string; body: string; time: string; stale: boolean }, i: number) => (
        <div key={i} className="text-sm">
          <strong>{r.reviewer}</strong> <span className="font-semibold">{DECISION[r.decision]}</span>
          {r.stale && <span className="text-gray-500"> (outdated)</span>}
          <span className="text-gray-500"> {ago(r.time)}</span>
          {r.body && <p className="whitespace-pre-wrap">{r.body}</p>}
        </div>
      ))}
    </section>
  );
}

function FilesTab({ data, act }: { data: PR; act: (m: string, p: string, b?: object) => Promise<void> }) {
  const [reviewing, setReviewing] = useState(false);
  const [summary, setSummary] = useState('');
  const [decision, setDecision] = useState('');
  const [reviewErr, setReviewErr] = useState('');
  const [line, setLine] = useState<{ path: string; key: string } | null>(null);
  const [cbody, setCbody] = useState('');
  const [cerr, setCerr] = useState('');
  const submitReview = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await act('POST', '/reviews', { decision, body: summary });
      setReviewing(false); setSummary(''); setDecision(''); setReviewErr('');
    } catch (ex) {
      const f = errorsOf(ex);
      setReviewErr(f.decision || f.body || f._);
    }
  };
  const addInline = async (mode: 'single' | 'pending') => {
    if (!line) return;
    if (!cbody.trim()) { setCerr('Comment is required'); return; }
    try {
      await act('POST', '/review-comments', { path: line.path, line: line.key, body: cbody, mode });
      setLine(null); setCbody(''); setCerr('');
    } catch (ex) {
      setCerr(errorsOf(ex).body || errorsOf(ex)._);
    }
  };
  const comments = data.reviewComments as { id: string; author: string; path: string; line: string; body: string; pending: boolean; outdated: boolean }[];
  return (
    <section>
      <div className="flex items-center gap-3 mb-2">
        <DiffStat diff={data.diff} />
        {data.perms.review && !reviewing && <button type="button" className={`${btn} ml-auto`} onClick={() => setReviewing(true)}>Review changes</button>}
      </div>
      {reviewing && (
        <form onSubmit={submitReview} noValidate className="border rounded p-3 mb-3 max-w-xl">
          <Field label="Summary" textarea value={summary} onChange={setSummary} />
          <fieldset className="mb-2">
            <legend className="sr-only">Review decision</legend>
            {[['comment', 'Comment'], ['approve', 'Approve'], ['request_changes', 'Request changes']].map(([v, l]) => (
              <label key={v} className="block"><input type="radio" name="decision" checked={decision === v} onChange={() => setDecision(v)} /> {l}</label>
            ))}
          </fieldset>
          <FieldError id="review-err" msg={reviewErr} />
          <div className="flex gap-2">
            <button type="submit" className={btn}>Submit review</button>
            <button type="button" className={btn2} onClick={() => setReviewing(false)}>Cancel</button>
          </div>
        </form>
      )}
      <DiffView
        files={data.diff.files}
        lineAction={data.perms.inline ? (path, key) => (
          <button type="button" aria-label="Add comment" className="text-blue-700 font-bold w-6" onClick={() => { setLine({ path, key }); setCbody(''); setCerr(''); }}>+</button>
        ) : undefined}
        renderAfter={(path, key) => (
          <>
            {comments.filter((c) => c.path === path && c.line === key).map((c) => (
              <div key={c.id} className="border-y bg-white px-3 py-2 font-sans">
                <p className="text-sm"><strong>{c.author}</strong>{c.pending && <span className="ml-2"><Badge>Pending review</Badge></span>}{c.outdated && <span className="ml-2"><Badge>Outdated</Badge></span>}</p>
                <p className="whitespace-pre-wrap">{c.body}</p>
              </div>
            ))}
            {line && line.path === path && line.key === key && (
              <div className="border-y bg-gray-50 p-3 font-sans">
                <Field label="Comment" textarea value={cbody} onChange={setCbody} error={cerr} autoFocus />
                <div className="flex gap-2">
                  <button type="button" className={btn} onClick={() => addInline('single')}>Add single comment</button>
                  <button type="button" className={btn2} onClick={() => addInline('pending')}>Start a review</button>
                  <button type="button" className={btn2} onClick={() => setLine(null)}>Cancel</button>
                </div>
              </div>
            )}
          </>
        )}
      />
    </section>
  );
}

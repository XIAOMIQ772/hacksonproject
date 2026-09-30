const express = require('express');
const store = require('../store');
const L = require('../lib');
const G = require('../git');
const { h } = require('./util');

const r = express.Router();

// Loads the repository named in the URL and the caller's permissions; hides it when unreadable.
function ctx(req) {
  const s = store.get();
  const user = L.currentUser(req);
  const repo = L.findRepo(s, req.params.owner, req.params.repo);
  if (!repo || !L.repoRole(s, user, repo)) L.fail(404, 'Access denied');
  return { s, user, repo, p: L.perms(s, user, repo) };
}
const need = (cond) => { if (!cond) L.fail(403, 'You do not have permission to do this'); };

function validBranch(n) {
  return typeof n === 'string' && n.length > 0 && n.length <= 200 && /^[A-Za-z0-9._\/-]+$/.test(n)
    && !n.includes('..') && !n.includes('//') && !n.startsWith('/') && !n.startsWith('-') && !n.startsWith('.')
    && !n.endsWith('/') && !n.endsWith('.') && !n.endsWith('.lock') && !n.split('/').some((seg) => seg.startsWith('.'));
}

function commitView(s, c) {
  return { sha: c.sha, short: c.sha.slice(0, 7), message: c.message, author: L.userName(s, c.authorId), time: c.time, parents: c.parents };
}

function protectionFor(repo, branch) {
  return (repo.protections || []).find((p) => p.branch === branch) || null;
}

function repoView(s, user, repo) {
  const p = L.perms(s, user, repo);
  return {
    ...L.repoSummary(s, repo),
    perms: p,
    branches: Object.keys(repo.branches).sort((a, b) => (a === repo.defaultBranch ? -1 : b === repo.defaultBranch ? 1 : a.localeCompare(b))),
    openIssues: s.issues.filter((i) => i.repoId === repo.id && i.state === 'open').length,
    openPulls: s.pulls.filter((x) => x.repoId === repo.id && x.state === 'open').length,
    protections: repo.protections || [],
    canFork: !!user,
  };
}

r.get('/repos/:owner/:repo', h(async (req) => {
  const s = store.get();
  const user = L.currentUser(req);
  const repo = L.findRepo(s, req.params.owner, req.params.repo);
  if (!repo || !L.repoRole(s, user, repo)) L.fail(404, 'Access denied');
  return repoView(s, user, repo);
}));

// Resolves "<branch>/<path>" where the branch name itself may contain slashes.
function resolveSpec(repo, spec) {
  if (!spec) return { branch: repo.defaultBranch, path: '' };
  const names = Object.keys(repo.branches).sort((a, b) => b.length - a.length);
  const b = names.find((n) => spec === n || spec.startsWith(`${n}/`));
  if (!b) {
    if (/^[0-9a-f]{40}$/.test(spec.split('/')[0])) return { branch: spec.split('/')[0], path: spec.split('/').slice(1).join('/'), sha: spec.split('/')[0] };
    L.fail(404, 'Branch not found');
  }
  return { branch: b, path: spec.slice(b.length + 1) };
}

r.get('/repos/:owner/:repo/contents', h(async (req) => {
  const { s, repo } = ctx(req);
  if (!Object.keys(repo.branches).length) return { empty: true };
  const { branch, path, sha } = resolveSpec(repo, String(req.query.spec || ''));
  const head = sha || repo.branches[branch];
  const commit = s.commits[head];
  if (!commit) L.fail(404, 'Branch not found');
  const tree = commit.tree;
  const history = G.log(s, head, path && tree[path] !== undefined ? path : undefined);
  const last = history[0] ? commitView(s, history[0]) : null;
  const base = { branch, path, lastCommit: last, commitCount: G.log(s, head).length };
  if (path && tree[path] !== undefined) return { ...base, type: 'file', content: tree[path] };
  if (path && !G.isDir(tree, path)) L.fail(404, 'Path not found');
  const readme = !path && tree['README.md'] !== undefined ? tree['README.md'] : null;
  return { ...base, type: 'dir', entries: G.listDir(tree, path), readme };
}));

r.post('/repos/:owner/:repo/branches', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  need(p.write);
  const name = String(req.body?.name ?? '');
  const from = String(req.body?.from || repo.defaultBranch);
  if (!validBranch(name)) L.fail(422, 'Invalid branch', { name: 'Invalid branch' });
  if (repo.branches[name]) L.fail(422, 'Branch already exists', { name: 'Branch already exists' });
  if (!repo.branches[from]) L.fail(422, 'Base branch not found');
  await store.mutate((d) => {
    const dr = d.repos.find((x) => x.id === repo.id);
    dr.branches[name] = repo.branches[from];
    dr.branchMeta = { ...(dr.branchMeta || {}), [name]: { base: repo.branches[from], creator: user.id, time: new Date().toISOString() } };
  });
  return { name };
}));

function validPath(p) {
  return p && !p.startsWith('/') && !p.split('/').some((seg) => seg === '..' || seg === '' || seg === '.');
}

r.post('/repos/:owner/:repo/files', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  need(p.write);
  const branch = String(req.body?.branch || repo.defaultBranch);
  const path = String(req.body?.path ?? '').trim();
  const content = String(req.body?.content ?? '');
  const message = String(req.body?.message ?? '').trim();
  const head = repo.branches[branch];
  const tree = head ? s.commits[head].tree : {};
  const fields = {};
  if (!validPath(path)) fields.path = 'Invalid file path';
  else if (tree[path] !== undefined || G.isDir(tree, path) || path.split('/').slice(0, -1).some((_, i, a) => tree[a.slice(0, i + 1).join('/')] !== undefined)) fields.path = 'A file with this path already exists';
  if (!message) fields.message = 'Commit message is required';
  else if (message.length > 72) fields.message = 'Commit message must be 72 characters or fewer';
  if (protectionFor(repo, branch)) fields.branch = 'Protected branch cannot be updated directly';
  if (Object.keys(fields).length) L.fail(422, Object.values(fields)[0], fields);
  const sha = await store.mutate((d) => {
    const id = G.makeCommit(d, { parents: head ? [head] : [], message, authorId: user.id, tree: { ...tree, [path]: content } });
    const dr = d.repos.find((x) => x.id === repo.id);
    dr.branches[branch] = id;
    dr.updatedAt = new Date().toISOString();
    return id;
  });
  return { sha, branch, path };
}));

r.get('/repos/:owner/:repo/commits', h(async (req) => {
  const { s, repo } = ctx(req);
  const branch = String(req.query.ref || repo.defaultBranch);
  const head = repo.branches[branch];
  if (!head) return { branch, commits: [] };
  const path = req.query.path ? String(req.query.path) : undefined;
  return { branch, path: path || null, commits: G.log(s, head, path).map((c) => commitView(s, c)) };
}));

r.get('/repos/:owner/:repo/commit/:sha', h(async (req) => {
  const { s } = ctx(req);
  const c = Object.values(s.commits).find((x) => x.sha === req.params.sha || x.sha.startsWith(req.params.sha));
  if (!c) L.fail(404, 'Commit not found');
  const parent = c.parents[0] ? s.commits[c.parents[0]] : null;
  return { ...commitView(s, c), diff: G.diffTrees(parent?.tree || {}, c.tree) };
}));

function compare(s, repo, base, head) {
  const b = repo.branches[base];
  const hd = repo.branches[head];
  if (!b || !hd) L.fail(404, 'Branch not found');
  const mb = G.mergeBase(s, b, hd);
  const baseAnc = G.ancestors(s, b);
  const commits = G.log(s, hd).filter((c) => !baseAnc.has(c.sha)).map((c) => commitView(s, c)).reverse();
  const diff = G.diffTrees(mb ? s.commits[mb].tree : {}, s.commits[hd].tree);
  return { base, head, commits, diff, identical: base === head || commits.length === 0 || diff.files.length === 0 };
}

r.get('/repos/:owner/:repo/compare', h(async (req) => {
  const { s, repo, p } = ctx(req);
  const base = String(req.query.base || repo.defaultBranch);
  const head = String(req.query.head || repo.defaultBranch);
  return { ...compare(s, repo, base, head), canCreate: p.write };
}));

const LANG = { md: 'Markdown', ts: 'TypeScript', js: 'JavaScript', json: 'JSON', txt: 'Text', py: 'Python' };

r.get('/repos/:owner/:repo/search', h(async (req) => {
  const { s, repo } = ctx(req);
  const q = String(req.query.q || '').trim();
  const pathFilter = String(req.query.path || '').trim();
  const lang = String(req.query.lang || '').trim().toLowerCase();
  const branch = String(req.query.ref || repo.defaultBranch);
  const head = repo.branches[branch];
  if (!q || !head) return { branch, results: [] };
  const tree = s.commits[head].tree;
  const needle = q.toLowerCase();
  const results = [];
  for (const [path, content] of Object.entries(tree).sort()) {
    if (pathFilter && !path.startsWith(pathFilter)) continue;
    const ext = path.split('.').pop().toLowerCase();
    if (lang && (LANG[ext] || ext).toLowerCase() !== lang) continue;
    const lines = content.split('\n');
    const matches = lines.map((text, i) => ({ lineNo: i + 1, text })).filter((l) => l.text.toLowerCase().includes(needle));
    if (matches.length) results.push({ path, name: path.split('/').pop(), language: LANG[ext] || ext, branch, matches: matches.slice(0, 5) });
  }
  return { branch, results };
}));

r.get('/search/repos', h(async (req) => {
  const s = store.get();
  const user = L.currentUser(req);
  const q = String(req.query.q || '').trim().toLowerCase();
  if (!q) return { results: [] };
  const results = s.repos
    .filter((rp) => L.repoRole(s, user, rp))
    .map((rp) => L.repoSummary(s, rp))
    .filter((rp) => rp.fullName.toLowerCase().includes(q) || (rp.description || '').toLowerCase().includes(q))
    .sort((a, b) => (a.name.toLowerCase() === q ? -1 : b.name.toLowerCase() === q ? 1 : a.updatedAt < b.updatedAt ? 1 : -1));
  return { results };
}));

// ---- creation and forking ----
function validRepoName(n) {
  return /^[A-Za-z0-9._-]{1,100}$/.test(n) && n !== '.' && n !== '..';
}

function ownerRef(s, user, login) {
  const o = L.findOwner(s, login);
  if (!o || !L.creatableOwners(s, user).includes(login)) L.fail(403, 'You cannot create repositories for this owner', { owner: 'You cannot create repositories for this owner' });
  return o;
}

r.post('/repos', h(async (req) => {
  const user = L.requireUser(req);
  const s = store.get();
  const b = req.body || {};
  const owner = String(b.owner || user.username);
  const name = String(b.name ?? '').trim();
  const o = ownerRef(s, user, owner);
  const fields = {};
  if (!name) fields.name = 'Repository name is required';
  else if (!validRepoName(name)) fields.name = 'Repository name format is invalid';
  else if (L.findRepo(s, owner, name)) fields.name = 'Repository name already exists';
  if (Object.keys(fields).length) L.fail(422, Object.values(fields)[0], fields);
  const visibility = b.visibility === 'private' ? 'private' : 'public';
  const description = String(b.description ?? '').trim();
  await store.mutate((d) => {
    const now = new Date().toISOString();
    const repo = { id: store.nextId(d, 'r'), ownerType: o.type, ownerId: o.id, name, description, visibility, defaultBranch: 'main', createdBy: user.id, createdAt: now, updatedAt: now, forkOf: null, branches: {}, protections: [], nextNumber: 1 };
    if (b.readme) {
      repo.branches.main = G.makeCommit(d, { parents: [], message: 'Initial commit', authorId: user.id, tree: { 'README.md': `# ${name}\n\n${description}`.trimEnd() + '\n' } });
    }
    d.repos.push(repo);
  });
  return { owner, name };
}));

r.post('/repos/:owner/:repo/forks', h(async (req) => {
  const { s, user, repo } = ctx(req);
  if (!user) L.fail(401, 'Sign in required');
  const b = req.body || {};
  const owner = String(b.owner || user.username);
  const name = String(b.name ?? '').trim() || repo.name;
  const o = ownerRef(s, user, owner);
  const fields = {};
  if (!validRepoName(name)) fields.name = 'Repository name format is invalid';
  else if (L.findRepo(s, owner, name)) fields.name = 'Repository name already exists';
  if (Object.keys(fields).length) L.fail(422, Object.values(fields)[0], fields);
  const visibility = repo.visibility === 'private' ? 'private' : b.visibility === 'private' ? 'private' : 'public';
  await store.mutate((d) => {
    const now = new Date().toISOString();
    const branches = repo.branches[repo.defaultBranch] ? { [repo.defaultBranch]: repo.branches[repo.defaultBranch] } : {};
    d.repos.push({ id: store.nextId(d, 'r'), ownerType: o.type, ownerId: o.id, name, description: repo.description, visibility, defaultBranch: repo.defaultBranch, createdBy: user.id, createdAt: now, updatedAt: now, forkOf: repo.id, branches, protections: [], nextNumber: 1 });
  });
  return { owner, name };
}));

// ---- settings ----
r.put('/repos/:owner/:repo/visibility', h(async (req) => {
  const { repo, p } = ctx(req);
  need(p.admin);
  const v = req.body?.visibility === 'private' ? 'private' : 'public';
  await store.mutate((d) => { const dr = d.repos.find((x) => x.id === repo.id); dr.visibility = v; dr.updatedAt = new Date().toISOString(); });
  return { visibility: v };
}));

r.put('/repos/:owner/:repo/default-branch', h(async (req) => {
  const { user, repo, p } = ctx(req);
  need(p.admin);
  const b = String(req.body?.branch ?? '');
  if (!repo.branches[b]) L.fail(422, 'Branch not found');
  await store.mutate((d) => { const dr = d.repos.find((x) => x.id === repo.id); dr.defaultBranch = b; dr.defaultBranchChange = { by: user.id, time: new Date().toISOString() }; });
  return { defaultBranch: b };
}));

r.post('/repos/:owner/:repo/protections', h(async (req) => {
  const { user, repo, p } = ctx(req);
  need(p.admin);
  const branch = String(req.body?.branch ?? '').trim();
  if (!branch) L.fail(422, 'Branch name pattern is required', { branch: 'Branch name pattern is required' });
  const rule = { branch, requireApproval: !!req.body?.requireApproval, requireCheck: !!req.body?.requireCheck, by: user.id, time: new Date().toISOString() };
  const original = String(req.body?.original ?? '');
  await store.mutate((d) => {
    const dr = d.repos.find((x) => x.id === repo.id);
    dr.protections = (dr.protections || []).filter((x) => x.branch !== branch && x.branch !== original);
    dr.protections.push(rule);
  });
  return rule;
}));

// ---- access management ----
function repoOrg(s, repo) {
  return repo.ownerType === 'org' ? s.orgs.find((o) => o.id === repo.ownerId) : null;
}

r.get('/repos/:owner/:repo/access', h(async (req) => {
  const { s, repo, p } = ctx(req);
  need(p.admin);
  const grants = s.grants.filter((g) => g.repoId === repo.id).map((g) => ({
    subjectType: g.subjectType,
    name: g.subjectType === 'team' ? s.teams.find((t) => t.id === g.subjectId)?.name : L.userName(s, g.subjectId),
    role: g.role,
  }));
  return { grants };
}));

r.get('/repos/:owner/:repo/access/candidates', h(async (req) => {
  const { s, repo, p } = ctx(req);
  need(p.admin);
  const q = String(req.query.q || '').trim().toLowerCase();
  const org = repoOrg(s, repo);
  const users = org ? s.orgMembers.filter((m) => m.orgId === org.id).map((m) => L.userById(s, m.userId)) : s.users;
  const teams = org ? s.teams.filter((t) => t.orgId === org.id) : [];
  const out = [
    ...teams.filter((t) => t.name.toLowerCase().includes(q)).map((t) => ({ subjectType: 'team', name: t.name })),
    ...users.filter((u) => u && u.username.toLowerCase().includes(q)).map((u) => ({ subjectType: 'user', name: u.username })),
  ];
  return { candidates: q ? out.slice(0, 50) : out.slice(0, 20) };
}));

r.post('/repos/:owner/:repo/access', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  need(p.admin);
  const role = String(req.body?.role ?? '').toLowerCase();
  if (!L.ROLES.includes(role)) L.fail(422, 'Role is not supported', { role: 'Role is not supported' });
  const type = req.body?.subjectType === 'team' ? 'team' : 'user';
  const name = String(req.body?.name ?? '');
  const org = repoOrg(s, repo);
  let subjectId;
  if (type === 'team') subjectId = s.teams.find((t) => t.name === name && org && t.orgId === org.id)?.id;
  else {
    const u = s.users.find((x) => x.username === name);
    if (u && (!org || L.orgRole(s, u, org.id))) subjectId = u.id;
  }
  if (!subjectId) L.fail(422, 'Select a member or team of this organization', { subject: 'Select a member or team of this organization' });
  await store.mutate((d) => {
    const existing = d.grants.find((g) => g.repoId === repo.id && g.subjectType === type && g.subjectId === subjectId);
    if (existing) Object.assign(existing, { role, grantorId: user.id, time: new Date().toISOString() });
    else d.grants.push({ repoId: repo.id, subjectType: type, subjectId, role, grantorId: user.id, time: new Date().toISOString() });
  });
  return { ok: true };
}));

module.exports = { router: r, ctx, need, compare, commitView, protectionFor, validBranch };

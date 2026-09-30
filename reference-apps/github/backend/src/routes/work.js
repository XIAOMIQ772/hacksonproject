const express = require('express');
const store = require('../store');
const L = require('../lib');
const G = require('../git');
const { h } = require('./util');
const { ctx, need, compare, commitView, protectionFor } = require('./repos');

const r = express.Router();
const now = () => new Date().toISOString();

function addEvent(d, targetType, targetId, actorId, text) {
  d.events.push({ id: store.nextId(d, 'e'), targetType, targetId, actorId, text, createdAt: now() });
}

function timeline(s, targetType, targetId, viewer) {
  const items = [
    ...s.comments.filter((c) => c.targetType === targetType && c.targetId === targetId).map((c) => ({
      kind: 'comment', id: c.id, author: L.userName(s, c.authorId), body: c.body, createdAt: c.createdAt,
      reactions: reactionSummary(s, 'comment', c.id, viewer),
    })),
    ...s.events.filter((e) => e.targetType === targetType && e.targetId === targetId).map((e) => ({ kind: 'event', id: e.id, actor: L.userName(s, e.actorId), text: e.text, createdAt: e.createdAt })),
  ];
  return items.sort((a, b) => (a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : a.id.localeCompare(b.id, undefined, { numeric: true })));
}

function reactionSummary(s, targetType, targetId, viewer) {
  const out = {};
  for (const x of s.reactions.filter((x) => x.targetType === targetType && x.targetId === targetId)) {
    out[x.content] = out[x.content] || { count: 0, mine: false };
    out[x.content].count += 1;
    if (viewer && x.userId === viewer.id) out[x.content].mine = true;
  }
  return out;
}

const labelNames = (s, ids) => ids.map((id) => s.labels.find((l) => l.id === id)?.name).filter(Boolean);
const milestoneTitle = (s, id) => s.milestones.find((m) => m.id === id)?.title || null;

// Accounts whose effective role on the repo is at least Triage.
function assignable(s, repo) {
  return s.users.filter((u) => ['triage', 'write', 'maintain', 'admin'].includes(L.explicitRole(s, u, repo)));
}

// ================= Issues =================
function getIssue(s, repo, n) {
  const i = s.issues.find((x) => x.repoId === repo.id && x.number === Number(n));
  if (!i) L.fail(404, 'Issue not found');
  return i;
}

r.get('/repos/:owner/:repo/issues', h(async (req) => {
  const { s, repo, p } = ctx(req);
  const state = req.query.state === 'closed' ? 'closed' : 'open';
  const q = String(req.query.q || '').trim().toLowerCase();
  const label = String(req.query.label || '');
  const all = s.issues.filter((i) => i.repoId === repo.id);
  const match = (i) => (!q || i.title.toLowerCase().includes(q) || (i.body || '').toLowerCase().includes(q))
    && (!label || labelNames(s, i.labels).includes(label));
  const rows = all.filter((i) => i.state === state && match(i)).sort((a, b) => b.number - a.number).map((i) => ({
    number: i.number, title: i.title, state: i.state, author: L.userName(s, i.authorId), labels: labelNames(s, i.labels), updatedAt: i.updatedAt,
  }));
  return {
    rows,
    openCount: all.filter((i) => i.state === 'open' && match(i)).length,
    closedCount: all.filter((i) => i.state === 'closed' && match(i)).length,
    labels: s.labels.filter((l) => l.repoId === repo.id).map((l) => l.name),
    canCreate: p.write,
  };
}));

r.post('/repos/:owner/:repo/issues', h(async (req) => {
  const { user, repo, p } = ctx(req);
  need(p.write);
  const title = String(req.body?.title ?? '').trim();
  if (!title) L.fail(422, 'Title is required', { title: 'Title is required' });
  if (title.length > 256) L.fail(422, 'Title is too long (maximum is 256 characters)', { title: 'Title is too long (maximum is 256 characters)' });
  const number = await store.mutate((d) => {
    const dr = d.repos.find((x) => x.id === repo.id);
    const num = dr.nextNumber++;
    const id = store.nextId(d, 'i');
    d.issues.push({ id, repoId: repo.id, number: num, title, body: String(req.body?.body ?? ''), authorId: user.id, state: 'open', createdAt: now(), updatedAt: now(), assignees: [], labels: [], milestoneId: null });
    addEvent(d, 'issue', id, user.id, 'opened this issue');
    return num;
  });
  return { number };
}));

r.get('/repos/:owner/:repo/issues/:n', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const i = getIssue(s, repo, req.params.n);
  return {
    id: i.id, number: i.number, title: i.title, body: i.body, state: i.state, author: L.userName(s, i.authorId), createdAt: i.createdAt,
    assignees: i.assignees.map((id) => L.userName(s, id)), labels: labelNames(s, i.labels), milestone: milestoneTitle(s, i.milestoneId),
    reactions: reactionSummary(s, 'issue', i.id, user),
    timeline: timeline(s, 'issue', i.id, user),
    repoLabels: s.labels.filter((l) => l.repoId === repo.id).map((l) => l.name),
    repoMilestones: s.milestones.filter((m) => m.repoId === repo.id).map((m) => m.title),
    perms: { edit: p.write, comment: p.write, triage: p.triage, react: !!user },
  };
}));

r.patch('/repos/:owner/:repo/issues/:n', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const i = getIssue(s, repo, req.params.n);
  const b = req.body || {};
  if ('title' in b || 'body' in b) need(p.write);
  if ('state' in b) need(p.triage);
  if ('title' in b) {
    const t = String(b.title ?? '').trim();
    if (!t) L.fail(422, 'Title is required', { title: 'Title is required' });
    if (t.length > 256) L.fail(422, 'Title is too long (maximum is 256 characters)', { title: 'Title is too long (maximum is 256 characters)' });
  }
  if ('body' in b && String(b.body).length > 65536) L.fail(422, 'Description is too long', { body: 'Description is too long' });
  await store.mutate((d) => {
    const di = d.issues.find((x) => x.id === i.id);
    if ('title' in b) { addEvent(d, 'issue', i.id, user.id, `changed the title from ${di.title} to ${String(b.title).trim()}`); di.title = String(b.title).trim(); }
    if ('body' in b) { di.body = String(b.body); addEvent(d, 'issue', i.id, user.id, 'edited the description'); }
    if ('state' in b) {
      const st = b.state === 'closed' ? 'closed' : 'open';
      if (st !== di.state) { di.state = st; addEvent(d, 'issue', i.id, user.id, st === 'closed' ? 'Closed issue' : 'Reopened issue'); }
    }
    di.updatedAt = now();
  });
  return { ok: true };
}));

function addComment(targetType) {
  return h(async (req) => {
    const { s, user, repo, p } = ctx(req);
    const target = targetType === 'issue' ? getIssue(s, repo, req.params.n) : getPull(s, repo, req.params.n);
    need(p.write);
    const body = String(req.body?.body ?? '');
    if (!body.trim()) L.fail(422, 'Comment is required', { body: 'Comment is required' });
    if (body.length > 65536) L.fail(422, 'Comment is too long', { body: 'Comment is too long' });
    await store.mutate((d) => {
      d.comments.push({ id: store.nextId(d, 'c'), targetType, targetId: target.id, authorId: user.id, body, createdAt: now() });
      const coll = targetType === 'issue' ? d.issues : d.pulls;
      coll.find((x) => x.id === target.id).updatedAt = now();
    });
    return { ok: true };
  });
}
r.post('/repos/:owner/:repo/issues/:n/comments', addComment('issue'));

r.get('/repos/:owner/:repo/assignable', h(async (req) => {
  const { s, repo } = ctx(req);
  const q = String(req.query.q || '').trim().toLowerCase();
  return { users: assignable(s, repo).map((u) => u.username).filter((n) => n.toLowerCase().includes(q)) };
}));

r.post('/repos/:owner/:repo/issues/:n/assignees', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  need(p.triage);
  const i = getIssue(s, repo, req.params.n);
  const target = assignable(s, repo).find((u) => u.username === req.body?.username);
  if (!target) L.fail(422, 'Account cannot be assigned', { username: 'Account cannot be assigned' });
  await store.mutate((d) => {
    const di = d.issues.find((x) => x.id === i.id);
    if (di.assignees.includes(target.id)) { di.assignees = di.assignees.filter((x) => x !== target.id); addEvent(d, 'issue', i.id, user.id, `unassigned ${target.username}`); }
    else { di.assignees.push(target.id); addEvent(d, 'issue', i.id, user.id, `assigned ${target.username}`); }
    di.updatedAt = now();
  });
  return { ok: true };
}));

r.post('/repos/:owner/:repo/issues/:n/labels', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  need(p.triage);
  const i = getIssue(s, repo, req.params.n);
  const label = s.labels.find((l) => l.repoId === repo.id && l.name === req.body?.name);
  if (!label) L.fail(422, 'Label not found in this repository');
  await store.mutate((d) => {
    const di = d.issues.find((x) => x.id === i.id);
    if (di.labels.includes(label.id)) { di.labels = di.labels.filter((x) => x !== label.id); addEvent(d, 'issue', i.id, user.id, `removed the ${label.name} label`); }
    else { di.labels.push(label.id); addEvent(d, 'issue', i.id, user.id, `added the ${label.name} label`); }
    di.updatedAt = now();
  });
  return { ok: true };
}));

function setMilestone(kind) {
  return h(async (req) => {
    const { s, user, repo, p } = ctx(req);
    need(p.triage);
    const item = kind === 'issue' ? getIssue(s, repo, req.params.n) : getPull(s, repo, req.params.n);
    const title = req.body?.title;
    const m = title ? s.milestones.find((x) => x.repoId === repo.id && x.title === title) : null;
    if (title && !m) L.fail(422, 'Milestone not found in this repository');
    await store.mutate((d) => {
      const coll = kind === 'issue' ? d.issues : d.pulls;
      const di = coll.find((x) => x.id === item.id);
      di.milestoneId = m ? m.id : null;
      addEvent(d, kind === 'issue' ? 'issue' : 'pr', item.id, user.id, m ? `added this to the ${m.title} milestone` : 'removed the milestone');
    });
    return { ok: true };
  });
}
r.put('/repos/:owner/:repo/issues/:n/milestone', setMilestone('issue'));

r.post('/repos/:owner/:repo/reactions', h(async (req) => {
  const { s, user } = ctx(req);
  if (!user) L.fail(401, 'Sign in required');
  const { targetType, targetId, content } = req.body || {};
  if (!['comment', 'issue'].includes(targetType) || !content) L.fail(422, 'Invalid reaction');
  await store.mutate((d) => {
    const ex = d.reactions.find((x) => x.targetType === targetType && x.targetId === targetId && x.userId === user.id && x.content === content);
    if (ex) d.reactions = d.reactions.filter((x) => x !== ex);
    else d.reactions.push({ targetType, targetId, userId: user.id, content });
  });
  return { ok: true, s: !!s };
}));

// ================= Pull requests =================
function getPull(s, repo, n) {
  const x = s.pulls.find((y) => y.repoId === repo.id && y.number === Number(n));
  if (!x) L.fail(404, 'Pull request not found');
  return x;
}

function prStatus(pr) {
  if (pr.state === 'merged') return 'Merged';
  if (pr.state === 'closed') return 'Closed';
  return pr.draft ? 'Draft' : 'Open';
}

r.get('/repos/:owner/:repo/pulls', h(async (req) => {
  const { s, repo, p } = ctx(req);
  const state = String(req.query.state || 'open');
  const author = String(req.query.author || '').trim().toLowerCase();
  const all = s.pulls.filter((x) => x.repoId === repo.id && (!author || L.userName(s, x.authorId).toLowerCase().includes(author)));
  const pick = (x) => (state === 'all' ? true : state === 'draft' ? x.state === 'open' && x.draft : state === 'open' ? x.state === 'open' : x.state === state);
  return {
    rows: all.filter(pick).sort((a, b) => b.number - a.number).map((x) => ({ number: x.number, title: x.title, author: L.userName(s, x.authorId), status: prStatus(x), base: x.base, head: x.head, updatedAt: x.updatedAt })),
    counts: { open: all.filter((x) => x.state === 'open').length, closed: all.filter((x) => x.state === 'closed').length, merged: all.filter((x) => x.state === 'merged').length, draft: all.filter((x) => x.state === 'open' && x.draft).length },
    authors: [...new Set(s.pulls.filter((x) => x.repoId === repo.id).map((x) => L.userName(s, x.authorId)))],
    canCreate: p.write,
  };
}));

r.post('/repos/:owner/:repo/pulls', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  need(p.write);
  const b = req.body || {};
  const title = String(b.title ?? '').trim();
  const body = String(b.body ?? '');
  const fields = {};
  if (!title) fields.title = 'Title is required';
  else if (title.length > 256) fields.title = 'Title is too long (maximum is 256 characters)';
  if (body.length > 65536) fields.body = 'Description is too long';
  if (Object.keys(fields).length) L.fail(422, Object.values(fields)[0], fields);
  const cmp = compare(s, repo, String(b.base), String(b.head));
  if (cmp.identical) L.fail(422, 'No changes', { base: 'No changes' });
  const number = await store.mutate((d) => {
    const dr = d.repos.find((x) => x.id === repo.id);
    const num = dr.nextNumber++;
    const id = store.nextId(d, 'p');
    d.pulls.push({ id, repoId: repo.id, number: num, title, body, authorId: user.id, state: 'open', draft: !!b.draft, base: cmp.base, head: cmp.head, headSha: repo.branches[cmp.head], baseSha: repo.branches[cmp.base], createdAt: now(), updatedAt: now(), reviewers: [], milestoneId: null });
    addEvent(d, 'pr', id, user.id, b.draft ? 'opened this draft pull request' : 'opened this pull request');
    return num;
  });
  return { number };
}));

function checkFor(s, repo, sha) {
  return s.checks.find((c) => c.repoId === repo.id && c.sha === sha && c.name === 'test') || null;
}

// Effective decision per reviewer: latest review for the current compare commit.
function decisions(s, pr, headSha) {
  const out = {};
  for (const rv of s.reviews.filter((x) => x.prId === pr.id && x.commitSha === headSha && x.userId !== pr.authorId).sort((a, b) => (a.time < b.time ? -1 : 1))) {
    out[rv.userId] = rv;
  }
  return out;
}

function mergeState(s, repo, pr) {
  const headSha = repo.branches[pr.head];
  const baseSha = repo.branches[pr.base];
  const reasons = [];
  const met = [];
  if (!headSha || !baseSha) return { headSha, reasons: ['Branch no longer exists'], met, conflicts: [] };
  const mb = G.mergeBase(s, baseSha, headSha);
  const m = G.mergeTrees(mb ? s.commits[mb].tree : {}, s.commits[baseSha].tree, s.commits[headSha].tree);
  if (pr.draft) reasons.push('Draft pull requests cannot be merged');
  if (m.conflicts.length) reasons.push('This branch has conflicts that must be resolved');
  else met.push('No conflicts with base branch');
  const dec = Object.values(decisions(s, pr, headSha));
  if (dec.some((x) => x.decision === 'request_changes')) reasons.push('Changes requested');
  const rule = protectionFor(repo, pr.base);
  if (rule?.requireApproval) {
    if (dec.some((x) => x.decision === 'approve')) met.push('1 approval');
    else reasons.push('Review required by branch protection');
  }
  if (rule?.requireCheck) {
    if (checkFor(s, repo, headSha)?.status === 'success') met.push('Required status check test succeeded');
    else reasons.push('Required status check test must succeed');
  }
  return { headSha, baseSha, mergeBase: mb, tree: m.tree, conflicts: m.conflicts, reasons, met };
}

r.get('/repos/:owner/:repo/pulls/:n', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const pr = getPull(s, repo, req.params.n);
  const isAuthor = !!user && user.id === pr.authorId;
  let cmp = null;
  if (pr.state === 'merged') {
    const mc = s.commits[pr.mergeSha];
    const commits = G.log(s, pr.headSha).filter((c) => !G.ancestors(s, pr.baseSha).has(c.sha)).map((c) => commitView(s, c)).reverse();
    const mb = G.mergeBase(s, pr.baseSha, pr.headSha);
    cmp = { commits, diff: G.diffTrees(mb ? s.commits[mb].tree : {}, s.commits[pr.headSha].tree), mergeCommit: mc ? commitView(s, mc) : null };
  } else if (repo.branches[pr.head] && repo.branches[pr.base]) cmp = compare(s, repo, pr.base, pr.head);
  const ms = pr.state === 'open' ? mergeState(s, repo, pr) : { headSha: pr.headSha, reasons: [], met: [] };
  const headSha = ms.headSha || pr.headSha;
  const check = checkFor(s, repo, headSha);
  const dec = decisions(s, pr, headSha);
  const rc = s.reviewComments.filter((c) => c.prId === pr.id && (c.state === 'published' || (user && c.userId === user.id)));
  return {
    number: pr.number, title: pr.title, body: pr.body, status: prStatus(pr), state: pr.state, draft: pr.draft,
    author: L.userName(s, pr.authorId), base: pr.base, head: pr.head, createdAt: pr.createdAt, headSha,
    mergedBy: pr.mergedBy ? L.userName(s, pr.mergedBy) : null, mergedAt: pr.mergedAt || null, mergeSha: pr.mergeSha || null,
    commits: cmp?.commits || [], diff: cmp?.diff || { files: [], additions: 0, deletions: 0 },
    timeline: timeline(s, 'pr', pr.id, user),
    reviews: s.reviews.filter((x) => x.prId === pr.id).sort((a, b) => (a.time < b.time ? -1 : 1)).map((x) => ({ reviewer: L.userName(s, x.userId), decision: x.decision, body: x.body, time: x.time, stale: x.commitSha !== headSha })),
    decisions: Object.values(dec).map((x) => ({ reviewer: L.userName(s, x.userId), decision: x.decision })),
    reviewComments: rc.map((c) => ({ id: c.id, author: L.userName(s, c.userId), path: c.path, line: c.line, body: c.body, pending: c.state === 'pending', outdated: c.commitSha !== headSha, time: c.time })),
    reviewers: pr.reviewers.map((id) => L.userName(s, id)),
    milestone: milestoneTitle(s, pr.milestoneId),
    repoMilestones: s.milestones.filter((m) => m.repoId === repo.id).map((m) => m.title),
    check: { name: 'test', status: check?.status || 'pending', setBy: check ? L.userName(s, check.setBy) : null, time: check?.time || null },
    protection: protectionFor(repo, pr.base),
    merge: { reasons: ms.reasons, met: ms.met, mergeable: pr.state === 'open' && ms.reasons.length === 0 },
    perms: {
      comment: p.write,
      review: p.write && !isAuthor && pr.state === 'open' && !pr.draft,
      inline: p.write && !isAuthor && pr.state === 'open',
      merge: p.maintain,
      closeReopen: pr.state !== 'merged' && (isAuthor || p.maintain),
      ready: pr.state === 'open' && pr.draft && (isAuthor || p.maintain),
      reviewers: pr.state === 'open' && (isAuthor || p.maintain),
      checks: p.admin && pr.state === 'open',
      triage: p.triage,
    },
  };
}));

r.patch('/repos/:owner/:repo/pulls/:n', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const pr = getPull(s, repo, req.params.n);
  const isAuthor = !!user && user.id === pr.authorId;
  need(isAuthor || p.maintain);
  if (pr.state === 'merged') L.fail(422, 'Merged pull requests cannot change state');
  const b = req.body || {};
  await store.mutate((d) => {
    const dp = d.pulls.find((x) => x.id === pr.id);
    if (b.ready && dp.draft) { dp.draft = false; addEvent(d, 'pr', pr.id, user.id, 'Ready for review'); }
    if (b.state === 'closed' && dp.state === 'open') { dp.state = 'closed'; addEvent(d, 'pr', pr.id, user.id, 'Closed pull request'); }
    if (b.state === 'open' && dp.state === 'closed') { dp.state = 'open'; addEvent(d, 'pr', pr.id, user.id, 'Reopened pull request'); }
    dp.updatedAt = now();
  });
  return { ok: true };
}));

r.post('/repos/:owner/:repo/pulls/:n/comments', addComment('pr'));
r.put('/repos/:owner/:repo/pulls/:n/milestone', setMilestone('pr'));

function reviewerCandidates(s, repo, pr) {
  return s.users.filter((u) => u.id !== pr.authorId && ['write', 'maintain', 'admin'].includes(L.explicitRole(s, u, repo)));
}

r.get('/repos/:owner/:repo/pulls/:n/reviewer-candidates', h(async (req) => {
  const { s, repo } = ctx(req);
  const pr = getPull(s, repo, req.params.n);
  const q = String(req.query.q || '').trim().toLowerCase();
  return { users: reviewerCandidates(s, repo, pr).map((u) => u.username).filter((n) => n.toLowerCase().includes(q)) };
}));

r.post('/repos/:owner/:repo/pulls/:n/reviewers', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const pr = getPull(s, repo, req.params.n);
  need((user && user.id === pr.authorId) || p.maintain);
  if (pr.state !== 'open') L.fail(422, 'Pull request is not open');
  const target = reviewerCandidates(s, repo, pr).find((u) => u.username === req.body?.username);
  if (!target) L.fail(422, 'Account cannot review this pull request');
  await store.mutate((d) => {
    const dp = d.pulls.find((x) => x.id === pr.id);
    if (!dp.reviewers.includes(target.id)) { dp.reviewers.push(target.id); addEvent(d, 'pr', pr.id, user.id, `requested a review from ${target.username}`); }
  });
  return { ok: true };
}));

r.delete('/repos/:owner/:repo/pulls/:n/reviewers/:username', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const pr = getPull(s, repo, req.params.n);
  need((user && user.id === pr.authorId) || p.maintain);
  const target = s.users.find((u) => u.username === req.params.username);
  if (!target) L.fail(404, 'Account not found');
  await store.mutate((d) => {
    const dp = d.pulls.find((x) => x.id === pr.id);
    dp.reviewers = dp.reviewers.filter((x) => x !== target.id);
    addEvent(d, 'pr', pr.id, user.id, `removed the review request for ${target.username}`);
  });
  return { ok: true };
}));

r.post('/repos/:owner/:repo/pulls/:n/review-comments', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const pr = getPull(s, repo, req.params.n);
  need(p.write && user && user.id !== pr.authorId && pr.state === 'open');
  const body = String(req.body?.body ?? '');
  if (!body.trim()) L.fail(422, 'Comment is required', { body: 'Comment is required' });
  const path = String(req.body?.path ?? '');
  const line = String(req.body?.line ?? '');
  if (!path || !line) L.fail(422, 'A changed line is required');
  await store.mutate((d) => {
    d.reviewComments.push({ id: store.nextId(d, 'rc'), prId: pr.id, userId: user.id, path, line, body, commitSha: repo.branches[pr.head], state: req.body?.mode === 'pending' ? 'pending' : 'published', time: now() });
  });
  return { ok: true };
}));

r.post('/repos/:owner/:repo/pulls/:n/reviews', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const pr = getPull(s, repo, req.params.n);
  need(p.write && user && user.id !== pr.authorId);
  if (pr.state !== 'open' || pr.draft) L.fail(422, 'This pull request cannot be reviewed');
  const decision = String(req.body?.decision ?? '');
  if (!['comment', 'approve', 'request_changes'].includes(decision)) L.fail(422, 'Select a review decision', { decision: 'Select a review decision' });
  const body = String(req.body?.body ?? '');
  if (decision === 'request_changes' && !body.trim()) L.fail(422, 'Summary is required to request changes', { body: 'Summary is required to request changes' });
  await store.mutate((d) => {
    d.reviews.push({ id: store.nextId(d, 'rv'), prId: pr.id, userId: user.id, decision, body, commitSha: repo.branches[pr.head], time: now() });
    for (const c of d.reviewComments) if (c.prId === pr.id && c.userId === user.id && c.state === 'pending') c.state = 'published';
    const label = { comment: 'reviewed', approve: 'approved these changes', request_changes: 'requested changes' }[decision];
    addEvent(d, 'pr', pr.id, user.id, label);
  });
  return { ok: true };
}));

r.put('/repos/:owner/:repo/pulls/:n/checks', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const pr = getPull(s, repo, req.params.n);
  need(p.admin);
  const status = String(req.body?.status ?? '');
  if (!['pending', 'success', 'failure'].includes(status)) L.fail(422, 'Invalid status');
  const sha = repo.branches[pr.head] || pr.headSha;
  await store.mutate((d) => {
    d.checks = d.checks.filter((c) => !(c.repoId === repo.id && c.sha === sha && c.name === 'test'));
    d.checks.push({ repoId: repo.id, sha, name: 'test', status, setBy: user.id, time: now() });
  });
  return { ok: true, s: !!s };
}));

r.post('/repos/:owner/:repo/pulls/:n/merge', h(async (req) => {
  const { s, user, repo, p } = ctx(req);
  const pr = getPull(s, repo, req.params.n);
  need(p.maintain);
  if (pr.state !== 'open') L.fail(422, 'Pull request is not open');
  const ms = mergeState(s, repo, pr);
  if (ms.reasons.length) L.fail(422, ms.reasons[0], { merge: ms.reasons.join('; ') });
  await store.mutate((d) => {
    const id = G.makeCommit(d, { parents: [ms.baseSha, ms.headSha], message: `Merge pull request #${pr.number} from ${pr.head}`, authorId: user.id, tree: ms.tree });
    const dr = d.repos.find((x) => x.id === repo.id);
    dr.branches[pr.base] = id;
    dr.updatedAt = now();
    const dp = d.pulls.find((x) => x.id === pr.id);
    Object.assign(dp, { state: 'merged', draft: false, mergedBy: user.id, mergedAt: now(), mergeSha: id, headSha: ms.headSha, baseSha: ms.baseSha, updatedAt: now() });
    addEvent(d, 'pr', pr.id, user.id, `merged commit ${id.slice(0, 7)} into ${pr.base}`);
  });
  return { ok: true };
}));

module.exports = r;

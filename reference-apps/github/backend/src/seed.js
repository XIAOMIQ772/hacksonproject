// Idempotent startup seed: runs once on an empty database (tracked by state.seedVersion).
const store = require('./store');
const L = require('./lib');
const G = require('./git');

const PASSWORD = 'Valid-password-123!';
const ago = (days, extraMin = 0) => new Date(Date.now() - days * 86400000 - extraMin * 60000).toISOString();

async function seed() {
  if (store.get().seedVersion) return;
  await store.mutate((d) => {
    const hash = L.hashPassword(PASSWORD);
    const user = (username, email) => {
      const u = { id: store.nextId(d, 'u'), username, email, emailVerified: true, passwordHash: hash, createdAt: ago(30) };
      d.users.push(u);
      return u;
    };
    const alice = user('alice-dev', 'alice.dev@example.test');
    const bob = user('bob-reviewer', 'bob.reviewer@example.test');
    const carol = user('carol-reader', 'carol.reader@example.test');
    const dave = user('dave-triage', 'dave.triage@example.test');
    const erin = user('erin-maintainer', 'erin.maintainer@example.test');
    const frank = user('frank-admin', 'frank.admin@example.test');
    user('grace-newcomer', 'grace.newcomer@example.test');
    const henry = user('henry-member', 'henry.member@example.test');

    const org = { id: store.nextId(d, 'o'), login: 'acme-demo', displayName: 'Acme Demo', createdAt: ago(30) };
    d.orgs.push(org);
    d.orgMembers.push({ orgId: org.id, userId: alice.id, role: 'owner' });
    for (const u of [bob, carol, dave, erin, frank, henry]) d.orgMembers.push({ orgId: org.id, userId: u.id, role: 'member' });

    const team = (name, parent, description = '') => {
      const t = { id: store.nextId(d, 't'), orgId: org.id, name, description, parentId: parent?.id || null, createdBy: alice.id, createdAt: ago(20) };
      d.teams.push(t);
      return t;
    };
    const engineering = team('engineering', null, 'All engineers');
    const frontend = team('frontend-team', engineering, 'Frontend engineers');
    team('design-system', frontend, 'Design system maintainers');
    team('backend-team', null, 'Backend engineers');
    const docsTeam = team('docs-team', null, 'Documentation writers');
    d.teamMembers.push({ teamId: frontend.id, userId: bob.id });

    const repo = (ownerType, owner, name, description, visibility, extra = {}) => {
      const r = { id: store.nextId(d, 'r'), ownerType, ownerId: owner.id, name, description, visibility, defaultBranch: 'main', createdBy: alice.id, createdAt: ago(10), updatedAt: ago(1), forkOf: null, branches: {}, protections: [], nextNumber: 1, ...extra };
      d.repos.push(r);
      return r;
    };
    const commit = (parents, message, author, tree, time) => G.makeCommit(d, { parents, message, authorId: author.id, tree, time });

    // ---- acme-demo/acme-docs ----
    const docs = repo('org', org, 'acme-docs', 'Documentation for the Acme Demo organization', 'public');
    const t1 = {
      'README.md': '# acme-docs\n\nWelcome to the Acme docs repository.\n',
      'docs/getting-started.md': 'Welcome to the Acme Demo documentation.\n',
      'src/search.ts': 'export function search(query: string) {\n  return query.trim();\n}\n',
    };
    const c1 = commit([], 'Initial commit', bob, t1, ago(3));
    const t2 = {
      ...t1,
      'README.md': '# acme-docs\n\nWelcome to the Acme docs repository.\n\nThis guide documents the search flow for Acme docs.\n',
      'src/search.ts': 'export function search(query: string) {\n  const normalized = query.trim();\n  return normalized.toLowerCase();\n}\n',
    };
    const c2 = commit([c1], 'Document search flow', alice, t2, ago(2));
    const c3 = commit([c2], 'Improve search ranking', alice, {
      ...t2,
      'src/search.ts': 'export function search(query: string) {\n  const normalized = query.trim();\n  const ranked = normalized.toLowerCase();\n  return ranked;\n}\n',
      'main-only.md': 'This file only exists on the feature-search branch.\n',
    }, ago(1, 60));
    const branchCommit = (msg, changes, author = alice) => commit([c2], msg, author, { ...t2, ...changes }, ago(1, 30));
    docs.branches = {
      main: c2,
      'feature-search': c3,
      release: c2,
      'draft-feature': branchCommit('Update onboarding draft', { 'docs/getting-started.md': 'Welcome to the Acme Demo documentation.\nStart with the onboarding checklist.\n' }),
      'fix-search': branchCommit('Fix search trimming', { 'src/search.ts': 'export function search(query: string) {\n  const normalized = query.trim();\n  return normalized.toLocaleLowerCase();\n}\n' }),
      'merge-ready': branchCommit('Add merge guide', { 'docs/merge.md': 'Merging requires one approval.\n' }),
      'merge-blocked': branchCommit('Add release notes', { 'docs/release-notes.md': 'Release notes draft.\n' }),
      'review-approve': branchCommit('Add review guide', { 'docs/review.md': 'Review every change.\n' }),
      'review-changes': branchCommit('Add style guide', { 'docs/style.md': 'Use short sentences.\n' }),
      'inline-comments': branchCommit('Add FAQ', { 'docs/faq.md': 'Frequently asked questions.\n' }),
      'close-reopen': branchCommit('Add glossary', { 'docs/glossary.md': 'Glossary of terms.\n' }),
    };
    docs.protections = [{ branch: 'release', requireApproval: true, requireCheck: true, by: alice.id, time: ago(5) }];

    const label = (r, name, color) => { const l = { id: store.nextId(d, 'l'), repoId: r.id, name, color }; d.labels.push(l); return l; };
    const bug = label(docs, 'bug', 'd73a4a');
    const documentation = label(docs, 'documentation', '0075ca');
    label(docs, 'enhancement', 'a2eeef');
    const milestone = (r, title) => { const m = { id: store.nextId(d, 'm'), repoId: r.id, title }; d.milestones.push(m); return m; };
    milestone(docs, 'Q3 launch');
    milestone(docs, 'v1.0');

    const event = (targetType, targetId, actor, text, time) => d.events.push({ id: store.nextId(d, 'e'), targetType, targetId, actorId: actor.id, text, createdAt: time });
    const comment = (targetType, targetId, author, body, time) => d.comments.push({ id: store.nextId(d, 'c'), targetType, targetId, authorId: author.id, body, createdAt: time });
    const issue = (r, title, body, author, state, extra = {}) => {
      const i = { id: store.nextId(d, 'i'), repoId: r.id, number: r.nextNumber++, title, body, authorId: author.id, state, createdAt: ago(4), updatedAt: ago(1), assignees: [], labels: [], milestoneId: null, ...extra };
      d.issues.push(i);
      event('issue', i.id, author, 'opened this issue', ago(4));
      if (state === 'closed') event('issue', i.id, author, 'Closed issue', ago(3));
      return i;
    };
    const onboarding = issue(docs, 'Improve onboarding', 'Describe the onboarding improvement.', alice, 'open', { labels: [documentation.id], assignees: [dave.id] });
    comment('issue', onboarding.id, bob, 'I can help with the onboarding guide.', ago(3, 30));
    issue(docs, 'Legacy welcome text', 'The welcome text is outdated.', alice, 'closed', { labels: [bug.id] });
    issue(docs, 'Original issue title', 'This issue is used to verify title validation.', alice, 'open');
    issue(docs, 'Fix broken search link', 'The search link on the docs home page is broken.', bob, 'open', { labels: [bug.id] });
    issue(docs, 'Protected issue', 'Only triage, maintain, and admin roles can close this issue.', alice, 'open');

    const pull = (title, head, base, author, extra = {}) => {
      const p = { id: store.nextId(d, 'p'), repoId: docs.id, number: docs.nextNumber++, title, body: extra.body || `${title}.`, authorId: author.id, state: 'open', draft: false, base, head, headSha: docs.branches[head], baseSha: docs.branches[base], createdAt: ago(2), updatedAt: ago(1), reviewers: [], milestoneId: null, ...extra };
      d.pulls.push(p);
      event('pr', p.id, author, p.draft ? 'opened this draft pull request' : 'opened this pull request', ago(2));
      return p;
    };
    const prOnboarding = pull('Improve onboarding', 'feature-search', 'main', alice, { body: 'This pull request improves onboarding and search ranking.' });
    comment('pr', prOnboarding.id, bob, 'Looks good so far, I will review the search changes.', ago(1, 50));
    const fixSearch = pull('Fix search', 'fix-search', 'main', alice, { state: 'closed', body: 'Fix search trimming.' });
    event('pr', fixSearch.id, alice, 'Closed pull request', ago(1, 40));
    pull('Draft onboarding update', 'draft-feature', 'main', alice, { draft: true, body: 'Draft update to the onboarding guide.' });
    const ready = pull('Ready to merge', 'merge-ready', 'main', alice, { body: 'Adds the merge guide.' });
    d.reviews.push({ id: store.nextId(d, 'rv'), prId: ready.id, userId: bob.id, decision: 'approve', body: 'Approved.', commitSha: docs.branches['merge-ready'], time: ago(1, 20) });
    event('pr', ready.id, bob, 'approved these changes', ago(1, 20));
    d.checks.push({ repoId: docs.id, sha: docs.branches['merge-ready'], name: 'test', status: 'success', setBy: alice.id, time: ago(1, 10) });
    pull('Blocked merge', 'merge-blocked', 'release', alice, { body: 'Release notes waiting for review.' });
    pull('Add review guide', 'review-approve', 'main', alice);
    pull('Add style guide', 'review-changes', 'main', alice);
    pull('Add FAQ', 'inline-comments', 'main', alice);
    pull('Add glossary', 'close-reopen', 'main', alice);

    d.grants.push({ repoId: docs.id, subjectType: 'user', subjectId: bob.id, role: 'write', grantorId: alice.id, time: ago(9) });
    d.grants.push({ repoId: docs.id, subjectType: 'user', subjectId: carol.id, role: 'read', grantorId: alice.id, time: ago(9) });
    d.grants.push({ repoId: docs.id, subjectType: 'user', subjectId: dave.id, role: 'triage', grantorId: alice.id, time: ago(9) });
    d.grants.push({ repoId: docs.id, subjectType: 'user', subjectId: erin.id, role: 'maintain', grantorId: alice.id, time: ago(9) });
    d.grants.push({ repoId: docs.id, subjectType: 'user', subjectId: frank.id, role: 'admin', grantorId: alice.id, time: ago(9) });
    d.grants.push({ repoId: docs.id, subjectType: 'team', subjectId: docsTeam.id, role: 'write', grantorId: alice.id, time: ago(9) });

    // ---- other repositories ----
    const secret = repo('org', org, 'secret-research', 'Private research notes', 'private');
    secret.branches.main = commit([], 'Initial commit', alice, { 'README.md': '# secret-research\n\nPrivate research notes.\n' }, ago(6));
    label(secret, 'bug', 'd73a4a');
    milestone(secret, 'Secret milestone');
    for (const u of [bob, carol, dave, erin, frank]) {
      const role = { [bob.id]: 'write', [carol.id]: 'read', [dave.id]: 'triage', [erin.id]: 'maintain', [frank.id]: 'admin' }[u.id];
      if (u !== bob) d.grants.push({ repoId: secret.id, subjectType: 'user', subjectId: u.id, role, grantorId: alice.id, time: ago(9) });
    }
    const vis = repo('org', org, 'visibility-demo', 'Content ready to be made public', 'private');
    vis.branches.main = commit([], 'Initial commit', alice, { 'README.md': '# visibility-demo\n\nContent ready to be made public.\n' }, ago(6));
    d.grants.push({ repoId: vis.id, subjectType: 'user', subjectId: bob.id, role: 'write', grantorId: alice.id, time: ago(9) });

    const fork = repo('user', alice, 'acme-docs-fork', docs.description, 'public', { forkOf: docs.id });
    fork.branches.main = c2;
    const bobRepo = repo('user', bob, 'bob-notes', 'Personal notes', 'public', { createdBy: bob.id });
    bobRepo.branches.main = commit([], 'Initial commit', bob, { 'README.md': '# bob-notes\n' }, ago(6));

    d.seedVersion = 1;
  });
}

module.exports = seed;

const crypto = require('crypto');
const store = require('./store');

const RANK = { read: 1, triage: 2, write: 3, maintain: 4, admin: 5 };
const ROLES = ['read', 'triage', 'write', 'maintain', 'admin'];

function hashPassword(pw) {
  const salt = crypto.randomBytes(8).toString('hex');
  return `${salt}:${crypto.scryptSync(pw, salt, 32).toString('hex')}`;
}
function checkPassword(pw, hash) {
  const [salt, h] = String(hash).split(':');
  return crypto.scryptSync(String(pw), salt, 32).toString('hex') === h;
}

const validUsername = (u) => typeof u === 'string' && u.length >= 1 && u.length <= 39 && /^[a-z0-9]+(-[a-z0-9]+)*$/.test(u);
function validEmail(e) {
  const v = String(e || '').trim();
  if (!v || v.length > 254) return false;
  const parts = v.split('@');
  if (parts.length !== 2 || !parts[0] || /\s/.test(v)) return false;
  const labels = parts[1].split('.');
  return labels.length >= 2 && labels.every((l) => l.length > 0);
}
const validPassword = (p) => typeof p === 'string' && p.length >= 12 && p.length <= 128 && /[A-Z]/.test(p) && /[a-z]/.test(p) && /[0-9]/.test(p) && /[^A-Za-z0-9]/.test(p) && !/\s/.test(p);

class HttpError extends Error {
  constructor(status, message, fields) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}
const fail = (status, message, fields) => { throw new HttpError(status, message, fields); };

function sessionToken(req) {
  return (/(?:^|;\s*)gh_session=([^;]+)/.exec(req.headers.cookie || '') || [])[1];
}

function currentUser(req) {
  const s = store.get();
  const tok = sessionToken(req);
  const sess = tok && s.sessions[tok];
  if (!sess || !sess.active) return null;
  return s.users.find((u) => u.id === sess.userId) || null;
}

function requireUser(req) {
  const u = currentUser(req);
  if (!u) fail(401, 'Sign in required');
  return u;
}

const userById = (s, id) => s.users.find((u) => u.id === id);
const userName = (s, id) => userById(s, id)?.username || 'ghost';

function ownerLogin(s, repo) {
  return repo.ownerType === 'org' ? s.orgs.find((o) => o.id === repo.ownerId)?.login : userById(s, repo.ownerId)?.username;
}

function findOwner(s, login) {
  const org = s.orgs.find((o) => o.login === login);
  if (org) return { type: 'org', id: org.id, org };
  const user = s.users.find((u) => u.username === login);
  if (user) return { type: 'user', id: user.id, user };
  return null;
}

function orgRole(s, user, orgId) {
  if (!user) return null;
  return s.orgMembers.find((m) => m.orgId === orgId && m.userId === user.id)?.role || null;
}

function explicitRole(s, user, repo) {
  if (!user) return null;
  if (repo.ownerType === 'user' && repo.ownerId === user.id) return 'admin';
  if (repo.ownerType === 'org' && orgRole(s, user, repo.ownerId) === 'owner') return 'admin';
  let best = null;
  const teamIds = new Set(s.teamMembers.filter((m) => m.userId === user.id).map((m) => m.teamId));
  for (const g of s.grants) {
    if (g.repoId !== repo.id) continue;
    if ((g.subjectType === 'user' && g.subjectId === user.id) || (g.subjectType === 'team' && teamIds.has(g.subjectId))) {
      if (!best || RANK[g.role] > RANK[best]) best = g.role;
    }
  }
  return best;
}

function repoRole(s, user, repo) {
  const r = explicitRole(s, user, repo);
  if (r) return r;
  return repo.visibility === 'public' ? 'read' : null;
}

function perms(s, user, repo) {
  const role = repoRole(s, user, repo);
  const is = (...roles) => !!user && roles.includes(role);
  return {
    role,
    signedIn: !!user,
    read: !!role,
    write: is('write', 'maintain', 'admin'),
    triage: is('triage', 'maintain', 'admin'),
    maintain: is('maintain', 'admin'),
    admin: is('admin'),
  };
}

function findRepo(s, owner, name) {
  const o = findOwner(s, owner);
  if (!o) return null;
  return s.repos.find((r) => r.ownerType === o.type && r.ownerId === o.id && r.name === name) || null;
}

function repoSummary(s, repo) {
  const owner = ownerLogin(s, repo);
  const fork = repo.forkOf && s.repos.find((r) => r.id === repo.forkOf);
  return {
    id: repo.id, owner, name: repo.name, fullName: `${owner}/${repo.name}`, description: repo.description,
    visibility: repo.visibility, updatedAt: repo.updatedAt, defaultBranch: repo.defaultBranch,
    forkOf: fork ? { owner: ownerLogin(s, fork), name: fork.name, fullName: `${ownerLogin(s, fork)}/${fork.name}` } : null,
  };
}

// Namespaces where the user may create repositories: personal plus organizations they own or belong to.
function creatableOwners(s, user) {
  const orgs = s.orgMembers.filter((m) => m.userId === user.id).map((m) => s.orgs.find((o) => o.id === m.orgId)).filter(Boolean);
  return [user.username, ...orgs.map((o) => o.login)];
}

module.exports = {
  RANK, ROLES, hashPassword, checkPassword, validUsername, validEmail, validPassword, HttpError, fail,
  sessionToken, currentUser, requireUser, userById, userName, ownerLogin, findOwner, orgRole, repoRole, explicitRole,
  perms, findRepo, repoSummary, creatableOwners,
};

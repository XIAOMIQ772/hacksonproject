const express = require('express');
const store = require('../store');
const L = require('../lib');
const { h } = require('./util');

const r = express.Router();
const validTeam = (n) => typeof n === 'string' && n.length >= 1 && n.length <= 50 && /^[a-z0-9]+(-+[a-z0-9]+)*$/.test(n);

function getOrg(s, login) {
  const org = s.orgs.find((o) => o.login === login);
  if (!org) L.fail(404, 'Organization not found');
  return org;
}
function requireOwner(s, user, org) {
  if (!user) L.fail(401, 'Sign in required');
  if (L.orgRole(s, user, org.id) !== 'owner') L.fail(403, 'Only organization owners can do this');
}
const teamName = (s, id) => s.teams.find((t) => t.id === id)?.name || null;

r.post('/orgs', h(async (req) => {
  const u = L.requireUser(req);
  const s = store.get();
  const login = String(req.body?.login ?? '').trim();
  const displayName = String(req.body?.displayName ?? '').trim();
  const fields = {};
  if (L.findOwner(s, login)) fields.login = 'Organization name already exists';
  else if (!L.validUsername(login)) fields.login = 'Organization name format is invalid';
  if (!displayName || displayName.length > 100) fields.displayName = 'Display name is required';
  if (Object.keys(fields).length) L.fail(422, 'Organization was not created', fields);
  await store.mutate((d) => {
    const id = store.nextId(d, 'o');
    d.orgs.push({ id, login, displayName, createdAt: new Date().toISOString() });
    d.orgMembers.push({ orgId: id, userId: u.id, role: 'owner' });
  });
  return { login };
}));

r.get('/owners/:login', h(async (req) => {
  const s = store.get();
  const u = L.currentUser(req);
  const o = L.findOwner(s, req.params.login);
  if (!o) L.fail(404, 'Not found');
  const repos = s.repos
    .filter((rp) => rp.ownerType === o.type && rp.ownerId === o.id && L.repoRole(s, u, rp))
    .sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1))
    .map((rp) => L.repoSummary(s, rp));
  if (o.type === 'org') {
    return { type: 'org', login: o.org.login, displayName: o.org.displayName, role: L.orgRole(s, u, o.id), repos };
  }
  return { type: 'user', login: o.user.username, repos };
}));

r.get('/orgs/:org/teams', h(async (req) => {
  const s = store.get();
  const org = getOrg(s, req.params.org);
  const u = L.currentUser(req);
  const teams = s.teams.filter((t) => t.orgId === org.id).map((t) => ({ name: t.name, description: t.description, parent: teamName(s, t.parentId), members: s.teamMembers.filter((m) => m.teamId === t.id).length }));
  return { org: { login: org.login, displayName: org.displayName }, teams, canManage: L.orgRole(s, u, org.id) === 'owner' };
}));

r.post('/orgs/:org/teams', h(async (req) => {
  const s = store.get();
  const org = getOrg(s, req.params.org);
  const u = L.currentUser(req);
  requireOwner(s, u, org);
  const name = String(req.body?.name ?? '').trim();
  const parentName = String(req.body?.parent ?? '');
  const fields = {};
  if (!name) fields.name = 'Team name is required';
  else if (!validTeam(name)) fields.name = 'Team name format is invalid';
  else if (s.teams.some((t) => t.orgId === org.id && t.name === name)) fields.name = 'Team name already exists';
  const parent = parentName ? s.teams.find((t) => t.orgId === org.id && t.name === parentName) : null;
  if (parentName && !parent) fields.parent = 'Parent team must belong to this organization';
  if (Object.keys(fields).length) L.fail(422, 'Team was not created', fields);
  await store.mutate((d) => {
    d.teams.push({ id: store.nextId(d, 't'), orgId: org.id, name, description: String(req.body?.description ?? ''), parentId: parent?.id || null, createdBy: u.id, createdAt: new Date().toISOString() });
  });
  return { name };
}));

function getTeam(s, org, name) {
  const t = s.teams.find((x) => x.orgId === org.id && x.name === name);
  if (!t) L.fail(404, 'Team not found');
  return t;
}

r.get('/orgs/:org/teams/:team', h(async (req) => {
  const s = store.get();
  const org = getOrg(s, req.params.org);
  const t = getTeam(s, org, req.params.team);
  const u = L.currentUser(req);
  return {
    org: { login: org.login, displayName: org.displayName },
    name: t.name, description: t.description, parent: teamName(s, t.parentId),
    children: s.teams.filter((x) => x.parentId === t.id).map((x) => x.name),
    members: s.teamMembers.filter((m) => m.teamId === t.id).map((m) => L.userName(s, m.userId)),
    allTeams: s.teams.filter((x) => x.orgId === org.id && x.id !== t.id).map((x) => x.name),
    canManage: L.orgRole(s, u, org.id) === 'owner',
  };
}));

r.post('/orgs/:org/teams/:team/members', h(async (req) => {
  const s = store.get();
  const org = getOrg(s, req.params.org);
  const t = getTeam(s, org, req.params.team);
  requireOwner(s, L.currentUser(req), org);
  const login = String(req.body?.username ?? '').trim();
  const target = s.users.find((x) => x.username === login || x.email.toLowerCase() === login.toLowerCase());
  if (!target) L.fail(422, 'Account not found', { username: 'Account not found' });
  if (!L.orgRole(s, target, org.id)) L.fail(422, 'Account is not an organization member', { username: 'Account is not an organization member' });
  if (s.teamMembers.some((m) => m.teamId === t.id && m.userId === target.id)) L.fail(422, 'Account is already a team member', { username: 'Account is already a team member' });
  await store.mutate((d) => { d.teamMembers.push({ teamId: t.id, userId: target.id }); });
  return { ok: true };
}));

r.delete('/orgs/:org/teams/:team/members/:username', h(async (req) => {
  const s = store.get();
  const org = getOrg(s, req.params.org);
  const t = getTeam(s, org, req.params.team);
  requireOwner(s, L.currentUser(req), org);
  const target = s.users.find((x) => x.username === req.params.username);
  if (!target) L.fail(404, 'Account not found');
  await store.mutate((d) => { d.teamMembers = d.teamMembers.filter((m) => !(m.teamId === t.id && m.userId === target.id)); });
  return { ok: true };
}));

r.put('/orgs/:org/teams/:team/parent', h(async (req) => {
  const s = store.get();
  const org = getOrg(s, req.params.org);
  const t = getTeam(s, org, req.params.team);
  requireOwner(s, L.currentUser(req), org);
  const parentName = String(req.body?.parent ?? '');
  let parentId = null;
  if (parentName) {
    const p = s.teams.find((x) => x.orgId === org.id && x.name === parentName);
    if (!p) L.fail(422, 'Parent team must belong to this organization', { parent: 'Parent team must belong to this organization' });
    for (let cur = p; cur; cur = s.teams.find((x) => x.id === cur.parentId)) {
      if (cur.id === t.id) L.fail(422, 'Cyclic team hierarchy is not allowed', { parent: 'Cyclic team hierarchy is not allowed' });
    }
    parentId = p.id;
  }
  await store.mutate((d) => { d.teams.find((x) => x.id === t.id).parentId = parentId; });
  return { ok: true };
}));

r.get('/orgs/:org/people', h(async (req) => {
  const s = store.get();
  const org = getOrg(s, req.params.org);
  const u = L.currentUser(req);
  const members = s.orgMembers.filter((m) => m.orgId === org.id).map((m) => ({ username: L.userName(s, m.userId), role: m.role === 'owner' ? 'Owner' : 'Member' }));
  return { org: { login: org.login, displayName: org.displayName }, members, canManage: L.orgRole(s, u, org.id) === 'owner', me: u?.username || null };
}));

r.post('/orgs/:org/people', h(async (req) => {
  const s = store.get();
  const org = getOrg(s, req.params.org);
  requireOwner(s, L.currentUser(req), org);
  const login = String(req.body?.login ?? '').trim();
  const role = String(req.body?.role ?? 'Member').toLowerCase();
  if (!['member', 'owner'].includes(role)) L.fail(422, 'Role is not supported', { role: 'Role is not supported' });
  const target = s.users.find((x) => x.username === login || x.email.toLowerCase() === login.toLowerCase());
  if (!target) L.fail(422, 'Account not found', { login: 'Account not found' });
  if (L.orgRole(s, target, org.id)) L.fail(422, 'Account is already a member', { login: 'Account is already a member' });
  await store.mutate((d) => { d.orgMembers.push({ orgId: org.id, userId: target.id, role }); });
  return { ok: true };
}));

r.delete('/orgs/:org/people/:username', h(async (req) => {
  const s = store.get();
  const org = getOrg(s, req.params.org);
  requireOwner(s, L.currentUser(req), org);
  const target = s.users.find((x) => x.username === req.params.username);
  const m = target && s.orgMembers.find((x) => x.orgId === org.id && x.userId === target.id);
  if (!m) L.fail(404, 'Member not found');
  if (m.role === 'owner' && s.orgMembers.filter((x) => x.orgId === org.id && x.role === 'owner').length === 1) L.fail(422, 'The last owner cannot be removed');
  await store.mutate((d) => {
    const teamIds = new Set(d.teams.filter((t) => t.orgId === org.id).map((t) => t.id));
    const repoIds = new Set(d.repos.filter((rp) => rp.ownerType === 'org' && rp.ownerId === org.id).map((rp) => rp.id));
    d.orgMembers = d.orgMembers.filter((x) => !(x.orgId === org.id && x.userId === target.id));
    d.teamMembers = d.teamMembers.filter((x) => !(teamIds.has(x.teamId) && x.userId === target.id));
    d.grants = d.grants.filter((g) => !(repoIds.has(g.repoId) && g.subjectType === 'user' && g.subjectId === target.id));
  });
  return { ok: true };
}));

module.exports = r;

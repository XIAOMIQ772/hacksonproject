const crypto = require('crypto');
const express = require('express');
const store = require('../store');
const L = require('../lib');
const { h } = require('./util');

const r = express.Router();
const PW_RULE = 'Password requirements are not satisfied';
const MISMATCH = 'Password confirmation does not match';

r.get('/session', h(async (req) => {
  const s = store.get();
  const u = L.currentUser(req);
  if (!u) return { user: null, orgs: [] };
  const orgs = s.orgMembers.filter((m) => m.userId === u.id).map((m) => s.orgs.find((o) => o.id === m.orgId)).filter(Boolean);
  return { user: { username: u.username, email: u.email }, orgs: orgs.map((o) => ({ login: o.login, displayName: o.displayName })) };
}));

r.post('/signup', h(async (req) => {
  const b = req.body || {};
  const username = String(b.username ?? '').trim();
  const email = String(b.email ?? '').trim();
  const password = String(b.password ?? '');
  const s = store.get();
  const fields = {};
  if (!L.validUsername(username)) fields.username = 'Username format is invalid';
  else if (L.findOwner(s, username)) fields.username = 'Username already exists';
  if (!L.validEmail(email)) fields.email = 'Email format is invalid';
  else if (s.users.some((u) => u.email.toLowerCase() === email.toLowerCase())) fields.email = 'Email already exists';
  if (!L.validPassword(password)) fields.password = PW_RULE;
  if (String(b.confirm ?? '') !== password) fields.confirm = MISMATCH;
  if (!b.agree) fields.agree = 'Agree to terms is required';
  if (Object.keys(fields).length) L.fail(422, 'Account could not be created', fields);
  await store.mutate((d) => {
    d.users.push({ id: store.nextId(d, 'u'), username, email, emailVerified: true, passwordHash: L.hashPassword(password), createdAt: new Date().toISOString() });
  });
  return { ok: true };
}));

r.post('/login', h(async (req, res) => {
  const b = req.body || {};
  const login = String(b.login ?? '').trim();
  const s = store.get();
  const u = s.users.find((x) => x.username === login || x.email.toLowerCase() === login.toLowerCase());
  if (!u || !L.checkPassword(b.password ?? '', u.passwordHash)) L.fail(401, 'Invalid credentials');
  const token = crypto.randomBytes(24).toString('hex');
  await store.mutate((d) => { d.sessions[token] = { userId: u.id, active: true, createdAt: new Date().toISOString() }; });
  res.setHeader('Set-Cookie', `gh_session=${token}; Path=/; HttpOnly; SameSite=Lax`);
  return { ok: true, username: u.username };
}));

r.post('/logout', h(async (req, res) => {
  const tok = L.sessionToken(req);
  if (tok && store.get().sessions[tok]) await store.mutate((d) => { d.sessions[tok].active = false; });
  res.setHeader('Set-Cookie', 'gh_session=; Path=/; Max-Age=0');
  return { ok: true };
}));

r.post('/password-reset', h(async (req) => {
  const b = req.body || {};
  const email = String(b.email ?? '').trim();
  const s = store.get();
  const u = s.users.find((x) => x.email.toLowerCase() === email.toLowerCase());
  const fields = {};
  if (!u) fields.email = 'No account is associated with this email';
  if (String(b.code ?? '') !== '123456') fields.code = 'Verification code is invalid';
  if (!L.validPassword(String(b.password ?? ''))) fields.password = PW_RULE;
  if (String(b.confirm ?? '') !== String(b.password ?? '')) fields.confirm = MISMATCH;
  if (Object.keys(fields).length) L.fail(422, 'Password was not reset', fields);
  await store.mutate((d) => {
    const du = d.users.find((x) => x.id === u.id);
    du.passwordHash = L.hashPassword(String(b.password));
    for (const sess of Object.values(d.sessions)) if (sess.userId === u.id) sess.active = false;
  });
  return { message: 'Password updated' };
}));

r.post('/settings/password', h(async (req) => {
  const u = L.requireUser(req);
  const b = req.body || {};
  const current = String(b.current ?? '');
  const password = String(b.password ?? '');
  const fields = {};
  if (!current) fields.current = 'Current password is required';
  else if (!L.checkPassword(current, u.passwordHash)) fields.current = 'Current password is incorrect';
  if (!password) fields.password = 'New password is required';
  else if (!L.validPassword(password)) fields.password = PW_RULE;
  if (!String(b.confirm ?? '')) fields.confirm = 'Confirm password is required';
  else if (String(b.confirm) !== password) fields.confirm = MISMATCH;
  if (Object.keys(fields).length) L.fail(422, 'Password was not updated', fields);
  const tok = L.sessionToken(req);
  await store.mutate((d) => {
    d.users.find((x) => x.id === u.id).passwordHash = L.hashPassword(password);
    for (const [k, sess] of Object.entries(d.sessions)) if (sess.userId === u.id && k !== tok) sess.active = false;
  });
  return { message: 'Password updated' };
}));

module.exports = r;

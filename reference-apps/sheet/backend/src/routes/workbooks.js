const express = require('express');
const db = require('../database/db_runtime');
const { seedWorkspace, newId, blankWorkbookData } = require('../database/seed_db');

const router = express.Router();
const COOKIE = 'sheet_ws';

// Each browser session gets its own workspace seeded with the evaluation data, so
// every fresh session starts from the same seed and sessions never interfere.
function readCookie(req) {
  const header = req.headers.cookie || '';
  for (const part of header.split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === COOKIE) return decodeURIComponent(v.join('='));
  }
  return null;
}

function setCookie(res, wsId) {
  res.setHeader(
    'Set-Cookie',
    `${COOKIE}=${encodeURIComponent(wsId)}; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly`,
  );
}

async function resolveWorkspace(req, res) {
  const current = readCookie(req);
  if (current) {
    const row = await db.get('SELECT id FROM workspaces WHERE id = ?', [current]);
    if (row) return current;
  }
  const wsId = newId();
  await seedWorkspace(db, wsId);
  setCookie(res, wsId);
  return wsId;
}

function toSummary(row) {
  return { id: row.id, name: row.name, updatedAt: row.updated_at };
}

function toFull(row) {
  return { ...toSummary(row), rev: row.rev, data: JSON.parse(row.data) };
}

function validData(data) {
  return data && Array.isArray(data.sheets) && data.sheets.length > 0 && typeof data.activeSheetId === 'string';
}

const wrap = (fn) => (req, res) => fn(req, res).catch((err) => {
  console.error(err);
  res.status(500).json({ error: 'Server error' });
});

router.get('/workbooks', wrap(async (req, res) => {
  const wsId = await resolveWorkspace(req, res);
  const rows = await db.all(
    'SELECT id, name, updated_at FROM workbooks WHERE workspace_id = ? ORDER BY updated_at DESC, created_at DESC',
    [wsId],
  );
  res.json(rows.map(toSummary));
}));

router.post('/workbooks', wrap(async (req, res) => {
  const wsId = await resolveWorkspace(req, res);
  const name = String(req.body?.name ?? '').trim();
  if (!name) {
    res.status(400).json({ error: 'Workbook name cannot be empty' });
    return;
  }
  const data = req.body?.data ?? blankWorkbookData();
  if (!validData(data)) {
    res.status(400).json({ error: 'Invalid workbook data' });
    return;
  }
  const now = new Date().toISOString();
  const id = newId();
  await db.run(
    'INSERT INTO workbooks (id, workspace_id, name, updated_at, created_at, rev, data) VALUES (?, ?, ?, ?, ?, 0, ?)',
    [id, wsId, name, now, now, JSON.stringify(data)],
  );
  const row = await db.get('SELECT * FROM workbooks WHERE id = ?', [id]);
  res.status(201).json(toFull(row));
}));

router.get('/workbooks/:id', wrap(async (req, res) => {
  const row = await db.get('SELECT * FROM workbooks WHERE id = ?', [req.params.id]);
  if (!row) {
    res.status(404).json({ error: 'Workbook not found' });
    return;
  }
  // Opening a workbook URL binds this browser session to the workbook's workspace.
  if (readCookie(req) !== row.workspace_id) setCookie(res, row.workspace_id);
  res.json(toFull(row));
}));

router.put('/workbooks/:id', wrap(async (req, res) => {
  const row = await db.get('SELECT * FROM workbooks WHERE id = ?', [req.params.id]);
  if (!row) {
    res.status(404).json({ error: 'Workbook not found' });
    return;
  }
  const body = req.body || {};
  const name = String(body.name ?? row.name).trim();
  if (!name) {
    res.status(400).json({ error: 'Workbook name cannot be empty' });
    return;
  }
  if (body.data !== undefined && !validData(body.data)) {
    res.status(400).json({ error: 'Invalid workbook data' });
    return;
  }
  const rev = Number(body.rev) || 0;
  if (rev && rev <= row.rev) {
    // A newer save already landed; keep it.
    res.json(toFull(row));
    return;
  }
  const updatedAt = typeof body.updatedAt === 'string' && body.updatedAt ? body.updatedAt : row.updated_at;
  const data = body.data !== undefined ? JSON.stringify(body.data) : row.data;
  await db.run('UPDATE workbooks SET name = ?, updated_at = ?, rev = ?, data = ? WHERE id = ?', [
    name, updatedAt, rev || row.rev, data, row.id,
  ]);
  const next = await db.get('SELECT * FROM workbooks WHERE id = ?', [row.id]);
  res.json(toFull(next));
}));

module.exports = router;

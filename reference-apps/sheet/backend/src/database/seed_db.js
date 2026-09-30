const crypto = require('crypto');
const { closeDb } = require('./init_db');
const runtime = require('./db_runtime');

function newId() {
  return crypto.randomBytes(9).toString('base64url');
}

function blankSheet(name, id = newId()) {
  return {
    id,
    name,
    cells: {},
    sel: { ar: 0, ac: 0, r1: 0, c1: 0, r2: 0, c2: 0 },
    rules: [],
    filter: null,
    pivot: null,
  };
}

function blankWorkbookData() {
  const sheet = blankSheet('Sheet1');
  return { activeSheetId: sheet.id, sheets: [sheet] };
}

// Evaluation seed: workbook "Q3 Sales" with Sheet1 (A1 = Region, sales table rows
// East/1200/Open, North/800/Closed, South/700/Open) and an empty Sheet2.
function q3SalesData() {
  const rows = [
    ['Region', 'Sales', 'Status'],
    ['East', '1200', 'Open'],
    ['North', '800', 'Closed'],
    ['South', '700', 'Open'],
  ];
  const sheet1 = blankSheet('Sheet1');
  rows.forEach((row, r) => row.forEach((v, c) => { sheet1.cells[`${r},${c}`] = v; }));
  const sheet2 = blankSheet('Sheet2');
  return { activeSheetId: sheet1.id, sheets: [sheet1, sheet2] };
}

async function seedWorkspace(tx, workspaceId) {
  const now = new Date().toISOString();
  // seeded record looks older than anything the user changes afterwards
  const seededAt = new Date(Math.floor(Date.now() / 60000) * 60000 - 86400000).toISOString();
  await tx.run('INSERT OR IGNORE INTO workspaces (id, created_at) VALUES (?, ?)', [workspaceId, now]);
  const existing = await tx.get('SELECT COUNT(*) AS n FROM workbooks WHERE workspace_id = ?', [workspaceId]);
  if (existing.n > 0) return;
  await tx.run(
    'INSERT INTO workbooks (id, workspace_id, name, updated_at, created_at, rev, data) VALUES (?, ?, ?, ?, ?, 0, ?)',
    [newId(), workspaceId, 'Q3 Sales', seededAt, seededAt, JSON.stringify(q3SalesData())],
  );
}

async function seedDatabase(workspaceId = 'default') {
  return seedWorkspace(runtime, workspaceId);
}

if (require.main === module) {
  seedDatabase()
    .then(() => closeDb())
    .catch((error) => {
      console.error('Database seed failed:', error);
      process.exitCode = 1;
    });
}

module.exports = seedDatabase;
module.exports.seedDatabase = seedDatabase;
module.exports.seed = seedDatabase;
module.exports.seedWorkspace = seedWorkspace;
module.exports.newId = newId;
module.exports.blankWorkbookData = blankWorkbookData;

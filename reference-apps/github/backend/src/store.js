// In-memory application state persisted as one JSON document in SQLite.
// Each write runs on a clone and is committed (and flushed to disk) only when
// the whole handler succeeds, so every operation is atomic.
const crypto = require('crypto');
const { initializeDatabase, getDb } = require('./database/init_db');
const openDb = async () => { await initializeDatabase(); return getDb(); };

let state = null;
let writeChain = Promise.resolve();

function emptyState() {
  return {
    seq: 1, users: [], sessions: {}, orgs: [], orgMembers: [], teams: [], teamMembers: [],
    repos: [], commits: {}, grants: [], issues: [], labels: [], milestones: [], comments: [],
    events: [], reactions: [], pulls: [], reviews: [], reviewComments: [], checks: [],
  };
}

function exec(db, sql, params = []) {
  return new Promise((resolve, reject) => db.run(sql, params, (err) => (err ? reject(err) : resolve())));
}

async function load() {
  const db = await openDb();
  await exec(db, 'CREATE TABLE IF NOT EXISTS app_state (id TEXT PRIMARY KEY, data TEXT NOT NULL)');
  const row = await new Promise((resolve, reject) =>
    db.get("SELECT data FROM app_state WHERE id = 'state'", (err, r) => (err ? reject(err) : resolve(r))));
  state = row ? { ...emptyState(), ...JSON.parse(row.data) } : emptyState();
  return state;
}

function persist() {
  const data = JSON.stringify(state);
  writeChain = writeChain.then(async () => {
    const db = await openDb();
    await exec(db, "INSERT INTO app_state (id, data) VALUES ('state', ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data", [data]);
  });
  return writeChain;
}

function get() {
  return state;
}

// Runs fn on a copy of the state; commits and persists only if fn returns normally.
async function mutate(fn) {
  const draft = structuredClone(state);
  const result = fn(draft);
  state = draft;
  await persist();
  return result;
}

function nextId(s, prefix) {
  s.seq += 1;
  return `${prefix}${s.seq}`;
}

function sha(content) {
  return crypto.createHash('sha1').update(content).digest('hex');
}

module.exports = { load, get, mutate, nextId, sha, persist };

const fs = require('fs');
const path = require('path');
const sqlite3 = require('sqlite3').verbose();

const DEFAULT_DB_FILENAME = 'database.db';

let db = null;
let initPromise = null;
let generation = 0; // bumped by closeDb(); lets waiters detect a closed/switched connection
let maintenance = null; // pending file removal; new connections wait for it
let currentDbPath = resolveDbPath(
  process.env.ARC_DB_FILE || process.env.DATABASE_FILE || DEFAULT_DB_FILENAME,
);

function resolveDbPath(inputPath = DEFAULT_DB_FILENAME) {
  const candidate = String(inputPath || DEFAULT_DB_FILENAME).trim() || DEFAULT_DB_FILENAME;
  return path.resolve(process.cwd(), candidate);
}

function ensureDbDirectory(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function getDbPath() {
  return currentDbPath;
}

async function setDbPath(nextPath) {
  const resolvedPath = resolveDbPath(nextPath);
  if (resolvedPath === currentDbPath) {
    return currentDbPath;
  }

  await closeDb();
  currentDbPath = resolvedPath;
  return currentDbPath;
}

// Raw connection (schema may not be applied yet). Prefer `await initializeDatabase()`.
function getDb() {
  if (!db) {
    ensureDbDirectory(currentDbPath);
    db = new sqlite3.Database(currentDbPath);
    db.configure('busyTimeout', 5000);
  }
  return db;
}

function runStatement(database, sql, params = []) {
  return new Promise((resolve, reject) => {
    database.run(sql, params, (err) => (err ? reject(err) : resolve()));
  });
}

function execSql(database, sql) {
  return new Promise((resolve, reject) => {
    database.exec(sql, (err) => (err ? reject(err) : resolve()));
  });
}

function allRows(database, sql, params = []) {
  return new Promise((resolve, reject) => {
    database.all(sql, params, (err, rows) => (err ? reject(err) : resolve(rows || [])));
  });
}

// Adds a column to an existing table only when it is missing (idempotent migration).
async function ensureColumn(database, table, column, definition) {
  const columns = await allRows(database, `PRAGMA table_info(${table})`);
  if (!columns.some((info) => info.name === column)) {
    await runStatement(database, `ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
  }
}

/**
 * Schema. Runs once per process before the first query, on every start.
 * - Idempotent DDL only: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
 * - New columns on existing tables: ensureColumn(database, table, column, definition).
 * - Never drop tables or delete rows here.
 */
async function applySchema(database) {
  await execSql(database, `
    -- CREATE TABLE IF NOT EXISTS ... ;
  `);
}

async function initializeDatabase(options = {}) {
  if (options.dbPath) {
    await setDbPath(options.dbPath);
  }
  if (options.reset) {
    await resetDatabaseFile();
  }
  while (maintenance) {
    await maintenance;
  }

  if (!initPromise) {
    const database = getDb();
    const pending = (async () => {
      await runStatement(database, 'PRAGMA foreign_keys = ON;');
      await applySchema(database);
      return database;
    })();
    initPromise = pending;
    // A failed init may be retried by the next caller.
    pending.catch(() => {
      if (initPromise === pending) {
        initPromise = null;
      }
    });
  }

  // Concurrent callers share the same promise and all receive the Database.
  const pending = initPromise;
  const startGeneration = generation;
  try {
    const database = await pending;
    if (generation === startGeneration && database === db) {
      return database;
    }
  } catch (error) {
    if (generation === startGeneration) {
      throw error;
    }
  }
  // The connection was closed or switched while waiting: initialise the current one.
  return initializeDatabase();
}

function closeDb() {
  generation += 1;
  initPromise = null;
  if (!db) {
    return Promise.resolve();
  }

  const currentDb = db;
  db = null;
  return new Promise((resolve, reject) => {
    currentDb.close((err) => (err ? reject(err) : resolve()));
  });
}

// Closes the connection (when it is the current file) and deletes the file plus its
// journal files. New connections wait until the removal has finished.
function removeDatabaseFile(targetPath = currentDbPath) {
  const resolvedPath = resolveDbPath(targetPath);
  const previous = maintenance;
  const task = (async () => {
    if (previous) {
      await previous;
    }
    if (resolvedPath === currentDbPath) {
      await closeDb();
    }
    for (const suffix of ['', '-journal', '-wal', '-shm']) {
      fs.rmSync(`${resolvedPath}${suffix}`, { force: true });
    }
  })();
  const tracked = task.then(() => undefined, () => undefined).then(() => {
    if (maintenance === tracked) {
      maintenance = null;
    }
  });
  maintenance = tracked;
  return task;
}

async function resetDatabaseFile(targetPath = currentDbPath) {
  await removeDatabaseFile(targetPath);
}

module.exports = {
  DEFAULT_DB_FILENAME,
  resolveDbPath,
  getDbPath,
  setDbPath,
  getDb,
  initializeDatabase,
  closeDb,
  removeDatabaseFile,
  resetDatabaseFile,
};

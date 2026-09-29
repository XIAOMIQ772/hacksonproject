const { closeDb } = require('./init_db');
const { withTransaction } = require('./db_runtime');

/**
 * Seed. Runs on every server start (after the schema), so it MUST be idempotent.
 * - Insert every pre-existing record described in the requirements, with the exact
 *   names/values. Parents before children.
 * - Use INSERT OR IGNORE on a UNIQUE/PRIMARY key, or check before inserting:
 *     const row = await get('SELECT id FROM <table> WHERE <unique col> = ?', [value]);
 *     if (!row) await run('INSERT INTO <table> (...) VALUES (...)', [...]);
 * - Never delete, reset or overwrite data here (tests share one database).
 */
async function seedDatabase() {
  return withTransaction(async ({ run, get, all, exec }) => {
    void run;
    void get;
    void all;
    void exec;
  });
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

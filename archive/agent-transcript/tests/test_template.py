import subprocess
import tempfile
import unittest
from pathlib import Path

import support


class TemplateTests(unittest.TestCase):
    def test_repeated_and_concurrent_initialization_return_the_database(self):
        source = Path(__file__).resolve().parents[1] / 'template/backend/src/database/init_db.js'
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const moduleStub = {exports: {}};
class Database {
  run(sql, cb) { setImmediate(() => cb(null)); }
  close(cb) { cb(null); }
}
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  module: moduleStub, process,
  require: name => name === 'sqlite3' ? {verbose: () => ({Database})} : require(name)
});
(async () => {
  const api = moduleStub.exports;
  const results = await Promise.all([api.initializeDatabase(), api.initializeDatabase()]);
  assert.equal(results[0], api.getDb());
  assert.equal(results[1], results[0]);
  assert.equal(await api.initializeDatabase(), results[0]);
  await api.closeDb();
  assert.notEqual(await api.initializeDatabase(), results[0]);
  await api.closeDb();
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['node', '-e', script, str(source)], cwd=tmp,
                                    text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

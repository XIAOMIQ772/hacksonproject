#!/usr/bin/env python3
"""Score a generated app with an external Playwright suite (e.g. the reference app's tests).

    python3 tools/local_eval.py APP_DIR TESTS_DIR [--workers 4]

The suite is copied into APP_DIR/backend/.eval-e2e and run against a fresh-database backend.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
import checks  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("app")
parser.add_argument("tests")
parser.add_argument("--workers", type=int, default=4)
args = parser.parse_args()
app, backend = Path(args.app).resolve(), Path(args.app).resolve() / "backend"
suite = backend / ".eval-e2e"
shutil.rmtree(suite, ignore_errors=True)
shutil.copytree(args.tests, suite)
(backend / "eval.config.cjs").write_text(
    "module.exports = { testDir: './.eval-e2e', testMatch: /.*\\.spec\\.(js|ts)$/, timeout: 15000,\n"
    "  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL } };\n")
problem = checks.build(app)
if problem:
    sys.exit(problem)
server = checks.Server(app)
try:
    problem = server.wait()
    if problem:
        sys.exit(problem)
    passed, total, failures = checks.e2e(app, server.url, config="eval.config.cjs", workers=args.workers)
finally:
    server.stop()
print(failures)
print(f"SCORE {passed}/{total}")

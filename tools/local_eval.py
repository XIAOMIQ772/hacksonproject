#!/usr/bin/env python3
"""Score a generated app with an external Playwright suite (e.g. the reference app's tests).

    python3 tools/local_eval.py APP_DIR TESTS_DIR [--workers 4] [--isolate]

The suite is copied into APP_DIR/backend/.eval-e2e and run against a fresh-database backend. With
--isolate every test gets its own backend and database, so tests that change seeded records do not
affect each other (each test then sees the app exactly as a fresh deployment).
"""
import argparse
import concurrent.futures as futures
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
import checks  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("app")
parser.add_argument("tests")
parser.add_argument("--workers", type=int, default=4)
parser.add_argument("--isolate", action="store_true", help="a fresh backend and database per test")
args = parser.parse_args()
app, backend = Path(args.app).resolve(), Path(args.app).resolve() / "backend"
suite = backend / ".eval-e2e"
shutil.rmtree(suite, ignore_errors=True)
shutil.copytree(args.tests, suite)
(backend / "eval.config.cjs").write_text(
    "module.exports = { testDir: './.eval-e2e', testMatch: /.*\\.spec\\.(js|ts)$/, timeout: 15000,\n"
    "  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL } };\n")
try:  # the suite never stays in the app, where a resumed agent could read it
    problem = checks.build(app)
    if problem:
        sys.exit(problem)
    if args.isolate:
        listing = backend / ".eval-list.json"  # a file: shell output is clipped
        checks.shell(f"npx playwright test --config=eval.config.cjs --list --reporter=json > {listing.name}",
                     backend, 120, env={"CI": "1"})
        data = json.loads(listing.read_text())
        listing.unlink()
        cases = []

        def walk(group: dict) -> None:
            for spec in group.get("specs", []):
                cases.append(f"{Path(spec['file']).name}:{spec['line']}")
            for child in group.get("suites", []):
                walk(child)
        for group in data.get("suites", []):
            walk(group)

        def one(case: str) -> tuple[int, int, str]:
            server = checks.Server(app)
            try:
                problem = server.wait()
                return (0, 1, f"- {case} :: server did not start\n  {problem}") if problem else \
                    checks.e2e(app, server.url, pattern=case, config="eval.config.cjs", workers=1)
            finally:
                server.stop()
        with futures.ThreadPoolExecutor(args.workers) as pool:
            results = list(pool.map(one, dict.fromkeys(cases)))
        passed, total = sum(r[0] for r in results), sum(r[1] for r in results)
        failures = "\n".join(r[2] for r in results if r[2])
    else:
        server = checks.Server(app)
        try:
            problem = server.wait()
            if problem:
                sys.exit(problem)
            passed, total, failures = checks.e2e(app, server.url, config="eval.config.cjs", workers=args.workers)
        finally:
            server.stop()
finally:
    shutil.rmtree(suite, ignore_errors=True)
    (backend / "eval.config.cjs").unlink(missing_ok=True)
print(failures)
print(f"SCORE {passed}/{total}")

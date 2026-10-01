"""Deterministic verification of the generated app: install, build, cold start, static rules, e2e tests."""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import shlex
import tempfile
import time
import urllib.request
from pathlib import Path

from tools import clip, kill_group, shell

# Browser dialogs are dismissed automatically by the test browser (rule 13).
STATIC_RULES = [
    (re.compile(r"\b(?:window\.)?(?:alert|confirm|prompt)\s*\("), "alert/confirm/prompt: use an in-page dialog"),
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def install(root: Path) -> str:
    """npm install where node_modules is missing or older than package.json (shared symlinks are left alone)."""
    out = []
    for part in ("backend", "frontend"):
        pkg, modules = root / part / "package.json", root / part / "node_modules"
        if modules.is_symlink():  # a worktree sharing the integration branch's dependencies
            continue
        if modules.is_dir() and modules.stat().st_mtime >= pkg.stat().st_mtime:
            continue
        result = shell("npm install --no-audit --no-fund --loglevel=error", root / part, 600)
        if result.rstrip().endswith("[exit 0]"):
            modules.touch()
        else:
            out.append(f"npm install failed in {part}:\n{result}")
    return "\n".join(out)


def build(root: Path) -> str:
    """Empty string when the frontend builds, otherwise the relevant error output."""
    problem = install(root)
    if problem:
        return problem
    result = shell("npm run build", root / "frontend", 300)
    return "" if result.rstrip().endswith("[exit 0]") else f"frontend build failed:\n{result}"


class Server:
    """Backend started as in production (`npm start`), on a fresh database."""

    def __init__(self, root: Path):
        self.root, self.port = root, free_port()
        self.dir = tempfile.mkdtemp(prefix="arc-db-")
        self.log = Path(self.dir) / "server.log"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "VISUAL_"))}
        env.update(PORT=str(self.port), ARC_DB_FILE=f"{self.dir}/app.db", DATABASE_FILE=f"{self.dir}/app.db")
        self.proc = subprocess.Popen(["npm", "start"], cwd=root / "backend", env=env, start_new_session=True,
                                     stdout=self.log.open("w"), stderr=subprocess.STDOUT)
        self.url = f"http://127.0.0.1:{self.port}"

    def wait(self, seconds: int = 40) -> str:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return f"backend exited with code {self.proc.returncode}:\n{self.output()}"
            try:
                with urllib.request.urlopen(self.url + "/", timeout=3) as r:
                    if r.status < 500:
                        return ""
            except Exception:
                time.sleep(0.5)
        return f"backend did not answer on / within {seconds}s:\n{self.output()}"

    def output(self) -> str:
        return clip(self.log.read_text(errors="replace"), 4000) if self.log.exists() else ""

    def stop(self) -> None:
        kill_group(self.proc.pid)


def static(root: Path, allow: str = "") -> list[str]:
    """Violations of the component rules; a line containing 'required by REQ-' is an explicit exception."""
    found = []
    for path in sorted((root / "frontend" / "src").rglob("*.[jt]s*")):
        for no, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if "required by REQ-" in line:
                continue
            for pattern, why in STATIC_RULES:
                if pattern.search(line):
                    found.append(f"{path.relative_to(root)}:{no}: {why}")
    return found


# Against a local server a correct action finishes in milliseconds, so a stuck locator fails after 3 s instead
# of using up the whole 15 s test timeout (twice, with the retry). Applied on top of the project's own config.
FAST_OVERRIDE = """const base = require('./{base}');
const config = base.default || base;
module.exports = {{ ...config, expect: {{ ...(config.expect || {{}}), timeout: 3000 }},
  use: {{ ...(config.use || {{}}), actionTimeout: 3000, navigationTimeout: 5000, trace: 'off' }} }};
"""


def e2e(root: Path, url: str, pattern: str = "", config: str = "", workers: int = 4) -> tuple[int, int, str]:
    """Run Playwright tests (backend/test-e2e unless `config` names another config); returns (passed, total, failures)."""
    tests = root / "backend" / "test-e2e"
    if not config and (not tests.is_dir() or not any(tests.glob("*.spec.*"))):
        return 0, 0, "no e2e tests in backend/test-e2e"
    report = Path(tempfile.mkdtemp(prefix="arc-pw-")) / "report.json"
    base = config or "playwright.config.js"
    fast = root / "backend" / f".check-{report.parent.name}.config.cjs"  # unique: runs may overlap
    if (root / "backend" / base).is_file():
        fast.write_text(FAST_OVERRIDE.format(base=base))
        cfg = f" --config={fast.name}"
    else:
        cfg = f" --config={config}" if config else ""
    cmd = (f"npx playwright test {pattern}{cfg} --reporter=json --workers={workers} --timeout=15000 --retries=1"
           f" > {report} 2>/dev/null")
    try:
        shell(cmd, root / "backend", 900, env={"PLAYWRIGHT_BASE_URL": url, "ARC_WEB_BASE_URL": url, "E2E_BASE_URL": url,
                                              "BASE_URL": url, "CI": "1"})
    finally:
        fast.unlink(missing_ok=True)
    try:
        data = json.loads(report.read_text())
    except (ValueError, OSError):
        return 0, 0, "playwright produced no report (syntax error in a spec?):\n" + \
            shell(f"npx playwright test {pattern} --list", root / "backend", 120, env={"CI": "1"})
    passed, total, failures, flaky = 0, 0, [], []

    def walk(suite: dict) -> None:
        nonlocal passed, total
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                total += 1
                results = test.get("results") or [{}]
                if test.get("status") == "expected":
                    passed += 1
                elif test.get("status") == "flaky":  # failed once, passed on the retry
                    passed += 1
                    flaky.append(f"{spec.get('file')} :: {spec.get('title')}")
                else:
                    # errors[] also holds the pending action ("waiting for getByLabel(...)") behind a timeout
                    messages = [e.get("message", "") for e in results[-1].get("errors") or []]
                    messages = messages or [(results[-1].get("error") or {}).get("message", "")]
                    error = re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(dict.fromkeys(messages)))
                    failures.append(f"- {spec.get('file')} :: {spec.get('title')}\n  {clip(error, 700)}")
        for child in suite.get("suites", []):
            walk(child)

    for suite in data.get("suites", []):
        walk(suite)
    for error in data.get("errors", []):
        failures.append(f"- load error: {clip(re.sub(chr(27) + r'\[[0-9;]*m', '', error.get('message', '')), 700)}")
    if flaky:
        failures.append("FLAKY (passed on retry; tests probably share state with parallel tests):\n"
                        + "\n".join(f"- {name}" for name in flaky))
    return passed, total, "\n".join(failures)


RERUN_MAX_FAILURES = 10  # a rerun stops early when failures are real, not load


def failure_names(failures: str) -> list[str]:
    """Names ("file :: title") of the tests that failed in `e2e` output; flaky ones passed and are excluded."""
    return re.findall(r"^- (.+ :: .+)$", failures.split("FLAKY (", 1)[0], re.M)


def confirm(root: Path, url: str, failures: str) -> tuple[str, int]:
    """Rerun the failed tests of a whole-suite run one at a time. Returns the failures that remain and the
    number of tests that passed on the rerun."""
    names = failure_names(failures)
    if not names:
        return failures, 0
    grep = "|".join(re.escape(name.split(" :: ", 1)[1]) for name in names)
    _, total, again = e2e(root, url, f"--grep {shlex.quote(grep)} --max-failures={RERUN_MAX_FAILURES}", workers=1)
    if not total:
        return failures, 0
    still = set(failure_names(again))
    recovered = [name for name in names if name not in still]
    if not recovered:
        return failures, 0
    head, _, tail = failures.partition("FLAKY (")
    kept = [entry for entry in re.split(r"\n(?=- )", head.strip())
            if not any(entry.startswith(f"- {name}\n") or entry == f"- {name}" for name in recovered)]
    sections = [*kept, *([f"FLAKY ({tail}"] if tail else []),
                "FLAKY (failed in the whole-suite run, passed when rerun one at a time):\n"
                + "\n".join(f"- {name}" for name in recovered)]
    return "\n".join(section for section in sections if section), len(recovered)


def failed_tests(report: str) -> set[str]:
    """Names ("file :: title") listed in a check report's FAILED TESTS section."""
    section = report.split("FAILED TESTS:\n", 1)[1].split("\nE2E FAILURES:", 1)[0] if "FAILED TESTS:\n" in report else ""
    return {line[2:] for line in section.splitlines() if line.startswith("- ")}


def spec_filter(pattern: str) -> str:
    """Playwright file filters for a check pattern, one quoted argument per alternative: 'a.spec|b.spec' (or
    space separated) runs both files. Unquoted, the shell read the | as a pipe and no test ran."""
    return " ".join(shlex.quote(part) for part in re.split(r"[|\s]+", pattern) if part)


def check(root: Path, pattern: str = "") -> tuple[bool, str]:
    """Full verification used by the `check` tool and the final gate."""
    pattern = spec_filter(pattern)
    problem = build(root)
    if problem:
        return False, problem
    server = Server(root)
    try:
        problem = server.wait()
        if problem:
            return False, problem
        if pattern:
            passed, total, failures = e2e(root, server.url, pattern)
        else:
            passed, total, failures = e2e(root, server.url)
            failures, recovered = confirm(root, server.url, failures)
            passed += recovered
        browser = list(dict.fromkeys(re.findall(r"^\[browser error\] (.+)$", server.output(), re.M)))
    finally:
        server.stop()
    violations = static(root)
    lines = [f"build ok; fresh-database start ok; e2e {passed}/{total} passed"]
    if failures:
        names = failure_names(failures)
        if names:  # complete list; the details below may be clipped
            lines.append("FAILED TESTS:\n" + "\n".join(f"- {name}" for name in names[:300]))
        lines.append("E2E FAILURES:\n" + clip(failures, 9000))
    if browser:
        lines.append("BROWSER ERRORS (uncaught in the page during the tests; page, then message):\n"
                     + "\n".join(f"- {line}" for line in browser[:10]))
    if violations:
        lines.append("RULE VIOLATIONS (rule 13):\n" + "\n".join(violations[:30]))
    ok = total > 0 and passed == total and not violations
    return ok, "\n".join(lines)

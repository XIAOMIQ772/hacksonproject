"""Deterministic verification of the generated app: install, build, cold start, static rules, e2e tests."""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from tools import clip, shell

# Browser-native popups cannot be driven like page content (standard §3.3).
STATIC_RULES = [
    (re.compile(r"<select\b"), "native <select>: use the shared ARIA Combobox component"),
    (re.compile(r"\b(?:window\.)?(?:alert|confirm|prompt)\s*\("), "alert/confirm/prompt: use an in-page dialog"),
    (re.compile(r'type=["\'](?:date|color|datetime-local)["\']'), "native date/color input: use a text input"),
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def install(root: Path) -> str:
    """npm install where node_modules is missing or older than package.json."""
    out = []
    for part in ("backend", "frontend"):
        pkg, modules = root / part / "package.json", root / part / "node_modules"
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
    """Backend started like the evaluator does, on a fresh database."""

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
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


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


def e2e(root: Path, url: str, pattern: str = "", config: str = "", workers: int = 4) -> tuple[int, int, str]:
    """Run Playwright tests (backend/test-e2e unless `config` names another config); returns (passed, total, failures)."""
    tests = root / "backend" / "test-e2e"
    if not config and (not tests.is_dir() or not any(tests.glob("*.spec.*"))):
        return 0, 0, "no e2e tests in backend/test-e2e"
    report = Path(tempfile.mkdtemp(prefix="arc-pw-")) / "report.json"
    cfg = f" --config={config}" if config else ""
    cmd = (f"npx playwright test {pattern}{cfg} --reporter=json --workers={workers} --timeout=15000 --retries=0"
           f" > {report} 2>/dev/null")
    shell(cmd, root / "backend", 900, env={"PLAYWRIGHT_BASE_URL": url, "CI": "1"})
    try:
        data = json.loads(report.read_text())
    except ValueError:
        return 0, 0, "playwright produced no report (syntax error in a spec?):\n" + \
            shell(f"npx playwright test {pattern} --list", root / "backend", 120, env={"CI": "1"})
    passed, total, failures = 0, 0, []

    def walk(suite: dict) -> None:
        nonlocal passed, total
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                total += 1
                results = test.get("results") or [{}]
                if test.get("status") == "expected":
                    passed += 1
                else:
                    error = (results[-1].get("error") or {}).get("message", "")
                    error = re.sub(r"\x1b\[[0-9;]*m", "", error)
                    failures.append(f"- {spec.get('file')} :: {spec.get('title')}\n  {clip(error, 700)}")
        for child in suite.get("suites", []):
            walk(child)

    for suite in data.get("suites", []):
        walk(suite)
    for error in data.get("errors", []):
        failures.append(f"- load error: {clip(re.sub(chr(27) + r'\[[0-9;]*m', '', error.get('message', '')), 700)}")
    return passed, total, "\n".join(failures)


def check(root: Path, pattern: str = "") -> tuple[bool, str]:
    """Full verification used by the `check` tool and the final gate."""
    problem = build(root)
    if problem:
        return False, problem
    server = Server(root)
    try:
        problem = server.wait()
        if problem:
            return False, problem
        passed, total, failures = e2e(root, server.url, pattern)
    finally:
        server.stop()
    violations = static(root)
    lines = [f"build ok; fresh-database start ok; e2e {passed}/{total} passed"]
    if failures:
        lines.append("E2E FAILURES:\n" + clip(failures, 9000))
    if violations:
        lines.append("RULE VIOLATIONS (standard §3.3):\n" + "\n".join(violations[:30]))
    ok = total > 0 and passed == total and not violations
    return ok, "\n".join(lines)

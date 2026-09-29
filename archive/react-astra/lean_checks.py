"""Cheap delivery checks: npm bootstrap, build + double cold start + browser render smoke +
UI-string lint, cleanup.

Everything here is defensive: process groups are always killed, deadlines are honoured
and ``run_check`` never raises (internal errors become a failed check).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

__all__ = [
    "CheckResult", "NpmBootstrap", "run_check", "cleanup_output", "free_port",
    "child_env", "spawn", "kill_group", "run_logged", "read_log", "extract_build_errors",
    "find_missing_strings", "npm_hard_error",
]

FEEDBACK_LIMIT = 4000
BUILD_ERRORS_LIMIT = 2500
SERVER_LOG_LIMIT = 2000
HEALTH_WAIT_SECONDS = 25.0
DEEP_LINK = "/__arc_check/deep/link"
LINT_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".html", ".css", ".json"}
MISSING_CAP = 25
RENDER_TIMEOUT = 25.0       # hard cap for the headless-browser render smoke
RENDER_MIN_SECONDS = 8.0    # skip the smoke when less than this is left for it
RENDER_RESERVE = 10.0       # check time kept free for the second start

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_FILE_POS = re.compile(r"[\w@./\\-]+\.[A-Za-z0-9]+[:(]\d+[:,]\s?\d+")
_ERROR_WORD = re.compile(r"error|Error|ERROR|✘")
_NPM_NOISE = re.compile(r"^\s*npm (error|ERR!)")
# npm failures that a plain `npm install` on the grader repeats; network errors are not listed.
_NPM_HARD = re.compile(r"\b(?:ERESOLVE|ETARGET|E404|EJSONPARSE|ENOVERSIONS)\b|No matching version|notarget",
                       re.IGNORECASE)
_NPM_BORING = re.compile(r"A complete log of this run|For a full report see|eresolve-report"
                         r"|^\s*npm (error|ERR!)\s*$")
_NODE_MODULES_FRAME = re.compile(r"^\s+at .*node_modules")
# One opener for every local request: never route 127.0.0.1 through an env proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# --------------------------------------------------------------------------- processes

def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Inherited environment tuned for non-interactive npm/node runs."""
    env = dict(os.environ)
    env.pop("NO_COLOR", None)  # node warns when NO_COLOR and FORCE_COLOR are both set
    env.update({
        "CI": "1",
        "FORCE_COLOR": "0",
        "npm_config_fund": "false",
        "npm_config_audit": "false",
        "npm_config_update_notifier": "false",
    })
    if extra:
        env.update(extra)
    return env


def spawn(command: list[str], cwd: Path, log_path: Path,
          env: dict[str, str] | None = None) -> subprocess.Popen:
    """Start ``command`` in its own session with stdout+stderr going to ``log_path``.

    Output goes to a file, never a pipe, so a background grandchild that keeps the
    descriptor open can never make the caller hang.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as stream:
        return subprocess.Popen(command, cwd=str(cwd), env=env if env is not None else child_env(),
                                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                start_new_session=True)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Some hosts answer EPERM for a group that only holds exiting/zombie members.
        return False
    except OSError:
        return False


def kill_group(process: subprocess.Popen | None, grace: float = 2.0) -> None:
    """SIGTERM the whole process group, wait up to ``grace``, then SIGKILL. Never raises."""
    if process is None:
        return
    pgid = process.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        # Group already gone; just reap the leader if needed.
        try:
            process.wait(timeout=0.5)
        except Exception:
            pass
        return
    except OSError:
        pass
    end = time.monotonic() + max(0.0, grace)
    while True:
        try:
            process.poll()  # reap the leader so it does not keep the group alive as a zombie
        except Exception:
            pass
        if not _group_alive(pgid):
            break
        if time.monotonic() >= end:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
            break
        time.sleep(0.05)
    try:
        process.wait(timeout=1)
    except Exception:
        pass


def run_logged(command: list[str], cwd: Path, log_path: Path, *, timeout: float,
               env: dict[str, str] | None = None, exit_grace: float = 0.5,
               timeout_grace: float = 2.0) -> tuple[int, bool]:
    """Run ``command`` to completion (or timeout), then kill its whole process group.

    Returns ``(returncode, timed_out)``; returncode 124 on timeout, 127 if it could
    not be started (the error is written to the log).
    """
    try:
        process = spawn(command, cwd, log_path, env)
    except OSError as error:
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(log_path).write_text(f"failed to start {command[0]}: {error}\n", encoding="utf-8")
        except OSError:
            pass
        return 127, False
    timed_out = False
    try:
        try:
            code = process.wait(timeout=max(0.01, timeout))
        except subprocess.TimeoutExpired:
            timed_out = True
            code = 124
    finally:
        kill_group(process, grace=timeout_grace if timed_out else exit_grace)
    return code, timed_out


def read_log(path: Path, max_bytes: int = 400_000) -> str:
    """Read a command log (head+tail when huge), strip ANSI codes and CR progress lines."""
    try:
        path = Path(path)
        size = path.stat().st_size
        with open(path, "rb") as stream:
            if size <= max_bytes:
                data = stream.read()
            else:
                half = max_bytes // 2
                head = stream.read(half)
                stream.seek(size - half)
                data = head + f"\n...[{size - 2 * half} bytes omitted]...\n".encode() + stream.read()
    except OSError:
        return ""
    text = _ANSI.sub("", data.decode("utf-8", errors="replace")).replace("\r\n", "\n")
    if "\r" in text:
        lines = []
        for line in text.split("\n"):
            parts = [part for part in line.split("\r") if part]
            lines.append(parts[-1] if parts else "")
        text = "\n".join(lines)
    return text


def _tail_lines(text: str, lines: int, limit: int) -> str:
    tail = "\n".join(text.rstrip().splitlines()[-lines:])
    if len(tail) > limit:
        tail = "..." + tail[-(limit - 3):]
    return tail


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------------- npm bootstrap

def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def npm_hard_error(text: str) -> bool:
    """True when failed npm output names an error a fresh plain `npm install` repeats."""
    return bool(_NPM_HARD.search(text or ""))


class NpmBootstrap:
    """Background ``npm install`` for frontend/ and backend/, plus a synchronous ensure()."""

    SUBDIRS = ("frontend", "backend")

    def __init__(self, root: Path, log_dir: Path, npm: str = "npm"):
        self.root = Path(root)
        self.log_dir = Path(log_dir)
        self.npm = npm
        self._procs: dict[str, subprocess.Popen] = {}
        self._proc_hash: dict[str, str] = {}
        self._finished: set[str] = set()
        self._ok_hash: dict[str, str] = {}
        self._bg_failed: dict[str, str] = {}
        self._failed: dict[str, tuple[str, str]] = {}
        self._runs = 0
        self.hard_error = ""  # deterministic part of the last ensure() result

    # -- helpers
    def _command(self) -> list[str]:
        return [self.npm, "install", "--no-audit", "--no-fund", "--loglevel=error"]

    def _log(self, sub: str) -> Path:
        return self.log_dir / f"npm-install-{sub}.log"

    def _mark_ok(self, sub: str, digest: str) -> None:
        self._ok_hash[sub] = digest
        self._failed.pop(sub, None)
        marker = self.root / sub / "node_modules" / ".package-lock.json"
        try:
            if marker.is_file():
                os.utime(marker)  # later mtime comparisons see this install as current
        except OSError:
            pass

    def _summary(self, sub: str, code: int, log: Path, text: str | None = None) -> str:
        text = read_log(log) if text is None else text
        # npm prints the error code first; keep its error lines rather than a blind tail.
        lines = [line for line in text.splitlines() if _NPM_NOISE.match(line) and not _NPM_BORING.search(line)]
        if len(lines) > 15:
            lines = lines[:10] + ["..."] + lines[-5:]
        body = _clip_head("\n".join(lines), 900) if lines else _tail_lines(text, 15, 900)
        return f"{sub}: npm install failed (exit {code}); log {log}\n{body}".rstrip()

    def _failure_key(self, folder: Path) -> str:
        return _sha(folder / "package.json") + _sha(folder / ".npmrc")

    def _collect(self, sub: str) -> None:
        process = self._procs.get(sub)
        if process is None or sub in self._finished or process.poll() is None:
            return
        self._finished.add(sub)
        kill_group(process, grace=0.2)
        digest = self._proc_hash.get(sub, "")
        if process.returncode == 0:
            self._mark_ok(sub, digest)
            self._bg_failed.pop(sub, None)
        else:
            self._bg_failed[sub] = self._summary(sub, process.returncode, self._log(sub))

    def _needs_install(self, sub: str) -> bool:
        folder = self.root / sub
        package = folder / "package.json"
        if not package.is_file():
            return False
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True  # let npm report the broken package.json
        if not isinstance(data, dict):
            return True
        if not (data.get("dependencies") or data.get("devDependencies")
                or data.get("optionalDependencies")):
            return False
        marker = folder / "node_modules" / ".package-lock.json"
        if not marker.is_file():
            return True
        # A recorded hash is authoritative: a lazily collected background install utimes the
        # marker after package.json may already have changed, so mtimes would hide the edit.
        known = self._ok_hash.get(sub)
        if known is not None:
            return known != _sha(package)
        try:
            return package.stat().st_mtime > marker.stat().st_mtime
        except OSError:
            return True

    # -- public API
    def start(self) -> None:
        """Start background installs in frontend/ and backend/ (own sessions). Never raises."""
        for sub in self.SUBDIRS:
            folder = self.root / sub
            if not (folder / "package.json").is_file():
                continue
            running = self._procs.get(sub)
            if running is not None and running.poll() is None:
                continue
            try:
                self._proc_hash[sub] = _sha(folder / "package.json")
                self._procs[sub] = spawn(self._command(), folder, self._log(sub), child_env())
                self._finished.discard(sub)
            except OSError as error:
                self._bg_failed[sub] = f"{sub}: could not start npm install: {error}"

    def wait(self, timeout: float) -> dict[str, int | None]:
        """Wait (bounded) for background installs; returns returncodes (None = running)."""
        end = time.monotonic() + max(0.0, timeout or 0.0)
        result: dict[str, int | None] = {}
        for sub, process in self._procs.items():
            try:
                process.wait(timeout=max(0.0, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            self._collect(sub)
            result[sub] = process.poll()
        return result

    def ensure(self, timeout: float = 300) -> str:
        """Synchronously (re)install where needed; returns "" or an error summary.

        Only deterministic failures (see ``npm_hard_error``) are cached per package.json and
        copied to ``self.hard_error``; transient ones (network, timeout) are retried next time.
        """
        end = time.monotonic() + max(0.0, timeout)
        self.hard_error = ""
        try:
            self.wait(max(0.0, end - time.monotonic()))
        except Exception:
            pass
        errors: list[str] = []
        hard: list[str] = []
        for sub in self.SUBDIRS:
            folder = self.root / sub
            if not (folder / "package.json").is_file():
                continue
            process = self._procs.get(sub)
            if process is not None and process.poll() is None:
                errors.append(f"{sub}: npm install still running after {timeout:.0f}s")
                continue
            retry_failed_background = self._bg_failed.pop(sub, None) is not None
            if not (retry_failed_background or self._needs_install(sub)):
                continue
            digest = _sha(folder / "package.json")
            key = self._failure_key(folder)
            previous = self._failed.get(sub)
            if previous and previous[0] == key:
                errors.append(previous[1])  # unchanged package.json/.npmrc: do not retry forever
                hard.append(previous[1])
                continue
            left = end - time.monotonic()
            if left <= 1:
                errors.append(f"{sub}: npm install needed but no time left")
                continue
            self._runs += 1
            log = self.log_dir / f"npm-install-{sub}-{self._runs}.log"
            code, timed_out = run_logged(self._command(), folder, log, timeout=left, env=child_env())
            if code == 0:
                self._mark_ok(sub, digest)
                continue
            text = "" if timed_out else read_log(log)
            summary = (f"{sub}: npm install timed out after {left:.0f}s" if timed_out
                       else self._summary(sub, code, log, text))
            if npm_hard_error(text):
                self._failed[sub] = (key, summary)
                hard.append(summary)
            errors.append(summary)
        self.hard_error = "\n".join(hard)
        return "\n".join(errors)

    def stop(self) -> None:
        """Kill any background install still running (extra helper, never raises)."""
        for process in self._procs.values():
            if process.poll() is None:
                kill_group(process, grace=1.0)


# --------------------------------------------------------------------------- check

@dataclass
class CheckResult:
    ok: bool
    build_ok: bool
    start_ok: bool
    missing_strings: list[str] = field(default_factory=list)
    feedback: str = ""
    seconds: float = 0.0
    # First cold start healthy with no problems (pages, SPA fallback, browser render smoke).
    first_start_ok: bool = False
    # False when npm install failed deterministically (the grader's fresh install would too).
    npm_ok: bool = True


def extract_build_errors(text: str, root: Path | None = None, limit: int = BUILD_ERRORS_LIMIT) -> str:
    """Keep error-ish lines (error/Error/ERROR/✘/file:line:col) with a little context."""
    text = _ANSI.sub("", text or "")
    if root is not None:
        for prefix in {str(Path(root)), str(Path(root).resolve())}:
            text = text.replace(prefix + os.sep, "")
    lines = [line for line in text.splitlines() if not _NODE_MODULES_FRAME.match(line)]

    def matches(skip_npm_noise: bool) -> list[int]:
        found = []
        for index, line in enumerate(lines):
            if skip_npm_noise and _NPM_NOISE.match(line):
                continue
            if _ERROR_WORD.search(line) or _FILE_POS.search(line):
                found.append(index)
        return found

    hits = matches(True)
    drop_npm_noise = bool(hits)
    hits = hits or matches(False)
    if not hits:
        return _tail_lines(text, 30, limit)
    keep: set[int] = set()
    for index in hits:
        keep.update(range(max(0, index - 1), min(len(lines), index + 4)))
    out: list[str] = []
    previous = -2
    for index in sorted(keep):
        if drop_npm_noise and _NPM_NOISE.match(lines[index]):
            continue
        if previous >= 0 and index != previous + 1:
            out.append("...")
        out.append(lines[index])
        previous = index
    result = "\n".join(out).strip()
    if len(result) > limit:
        result = result[: limit - 16].rstrip() + "\n...(truncated)"
    return result


def _variants(text: str) -> list[str]:
    """Literal spellings of a UI string that JSX/JS source may legitimately contain."""
    out = [text]

    def add(value: str) -> None:
        if value not in out:
            out.append(value)

    if "'" in text:
        for rep in ("’", "&apos;", "&#39;", "&rsquo;", "\\'", "{\"'\"}"):
            add(text.replace("'", rep))
    if "’" in text:
        for rep in ("'", "&rsquo;", "&#8217;", "\\u2019"):
            add(text.replace("’", rep))
    if '"' in text:
        for rep in ("&quot;", '\\"', "&#34;"):
            add(text.replace('"', rep))
        curly, opened = [], False
        for char in text:
            if char == '"':
                curly.append("”" if opened else "“")
                opened = not opened
            else:
                curly.append(char)
        add("".join(curly))
    if "“" in text or "”" in text:
        add(text.replace("“", '"').replace("”", '"'))
        add(text.replace("“", "&ldquo;").replace("”", "&rdquo;"))
    if "‘" in text:
        add(text.replace("‘", "'").replace("’", "'"))
    if "&" in text:
        add(text.replace("&", "&amp;"))
    if "…" in text:
        add(text.replace("…", "..."))
        add(text.replace("…", "&hellip;"))
    if "..." in text:
        add(text.replace("...", "…"))
    if "\u00a0" in text:
        add(text.replace("\u00a0", " "))
    return out


def _source_corpus(frontend: Path) -> str:
    chunks: list[str] = []
    candidates: list[Path] = []
    src = frontend / "src"
    if src.is_dir():
        for directory, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in {"node_modules", "dist"}]
            candidates.extend(Path(directory) / name for name in files)
    if (frontend / "index.html").is_file():
        candidates.append(frontend / "index.html")
    for path in sorted(candidates):
        if path.suffix.lower() not in LINT_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def find_missing_strings(frontend: Path, strings: list[str]) -> list[str]:
    """UI strings not found verbatim (or as an entity/quote/whitespace variant) in frontend/src."""
    corpus = _source_corpus(Path(frontend))
    normalised = " ".join(corpus.split())
    missing: list[str] = []
    seen: set[str] = set()
    for raw in strings or []:
        text = str(raw)
        if not text.strip() or text in seen:
            continue
        seen.add(text)
        found = False
        for variant in _variants(text):
            if variant in corpus or (" ".join(variant.split()) in normalised):
                found = True
                break
        if not found:
            missing.append(text)
    return missing


def _http_get(url: str, timeout: float) -> tuple[int | None, str, str, str]:
    request = urllib.request.Request(url, headers={
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "User-Agent": "arc-lean-check",
    })
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read(400_000).decode("utf-8", errors="replace")
            return response.status, response.headers.get("Content-Type", "") or "", body, ""
    except urllib.error.HTTPError as error:
        try:
            body = error.read(20_000).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        content_type = error.headers.get("Content-Type", "") if error.headers else ""
        return error.code, content_type or "", body, ""
    except Exception as error:  # connection refused, timeout, reset ...
        reason = getattr(error, "reason", None)
        return None, "", "", f"{type(error).__name__}: {reason or error}"


def _snippet(body: str, limit: int = 160) -> str:
    return " ".join(body.split())[:limit]


# --------------------------------------------------------------------------- render smoke

# Loads "/" in headless chromium (playwright from backend/node_modules) and prints JSON lines:
# {"unavailable": why} | {"launched": true} then {"rendered", "errors" (pageerror only), "gotoError"}.
_RENDER_SCRIPT = r"""
const url = process.argv[1];
const started = Date.now();
const emit = (data) => process.stdout.write(
  JSON.stringify(Object.assign({ ms: Date.now() - started }, data)) + '\n');
const first = (error) => String((error && error.message) || error).split('\n')[0].slice(0, 300);
const painted = () => {
  const root = document.querySelector('#root');
  return !!root && (root.childElementCount > 0 || root.textContent.trim() !== '');
};
(async () => {
  let pw = null;
  for (const name of ['playwright', '@playwright/test']) {
    try { pw = require(name); break; } catch (error) { /* try the next package */ }
  }
  if (!pw || !pw.chromium) return emit({ unavailable: 'playwright is not installed in backend/node_modules' });
  let browser = null;
  let page = null;
  let launchError = '';
  for (const options of [{}, { channel: 'chromium' }]) {  // headless shell, then full chromium
    try {
      browser = await pw.chromium.launch(Object.assign({ headless: true, timeout: 10000 }, options));
      page = await browser.newPage();
      break;
    } catch (error) {
      launchError = launchError || first(error);
      if (browser) await browser.close().catch(() => {});
      browser = null;
    }
  }
  if (!page) return emit({ unavailable: 'chromium launch failed: ' + launchError });
  emit({ launched: true });
  const errors = [];
  let gotoError = '';
  page.on('pageerror', (error) => errors.push(first(error)));
  try { await page.goto(url, { waitUntil: 'load', timeout: 8000 }); } catch (error) { gotoError = first(error); }
  const wait = (ms) => page.waitForFunction(painted, null, { timeout: ms }).then(() => true, () => false);
  let rendered = await wait(3000);
  if (rendered) {  // data loaded after the first paint may still crash and unmount the app
    await page.waitForLoadState('networkidle', { timeout: 1500 }).catch(() => {});
    rendered = await wait(1500);
  }
  emit({ rendered, errors: errors.slice(0, 5), gotoError });
  await browser.close().catch(() => {});
})().catch((error) => emit({ unavailable: 'render smoke crashed: ' + first(error) }))
  .finally(() => process.exit(0));
"""
# backend dir -> advisory why the render smoke cannot run there (never retried).
_RENDER_UNAVAILABLE: dict[str, str] = {}


def _parse_render_output(text: str) -> dict:
    """Merge the JSON object lines printed by the render script (later keys win)."""
    data: dict = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            data.update(value)
    return data


def _render_verdict(data: dict, timed_out: bool, seconds: float) -> tuple[str, str, bool]:
    """(start problem, advisory, smoke unavailable) for the parsed render-script output."""
    if data.get("rendered") is True:
        return "", "", False
    if data.get("rendered") is False:
        errors = [str(item) for item in data.get("errors") or [] if str(item).strip()]
        detail = errors[0] if errors else "no error captured"
        if len(errors) > 1:
            detail += f" (+{len(errors) - 1} more page errors)"
        if not errors and data.get("gotoError"):
            detail += f"; page load: {data['gotoError']}"
        return ("GET / renders an empty #root in a real browser (white screen): " + detail
                + " -- an uncaught exception while rendering unmounts the whole React tree; guard values "
                  "that may be undefined (window globals, API data before it loads)", "", False)
    if data.get("unavailable"):
        return "", f"ADVISORY: render smoke skipped: {data['unavailable']}", True
    if data.get("launched"):  # the browser works; the page itself never settled
        return "", (f"ADVISORY: render smoke inconclusive: GET / did not finish rendering in a real "
                    f"browser within {seconds:.0f}s"), False
    reason = f"timed out after {seconds:.0f}s" if timed_out else "the render script printed no result"
    return "", f"ADVISORY: render smoke skipped: {reason}", True


def _render_smoke(backend: Path, url: str, log_path: Path, timeout: float) -> tuple[str, str]:
    """Open ``url`` in headless chromium; returns (start problem, advisory). Never raises."""
    key = str(Path(backend).resolve())
    if key in _RENDER_UNAVAILABLE:
        return "", ""  # reported once already; do not pay the launch cost again
    node = shutil.which("node") or "node"
    # Private TMPDIR: a failed launch leaves playwright profile dirs behind; remove them all.
    temp_dir = tempfile.mkdtemp(prefix="arc-render-")
    try:
        code, timed_out = run_logged([node, "-e", _RENDER_SCRIPT, url], backend, log_path, timeout=timeout,
                                     env=child_env({"TMPDIR": temp_dir}), exit_grace=1.0)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    data = _parse_render_output(read_log(log_path))
    if code == 127 and not data:
        data = {"unavailable": f"could not start node (see {log_path})"}
    problem, advisory, unavailable = _render_verdict(data, timed_out, timeout)
    if unavailable:
        _RENDER_UNAVAILABLE[key] = advisory
    return problem, advisory


@dataclass
class _Round:
    healthy: bool = False
    problems: list[str] = field(default_factory=list)
    log_tail: str = ""
    advisory: list[str] = field(default_factory=list)


def _server_round(backend: Path, db_file: Path, log_path: Path, *, check_pages: bool,
                  seconds: float, render_left: Callable[[], float] | None = None) -> _Round:
    """One cold start; with ``render_left`` (seconds left callable) also the browser render smoke."""
    outcome = _Round()
    port = free_port()
    env = child_env({"PORT": str(port), "ARC_DB_FILE": str(db_file)})
    node = shutil.which("node") or "node"
    try:
        process = spawn([node, "src/index.js"], backend, log_path, env)
    except OSError as error:
        outcome.problems.append(f"could not start node: {error}")
        return outcome
    base = f"http://127.0.0.1:{port}"
    try:
        limit = time.monotonic() + max(1.0, seconds)
        exited: int | None = None
        last = "no answer"
        while time.monotonic() < limit:
            if process.poll() is not None:
                exited = process.returncode
                break
            status, _, body, error = _http_get(base + "/api/health", timeout=2)
            if status == 200:
                outcome.healthy = True
                break
            last = f"HTTP {status} {_snippet(body, 80)}" if status is not None else error
            time.sleep(0.25)
        if not outcome.healthy:
            if exited is not None:
                outcome.problems.append(f"`node src/index.js` exited with code {exited} before "
                                        "GET /api/health answered")
            else:
                outcome.problems.append(f"GET /api/health did not return 200 within {seconds:.0f}s "
                                        f"(last: {last}); the server must listen on process.env.PORT "
                                        f"(was {port}) and serve /api/health")
        elif check_pages:
            status, _, body, error = _http_get(base + "/", timeout=5)
            root_ok = status == 200 and '<div id="root"' in body
            if not root_ok:
                what = f"HTTP {status}" if status is not None else error
                outcome.problems.append(f'GET / must return 200 with the built index.html (<div id="root">); '
                                        f"got {what}: {_snippet(body)} -- serve frontend/dist from the backend")
            status, content_type, body, error = _http_get(base + DEEP_LINK, timeout=5)
            is_html = "html" in content_type.lower() or "<html" in body.lower() or '<div id="root"' in body
            if status != 200 or not is_html:
                what = f"HTTP {status} ({content_type or 'no content-type'})" if status is not None else error
                outcome.problems.append(f"SPA fallback missing: GET {DEEP_LINK} must return 200 index.html; "
                                        f"got {what}: {_snippet(body)} -- every non-/api GET route must serve "
                                        "frontend/dist/index.html so deep links and reloads work")
            if root_ok and render_left is not None and process.poll() is None:
                budget = min(RENDER_TIMEOUT, render_left() - RENDER_RESERVE)
                if budget >= RENDER_MIN_SECONDS:
                    problem, note = _render_smoke(backend, base + "/", log_path.with_name("check-render.log"),
                                                  budget)
                    if problem:
                        outcome.problems.append(problem)
                    if note:
                        outcome.advisory.append(note)
                else:
                    outcome.advisory.append("ADVISORY: render smoke skipped: check deadline too close")
        if outcome.healthy and process.poll() is not None:
            outcome.problems.append(f"server exited (code {process.returncode}) while answering requests")
    finally:
        kill_group(process, grace=3.0)
    if outcome.problems:
        outcome.log_tail = _tail_lines(read_log(log_path), 40, SERVER_LOG_LIMIT)
    return outcome


def _clip_head(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 16)].rstrip() + "\n...(truncated)"


def _compose(header: str, sections: list[str], advisory: list[str]) -> str:
    body = "\n\n".join(s for s in sections if s)
    text = header + ("\n\n" + body if body else "")
    if advisory:
        room = FEEDBACK_LIMIT - len(text) - 4
        if room > 80:
            text += "\n\n" + _clip_head("\n".join(advisory), room)
    return _clip_head(text, FEEDBACK_LIMIT)


def _run_check(root: Path, log_dir: Path, ui_strings: list[str] | None,
               deadline: float | None, npm: NpmBootstrap | None, started: float) -> CheckResult:
    root = Path(root).resolve()
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    def left() -> float:
        return float("inf") if deadline is None else deadline - time.monotonic()

    sections: list[str] = []
    advisory: list[str] = []
    notes: list[str] = []

    # 1. dependencies
    bootstrap = npm if npm is not None else NpmBootstrap(root, log_dir)
    npm_exe = getattr(bootstrap, "npm", "npm") or "npm"
    npm_error = bootstrap.ensure(timeout=max(0.0, min(300.0, left() - 10)))
    # Only deterministic npm errors fail the check; network hiccups and timeouts are retried.
    hard = getattr(bootstrap, "hard_error", None)
    npm_hard_failed = bool(npm_error) and (bool(hard) if isinstance(hard, str) else npm_hard_error(npm_error))
    if npm_hard_failed:
        sections.append("NPM INSTALL FAILED (the grader deletes node_modules and runs a plain `npm install`, "
                        "so this fails the delivery; remove the package or pin a version that exists and "
                        "supports the installed React):\n" + _clip_head(npm_error, 700))
        notes.append("npm install FAILED")
    elif npm_error:
        advisory.append("ADVISORY: npm install problem (transient, not counted; retried on the next check):\n"
                        + _clip_head(npm_error, 700))

    # 2. frontend build
    build_ok = False
    frontend = root / "frontend"
    if not (frontend / "package.json").is_file():
        sections.append("BUILD FAILED: frontend/package.json is missing.")
        notes.append("build missing")
    elif left() < 5:
        sections.append("BUILD SKIPPED: check deadline reached.")
        notes.append("build skipped (deadline)")
    else:
        build_log = log_dir / "check-build.log"
        timeout = min(240.0, left())
        code, timed_out = run_logged([npm_exe, "run", "build"], frontend, build_log,
                                     timeout=timeout, env=child_env())
        build_ok = code == 0 and not timed_out
        if build_ok:
            notes.append("build ok")
        else:
            reason = f"timed out after {timeout:.0f}s" if timed_out else f"exit {code}"
            errors = extract_build_errors(read_log(build_log), root)
            sections.append(f"BUILD FAILED (`npm run build` in frontend, {reason}):\n{errors}")
            notes.append("build FAILED")

    # 3. double cold start on a fresh temp DB
    start_ok = False
    first_start_ok = False
    backend = root / "backend"
    if not (backend / "src" / "index.js").is_file():
        sections.append("START FAILED: backend/src/index.js is missing.")
        notes.append("start missing")
    elif left() < 8:
        sections.append("START SKIPPED: check deadline reached.")
        notes.append("start skipped (deadline)")
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="arc-check-"))
        db_file = temp_dir / "check.db"
        try:
            first = _server_round(backend, db_file, log_dir / "check-start-1.log",
                                  check_pages=build_ok, seconds=min(HEALTH_WAIT_SECONDS, left()),
                                  render_left=left if build_ok else None)
            first_start_ok = first.healthy and not first.problems
            advisory.extend(first.advisory)
            if first.problems:
                sections.append("START FAILED (cold start on a fresh DB):\n- " + "\n- ".join(first.problems)
                                + "\nserver log (last 40 lines):\n" + first.log_tail)
            if first.healthy and not db_file.exists():
                advisory.append("ADVISORY: the backend did not create its SQLite file at ARC_DB_FILE; "
                                "keep init_db.js honouring process.env.ARC_DB_FILE.")
            second = _Round()
            if first.healthy and left() >= 3:
                second = _server_round(backend, db_file, log_dir / "check-start-2.log",
                                       check_pages=False, seconds=min(HEALTH_WAIT_SECONDS, left()))
                if second.problems:
                    sections.append("SECOND START FAILED (restart on the same DB; schema and seed must be "
                                    "idempotent: CREATE TABLE IF NOT EXISTS, INSERT OR IGNORE / "
                                    "check-before-insert, never reset data):\n- "
                                    + "\n- ".join(second.problems)
                                    + "\nserver log (last 40 lines):\n" + second.log_tail)
            elif first.healthy:
                sections.append("SECOND START SKIPPED: check deadline reached.")
            start_ok = first_start_ok and second.healthy and not second.problems
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        notes.append("cold start x2 ok" if start_ok else "start FAILED")

    # 4. UI-string lint (advisory only)
    missing: list[str] = []
    if ui_strings:
        missing = find_missing_strings(frontend, list(ui_strings))
        if missing:
            shown = missing[:MISSING_CAP]
            more = f"\n(+{len(missing) - len(shown)} more)" if len(missing) > len(shown) else ""
            advisory.insert(0, f"ADVISORY (not a failure): {len(missing)} of {len(ui_strings)} exact UI strings "
                               "for this unit were not found verbatim in frontend/src; hidden tests locate "
                               "elements by exact text/accessible names, so use them exactly if they apply:\n"
                            + "\n".join(f'- "{text}"' for text in shown) + more)

    ok = build_ok and start_ok and not npm_hard_failed
    seconds = time.monotonic() - started
    header = f"CHECK {'PASSED' if ok else 'FAILED'}: {'; '.join(notes)} ({seconds:.1f}s)"
    feedback = _compose(header, sections, advisory)
    return CheckResult(ok=ok, build_ok=build_ok, start_ok=start_ok, missing_strings=missing,
                       feedback=feedback, seconds=seconds, first_start_ok=first_start_ok,
                       npm_ok=not npm_hard_failed)


def run_check(root: Path, log_dir: Path, *, ui_strings: list[str] | None = None,
              deadline: float | None = None, npm: NpmBootstrap | None = None) -> CheckResult:
    """Build + double cold start (+ browser render smoke) + UI-string lint. Never raises."""
    started = time.monotonic()
    try:
        return _run_check(root, log_dir, ui_strings, deadline, npm, started)
    except Exception as error:  # noqa: BLE001 - a check must never crash the agent
        seconds = time.monotonic() - started
        feedback = _clip_head(f"CHECK FAILED: internal check error: {type(error).__name__}: {error}",
                              FEEDBACK_LIMIT)
        return CheckResult(ok=False, build_ok=False, start_ok=False, missing_strings=[],
                           feedback=feedback, seconds=seconds, first_start_ok=False)


# --------------------------------------------------------------------------- cleanup

_DB_PATTERNS = ("*.db", "*.db-journal", "*.db-wal", "*.db-shm",
                "*.sqlite", "*.sqlite-journal", "*.sqlite-wal", "*.sqlite-shm",
                "*.sqlite3", "*.sqlite3-journal", "*.sqlite3-wal", "*.sqlite3-shm")
_REPORT_DIRS = ("test-results", "playwright-report", "backend/test-results", "backend/playwright-report",
                "frontend/test-results", "frontend/playwright-report", "backend/.arc-test-db")


def cleanup_output(root: Path) -> None:
    """Remove local DB files and test reports; keeps frontend/dist, .arc/, .git/, node_modules."""
    root = Path(root)
    backend = root / "backend"
    if backend.is_dir():
        for pattern in _DB_PATTERNS:
            for path in backend.glob(pattern):
                try:
                    if path.is_file() or path.is_symlink():
                        path.unlink()
                except OSError:
                    pass
    for relative in _REPORT_DIRS:
        path = root / relative
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass

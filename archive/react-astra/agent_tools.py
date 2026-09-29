"""Tool schemas and implementations for the lean agent (bash/read/write/edit/check/unit_done).

``dispatch`` never raises: every failure comes back as an ``"error: ..."`` string.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from lean_checks import child_env, read_log, run_logged

__all__ = ["TOOLS", "ToolContext", "dispatch", "clip", "file_index"]

OUTPUT_LIMIT = 6000          # tool results are kept at or below this size
BASH_DEFAULT_TIMEOUT = 120
BASH_MAX_TIMEOUT = 300
READ_DEFAULT_LIMIT = 400
READ_MAX_LIMIT = 1200
READ_MAX_CHARS = 5800        # read output is cut at a line boundary so it never needs clipping
READ_MAX_LINE = 1000         # longer (minified) lines are shortened in read output
READ_MAX_BYTES = 10_000_000
LIST_MAX_ENTRIES = 400
SUMMARY_LIMIT = 600

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tif", ".tiff", ".avif", ".heic",
    ".pdf", ".zip", ".gz", ".tgz", ".tar", ".bz2", ".xz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3", ".db-journal", ".db-wal", ".db-shm",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".wav", ".webm", ".mov",
    ".node", ".so", ".dylib", ".dll", ".exe", ".bin", ".wasm", ".class", ".pyc",
}
LIST_SKIP_DIRS = {"node_modules", "dist", ".git", ".arc", "__pycache__"}
INDEX_SKIP_DIRS = LIST_SKIP_DIRS | {"test-results", "playwright-report", "coverage", ".vite", ".cache"}
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock"}
WRITE_FORBIDDEN_PARTS = {"node_modules", ".git"}
# the placeholder main.py leaves for a payload elided from an old turn (copied back, it is no content)
ELIDED_PAYLOAD = re.compile(r"<\d+ chars (?:elided|omitted)[^>]*>")
PLACEHOLDER_ERROR = ("error: `{key}` is a placeholder for text elided from your context, not file content; "
                     "read the file and send the real text")


# --------------------------------------------------------------------------- schemas

def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


TOOLS: list[dict[str, Any]] = [
    _tool("bash",
          "Run a non-interactive shell command (`bash -c`) with cwd = project root (use `cd frontend && ...`). "
          f"Default timeout {BASH_DEFAULT_TIMEOUT}s, max {BASH_MAX_TIMEOUT}s. When the command's main process "
          "exits or times out, its WHOLE process group is killed, so background processes never outlive the "
          "call: start a server, curl it and stop it within ONE command, e.g. "
          "`cd backend && PORT=3999 ARC_DB_FILE=/tmp/t.db node src/index.js & sleep 2; "
          "curl -s localhost:3999/api/health`. Returns 'exit code N' and the combined stdout/stderr "
          "(long output keeps its head and tail).",
          {"command": {"type": "string", "description": "Shell command to run"},
           "timeout": {"type": "integer", "description": f"Seconds (default {BASH_DEFAULT_TIMEOUT}, "
                                                         f"max {BASH_MAX_TIMEOUT})"}},
          ["command"]),
    _tool("read",
          "Read a text file with 1-based line numbers (`N<TAB>text`; the prefix is not part of the file). "
          f"Default {READ_DEFAULT_LIMIT} lines from `offset`, max {READ_MAX_LIMIT}; long output stops at a "
          "line boundary and tells you the next offset. A directory path lists its entries (depth 2; "
          "node_modules, dist, .git, .arc skipped). Paths are relative to the project root (absolute paths "
          "inside it work); the requirements directory is readable too. Images/binaries are refused.",
          {"path": {"type": "string", "description": "File or directory path"},
           "offset": {"type": "integer", "description": "First line to show (1-based, default 1)"},
           "limit": {"type": "integer", "description": f"Number of lines (default {READ_DEFAULT_LIMIT})"}},
          ["path"]),
    _tool("write",
          "Create or overwrite a file with its COMPLETE content (parent directories are created). Paths are "
          "relative to the project root; node_modules, .git and the requirements directory are refused.",
          {"path": {"type": "string", "description": "File path"},
           "content": {"type": "string", "description": "Full file content"}},
          ["path", "content"]),
    _tool("edit",
          "Replace an exact text fragment in an existing file. `old` must occur exactly once (copy it "
          "verbatim, without line-number prefixes, with enough surrounding lines to be unique) unless "
          "replace_all=true. Use write for large rewrites.",
          {"path": {"type": "string", "description": "File path"},
           "old": {"type": "string", "description": "Exact existing text"},
           "new": {"type": "string", "description": "Replacement text"},
           "replace_all": {"type": "boolean", "description": "Replace every occurrence (default false)"}},
          ["path", "old", "new"]),
    _tool("check",
          "Run the project check: npm install when package.json changed, the frontend production build "
          "(`npm run build`), two cold starts of the backend on a fresh temporary SQLite DB (GET /api/health, "
          "GET /, a deep link, restart on the same DB) and an advisory lint of this unit's exact UI strings. "
          "Returns 'CHECK PASSED' or 'CHECK FAILED' with the relevant errors.",
          {}, []),
    _tool("unit_done",
          "Finish the current unit. `summary`: what was implemented (<= 600 chars). `notes`: durable "
          "architecture facts for later units (tables/columns, API routes, page routes, components, shared "
          "helpers).",
          {"summary": {"type": "string", "description": "What this unit implemented"},
           "notes": {"type": "string", "description": "Architecture notes appended to .arc/notes.md"}},
          ["summary"]),
]


# --------------------------------------------------------------------------- context

@dataclass
class ToolContext:
    root: Path
    requirements_dir: Path | None
    log_dir: Path
    run_check: Callable[[], str] | None = None
    on_unit_done: Callable[[str, str], str] | None = None
    command_deadline: float | None = None


# --------------------------------------------------------------------------- helpers

def clip(text: str, limit: int = OUTPUT_LIMIT) -> str:
    """Keep head and tail halves (total length <= limit) with an omission marker."""
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return text
    marker = f"\n...[{len(text) - limit} chars omitted]...\n"
    room = max(0, limit - len(marker))
    head = room - room // 2
    tail = room // 2
    return text[:head] + marker + (text[-tail:] if tail else "")


def _int_arg(value: Any, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _inside(path: Path, base: Path | None) -> bool:
    if base is None:
        return False
    return path == base or path.is_relative_to(base)


def _display(path: Path, ctx: ToolContext) -> str:
    root = Path(ctx.root).resolve()
    if _inside(path, root):
        return path.relative_to(root).as_posix() or "."
    return str(path)


def _resolve(raw: Any, ctx: ToolContext, *, for_write: bool) -> tuple[Path | None, str]:
    text = str(raw or "").strip()
    if not text:
        return None, "error: path is required"
    root = Path(ctx.root).resolve()
    requirements = Path(ctx.requirements_dir).resolve() if ctx.requirements_dir else None
    candidate = Path(text).expanduser()
    full = (candidate if candidate.is_absolute() else root / candidate).resolve()
    in_root = _inside(full, root)
    in_requirements = _inside(full, requirements)
    if for_write:
        if in_requirements:
            return None, f"error: {text} is inside the requirements directory, which is read-only"
        if not in_root:
            return None, f"error: {text} is outside the project root {root}; only project files may be changed"
        forbidden = WRITE_FORBIDDEN_PARTS.intersection(full.relative_to(root).parts)
        if forbidden:
            return None, f"error: refusing to modify files inside {sorted(forbidden)[0]}/"
    elif not (in_root or in_requirements):
        return None, f"error: {text} is outside the project root {root}"
    return full, ""


def _is_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with open(path, "rb") as stream:
            return b"\x00" in stream.read(8192)
    except OSError:
        return False


def _count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


# --------------------------------------------------------------------------- tools

def _bash(args: dict[str, Any], ctx: ToolContext) -> str:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return "error: command is required"
    requested = _int_arg(args.get("timeout"), None)
    timeout = float(min(requested if requested and requested > 0 else BASH_DEFAULT_TIMEOUT, BASH_MAX_TIMEOUT))
    if ctx.command_deadline is not None:
        left = ctx.command_deadline - time.monotonic()
        if left <= 0:
            return "error: the time budget for commands is exhausted; command not started"
        timeout = min(timeout, left)
    log_dir = Path(ctx.log_dir) / "bash"
    log_path = log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000_000:09d}.log"
    code, timed_out = run_logged(["bash", "-c", command], Path(ctx.root), log_path,
                                 timeout=timeout, env=child_env())
    output = read_log(log_path)
    header = f"exit code {code}"
    if timed_out:
        header += (f" (timed out after {timeout:.0f}s; every process of the command was killed -- "
                   "run long tasks with a larger timeout, never leave servers running)")
    body = output if output.strip() else "(no output)"
    budget = OUTPUT_LIMIT - len(header) - 1
    if len(body) > budget:
        note = f"\n(full output: {_display(log_path.resolve(), ctx)})"
        body = clip(body, max(200, budget - len(note))) + note
    return f"{header}\n{body}"


def _list_directory(path: Path, ctx: ToolContext) -> str:
    entries: list[str] = []
    truncated = False

    def walk(directory: Path, prefix: str, depth: int) -> None:
        nonlocal truncated
        try:
            children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as error:
            entries.append(f"{prefix}(unreadable: {error.strerror or error})")
            return
        for child in children:
            if len(entries) >= LIST_MAX_ENTRIES:
                truncated = True
                return
            if child.is_dir() and not child.is_symlink():
                if child.name in LIST_SKIP_DIRS:
                    entries.append(f"{prefix}{child.name}/ (skipped)")
                    continue
                entries.append(f"{prefix}{child.name}/")
                if depth < 2:
                    walk(child, f"{prefix}{child.name}/", depth + 1)
            else:
                entries.append(f"{prefix}{child.name}")

    walk(path, "", 1)
    if truncated:
        entries.append(f"... (listing stopped at {LIST_MAX_ENTRIES} entries)")
    header = f"{_display(path, ctx)}/ (directory, depth 2)"
    return clip(header + "\n" + ("\n".join(entries) if entries else "(empty directory)"))


def _read(args: dict[str, Any], ctx: ToolContext) -> str:
    path, error = _resolve(args.get("path"), ctx, for_write=False)
    if path is None:
        return error
    shown = _display(path, ctx)
    if path.is_dir():
        return _list_directory(path, ctx)
    if not path.exists():
        parent = path.parent
        hint = ""
        if parent.is_dir():
            names = sorted(p.name for p in parent.iterdir())[:40]
            close = difflib.get_close_matches(path.name, names, n=3, cutoff=0.5)
            if close:
                hint = f" Similar names in {_display(parent, ctx)}/: {', '.join(close)}"
        return f"error: {shown} does not exist.{hint}"
    if not path.is_file():
        return f"error: {shown} is not a regular file"
    if _is_binary(path):
        return (f"error: {shown} is a binary/image file ({path.suffix or 'binary'}); it cannot be read as "
                "text. Rely on the textual requirements instead.")
    try:
        size = path.stat().st_size
        if size > READ_MAX_BYTES:
            return f"error: {shown} is too large ({size} bytes); inspect it with bash (head/grep)"
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as err:
        return f"error: cannot read {shown}: {err.strerror or err}"
    lines = text.splitlines()
    total = len(lines)
    if total == 0:
        return f"{shown} (empty file)"
    offset = max(1, _int_arg(args.get("offset"), 1) or 1)
    limit = _int_arg(args.get("limit"), READ_DEFAULT_LIMIT) or READ_DEFAULT_LIMIT
    limit = max(1, min(limit, READ_MAX_LIMIT))
    if offset > total:
        return f"error: offset {offset} is beyond the end of {shown} (file has {total} lines)"
    end = min(total, offset + limit - 1)
    rendered: list[str] = []
    used = 0
    last = offset - 1
    for number in range(offset, end + 1):
        line = lines[number - 1]
        if len(line) > READ_MAX_LINE:
            line = line[:READ_MAX_LINE] + f" ...[+{len(line) - READ_MAX_LINE} chars]"
        entry = f"{number}\t{line}"
        if rendered and used + len(entry) + 1 > READ_MAX_CHARS - 200:
            break
        rendered.append(entry)
        used += len(entry) + 1
        last = number
    header = f"{shown} (file has {total} lines; showing {offset}-{last})"
    footer = f"\n... continue with offset={last + 1}" if last < total else ""
    return header + "\n" + "\n".join(rendered) + footer


def _write(args: dict[str, Any], ctx: ToolContext) -> str:
    path, error = _resolve(args.get("path"), ctx, for_write=True)
    if path is None:
        return error
    content = args.get("content")
    if content is None:
        return "error: content is required (the complete file content)"
    if not isinstance(content, str):
        content = json.dumps(content, indent=2, ensure_ascii=False) + "\n"
    if ELIDED_PAYLOAD.fullmatch(content.strip()):
        return PLACEHOLDER_ERROR.format(key="content")
    if path.is_dir():
        return f"error: {_display(path, ctx)} is a directory"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {_display(path, ctx)} ({_count_lines(content)} lines)"


def _normalise(line: str) -> str:
    return " ".join(line.split())


def _near_miss(content: str, old: str) -> str:
    old_lines = [line for line in old.splitlines() if line.strip()]
    if not old_lines:
        return ""
    file_lines = content.splitlines()
    wanted = [_normalise(line) for line in old_lines]
    # Whitespace-insensitive match over the non-blank lines of `old`.
    for start, line in enumerate(file_lines):
        if _normalise(line) != wanted[0]:
            continue
        index, matched, finish = start, 0, start
        while index < len(file_lines) and matched < len(wanted):
            candidate = _normalise(file_lines[index])
            if not candidate:
                index += 1
                continue
            if candidate != wanted[matched]:
                break
            matched += 1
            finish = index
            index += 1
        if matched == len(wanted):
            block = "\n".join(file_lines[start:finish + 1])
            return (f" A whitespace-insensitive match exists at lines {start + 1}-{finish + 1}; its exact text is:\n"
                    f"{clip(block, 1500)}\nUse that exact text as `old`.")
    stripped = [line.strip() for line in file_lines]
    close = difflib.get_close_matches(old_lines[0].strip(), stripped, n=1, cutoff=0.6)
    if close:
        number = stripped.index(close[0])
        window = "\n".join(f"{n + 1}\t{file_lines[n]}"
                           for n in range(max(0, number - 1), min(len(file_lines), number + 4)))
        return (f" The closest line to the start of `old` is line {number + 1}:\n{clip(window, 1500)}")
    return ""


def _edit(args: dict[str, Any], ctx: ToolContext) -> str:
    path, error = _resolve(args.get("path"), ctx, for_write=True)
    if path is None:
        return error
    shown = _display(path, ctx)
    old = args.get("old")
    new = args.get("new")
    if not isinstance(old, str) or old == "":
        return "error: `old` must be a non-empty exact text fragment (use write to create or replace whole files)"
    if new is None:
        return "error: `new` is required (use an empty string to delete the text)"
    if not isinstance(new, str):
        new = str(new)
    if ELIDED_PAYLOAD.fullmatch(new.strip()):
        return PLACEHOLDER_ERROR.format(key="new")
    if not path.is_file():
        return f"error: {shown} does not exist (use write to create it)"
    content = path.read_text(encoding="utf-8", errors="replace")
    if "\r\n" in content and "\r\n" not in old and old.replace("\n", "\r\n") in content:
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    count = content.count(old)
    if count == 0:
        return (f"error: `old` text was not found in {shown}.{_near_miss(content, old)}"
                "\nRe-read the relevant lines and copy the text exactly (without line-number prefixes).")
    replace_all = _truthy(args.get("replace_all"))
    if count > 1 and not replace_all:
        positions, start = [], 0
        while len(positions) < 10:
            index = content.find(old, start)
            if index < 0:
                break
            positions.append(str(content.count("\n", 0, index) + 1))
            start = index + 1
        return (f"error: `old` text matches {count} times in {shown} (at lines {', '.join(positions)}); include "
                "more surrounding context to make it unique, or set replace_all=true")
    if old == new:
        return f"error: `new` is identical to `old`; {shown} unchanged"
    first_line = content.count("\n", 0, content.find(old)) + 1
    updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    path.write_text(updated, encoding="utf-8")
    replaced = count if replace_all else 1
    return (f"edited {shown}: replaced {replaced} occurrence{'s' if replaced != 1 else ''} "
            f"(first at line {first_line}); file now has {_count_lines(updated)} lines")


def _check(args: dict[str, Any], ctx: ToolContext) -> str:
    if ctx.run_check is None:
        return "error: check is not available in this context"
    return str(ctx.run_check())


def _unit_done(args: dict[str, Any], ctx: ToolContext) -> str:
    summary = str(args.get("summary") or "").strip()[:SUMMARY_LIMIT]
    notes = args.get("notes")
    notes = "" if notes is None else (notes if isinstance(notes, str) else json.dumps(notes, ensure_ascii=False))
    if ctx.on_unit_done is None:
        return "unit done"
    return str(ctx.on_unit_done(summary, notes))


_HANDLERS: dict[str, Callable[[dict[str, Any], ToolContext], str]] = {
    "bash": _bash, "read": _read, "write": _write, "edit": _edit, "check": _check, "unit_done": _unit_done,
}


def dispatch(name: str, args: dict, ctx: ToolContext) -> str:
    """Execute a tool call. Never raises; errors are returned as "error: ..." strings."""
    try:
        if isinstance(args, (str, bytes)):
            raw = args.decode("utf-8", "replace") if isinstance(args, bytes) else args
            try:
                args = json.loads(raw) if raw.strip() else {}
            except ValueError as error:
                return f"error: invalid JSON arguments for {name}: {error}"
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return f"error: arguments for {name} must be a JSON object"
        handler = _HANDLERS.get(str(name))
        if handler is None:
            return f"error: unknown tool {name!r}; available tools: {', '.join(_HANDLERS)}"
        result = handler(args, ctx)
        return result if isinstance(result, str) else str(result)
    except Exception as error:  # noqa: BLE001 - tools must never crash the loop
        return f"error: {name} failed: {type(error).__name__}: {error}"


# --------------------------------------------------------------------------- file index

def file_index(root: Path, limit_chars: int = 6000) -> str:
    """Sorted "path  (N lines)" list: frontend/src + backend/src (any depth), then other text files
    at depth <= 3 (lockfiles, binaries, build/test output and hidden files excluded), capped."""
    root = Path(root)
    source_roots = ("frontend/src/", "backend/src/")
    sources: list[tuple[str, int]] = []
    others: list[tuple[str, int]] = []
    if not root.is_dir():
        return "(no files)"
    for directory, dirs, files in os.walk(root):
        relative_dir = Path(directory).relative_to(root)
        rel_dir = relative_dir.as_posix()
        in_source = any((rel_dir + "/").startswith(prefix) for prefix in source_roots)
        depth = 0 if rel_dir == "." else len(relative_dir.parts)
        kept = []
        for name in sorted(dirs):
            if name in INDEX_SKIP_DIRS or name.startswith("."):
                continue
            child = (relative_dir / name).as_posix()
            if in_source or depth < 2 or any(prefix.startswith(child + "/") for prefix in source_roots):
                kept.append(name)
        dirs[:] = kept
        for name in files:
            if name.startswith(".") or name in LOCKFILES:
                continue
            path = Path(directory) / name
            rel = (relative_dir / name).as_posix() if rel_dir != "." else name
            if not in_source and len(Path(rel).parts) > 3:
                continue
            if path.suffix.lower() in BINARY_EXTENSIONS or path.is_symlink():
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:8192]:
                continue
            count = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
            (sources if in_source else others).append((rel, count))
    ordered = sorted(sources) + sorted(others)
    lines: list[str] = []
    used = 0
    for position, (rel, count) in enumerate(ordered):
        entry = f"{rel}  ({count} lines)"
        if used + len(entry) + 1 > limit_chars - 40:
            lines.append(f"... (+{len(ordered) - position} more files not listed)")
            break
        lines.append(entry)
        used += len(entry) + 1
    return "\n".join(lines) if lines else "(no files)"

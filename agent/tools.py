"""File and shell tools exposed to the model. Paths are relative to the workspace root."""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
from pathlib import Path

OUTPUT_LIMIT = 12000
SECRET_ENV = ("OPENAI_API_KEY", "VISUAL_API_KEY", "ARCBENCH_COOKIE", "ARCBENCH_PASSWORD")

SCHEMAS = [
    {"name": "read", "description": "Read a text file (numbered lines; use offset/limit for large files) or view an image (.png/.jpg/.webp).",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}},
         "required": ["path"]}},
    {"name": "write", "description": "Create or overwrite a file with the full content.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit", "description": "Replace one exact, unique occurrence of old_text with new_text. For "
     "several changes use apply.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
         "required": ["path", "old_text", "new_text"]}},
    {"name": "apply", "description": "Make several file changes in one call: each change either writes a "
     "whole file (path, content) or replaces one exact, unique occurrence (path, old_text, new_text). "
     "Changes to the same file apply in order. A file with a change that cannot be applied is left unchanged "
     "and reported; the other files are written.",
     "parameters": {"type": "object", "properties": {"changes": {"type": "array", "items": {
         "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"},
                                          "old_text": {"type": "string"}, "new_text": {"type": "string"}},
         "required": ["path"]}}}, "required": ["changes"]}},
    {"name": "bash", "description": "Run a shell command in the workspace root (no interactive or "
     "long-running servers; they are killed at the timeout).",
     "parameters": {"type": "object", "properties": {
         "command": {"type": "string"}, "timeout": {"type": "integer", "description": "seconds, max 600"}},
         "required": ["command"]}},
]


def clip(text: str, limit: int = OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    head = limit // 3
    return f"{text[:head]}\n... [{len(text) - limit} chars omitted] ...\n{text[-(limit - head):]}"


class Tools:
    def __init__(self, root: Path, readable: list[Path] | None = None, read_only: bool = False):
        self.root = root.resolve()
        self.readable = [self.root, *[p.resolve() for p in readable or []]]
        self.read_only = read_only  # only read and read-only shell commands

    @property
    def schemas(self) -> list[dict]:
        return [s for s in SCHEMAS if not self.read_only or s["name"] in ("read", "bash")]

    def _path(self, path: str, *, write: bool) -> Path:
        target = (self.root / path).resolve()
        if not write and not target.exists():  # relative links in the requirements point into their directory
            target = next((found for base in self.readable[1:] if (found := (base / path).resolve()).exists()), target)
        allowed = [self.root] if write else self.readable
        if not any(target == base or base in target.parents for base in allowed):
            raise ValueError(f"path outside the workspace: {path}")
        if write and "node_modules" in target.relative_to(self.root).parts:
            raise ValueError("do not edit node_modules")
        return target

    def run(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
            if self.read_only and (name not in ("read", "bash")
                                   or (name == "bash" and not is_read_only(args.get("command", "")))):
                return ("ERROR: this session is read-only; use read and read-only shell commands (git diff/show/"
                        "log, grep, ls, cat, sed -n) without redirection")
            return getattr(self, f"_{name}")(**args)
        except TypeError as error:  # arguments that do not match the schema, e.g. apply without changes[]
            schema = next((s["parameters"] for s in SCHEMAS if s["name"] == name), {})
            return f"ERROR: {error}; {name} takes {json.dumps(schema.get('properties', {}))}"
        except Exception as error:  # the model sees every tool failure and decides what to do
            return f"ERROR: {type(error).__name__}: {error}"

    def _read(self, path: str, offset: int = 1, limit: int = 400) -> str:
        lines = self._path(path, write=False).read_text(errors="replace").splitlines()
        start = max(1, offset)
        body = "\n".join(f"{i:5} {line}" for i, line in enumerate(lines[start - 1:start - 1 + limit], start))
        more = len(lines) - (start - 1 + limit)
        return clip(body + (f"\n... {more} more lines" if more > 0 else ""))

    def _write(self, path: str, content: str) -> str:
        target = self._path(path, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(content)
        tmp.replace(target)
        return f"wrote {path} ({content.count(chr(10)) + 1} lines)"

    def _edit(self, path: str, old_text: str, new_text: str) -> str:
        target = self._path(path, write=True)
        text = target.read_text()
        count = text.count(old_text)
        if count != 1:
            return f"ERROR: old_text found {count} times in {path}; it must match exactly once"
        target.write_text(text.replace(old_text, new_text))
        return f"edited {path}"

    def _apply(self, changes: list[dict]) -> str:
        pending: dict[Path, str] = {}  # final text per file; a failed change leaves its file's text as it was
        failed: list[tuple[Path | None, str]] = []
        for number, change in enumerate(changes, 1):
            path = str(change.get("path", ""))
            try:
                target = self._path(path, write=True)
            except ValueError as error:
                failed.append((None, f"change {number} ({path}): {error}"))
                continue
            if "content" in change:
                pending[target] = str(change["content"])
                continue
            if "old_text" not in change or "new_text" not in change:
                failed.append((target, f"change {number} ({path}): needs content, or old_text and new_text"))
                continue
            if target not in pending and not target.is_file():
                failed.append((target, f"change {number}: {path} does not exist"))
                continue
            text = pending.get(target, target.read_text() if target.is_file() else "")
            count = text.count(change["old_text"])
            if count != 1:
                failed.append((target, f"change {number} ({path}): old_text found {count} times; it must match "
                                       "exactly once"))
                continue
            pending[target] = text.replace(change["old_text"], change["new_text"])
        broken = {target for target, _ in failed}  # a file with a failed change keeps its old text whole
        for target, text in pending.items():
            if target in broken:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(text)
            tmp.replace(target)
        written = ", ".join(str(t.relative_to(self.root)) for t in pending if t not in broken) or "nothing"
        if failed:
            return (f"ERROR: {len(failed)} of {len(changes)} changes failed; files with a failed change were left "
                    f"unchanged, the other files were written ({written}). Resend every change to these files:\n"
                    + "\n".join(f"- {f}" for _, f in failed))
        return f"applied: {written}"

    def _bash(self, command: str, timeout: int = 180) -> str:
        return shell(command, self.root, min(max(timeout, 1), 600))


READ_ONLY = {"cat", "ls", "grep", "rg", "egrep", "head", "tail", "wc", "find", "sed", "awk", "sort", "uniq",
             "cut", "tr", "echo", "printf", "pwd", "tree", "stat", "file", "diff", "jq", "nl", "basename",
             "dirname", "realpath", "true", "cd", "git"}
READ_ONLY_GIT = {"diff", "log", "show", "status", "grep", "ls-files", "rev-parse", "blame", "branch"}
UNSAFE = re.compile(r"(?<![0-9&])>(?!&)|>>|`|\$\(|\s-exec\b|\s-execdir\b|\s-delete\b|\s-fprint|\btee\b"
                    r"|\bsystem\s*\(|\s-i\b|--in-place|\s--output\b")


def is_read_only(command: str) -> bool:
    """True for commands made only of known read-only programs, without output redirection or substitution.

    Such commands may run concurrently with other read-only calls; anything unrecognised runs in order."""
    text = re.sub(r"\s[12]?>\s*/dev/null|\s2>&1", " ", command)
    if not text.strip() or UNSAFE.search(text):
        return False
    for segment in re.split(r"&&|\|\||;|\||\n", text):
        try:
            words = shlex.split(segment)
        except ValueError:
            return False
        if not words:
            continue
        if words[0] not in READ_ONLY:
            return False
        if words[0] == "sort" and any(w.startswith("-o") or w.startswith("--output") for w in words[1:]):
            return False
        if words[0] == "git" and (len(words) < 2 or words[1] not in READ_ONLY_GIT
                                  or (words[1] == "branch" and len(words) > 2)):
            return False
    return True


def kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # group already gone (macOS reports EPERM)
        pass


def shell(command: str, cwd: Path, timeout: int, env: dict | None = None) -> str:
    """Run in a new process group; the whole group is killed on timeout so servers do not linger."""
    clean = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    clean.update(env or {})
    proc = subprocess.Popen(["bash", "-lc", command], cwd=cwd, env=clean, text=True, errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        status = f"exit {proc.returncode}"
    except subprocess.TimeoutExpired:
        kill_group(proc.pid)
        out, _ = proc.communicate()
        status = f"killed after {timeout}s timeout"
    finally:
        kill_group(proc.pid)  # background children started by the command
    return clip(f"{out or ''}\n[{status}]")

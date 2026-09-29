"""File and shell tools exposed to the model. Paths are relative to the workspace root."""
from __future__ import annotations

import json
import os
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
    {"name": "edit", "description": "Replace one exact, unique occurrence of old_text with new_text.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
         "required": ["path", "old_text", "new_text"]}},
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
    def __init__(self, root: Path, readable: list[Path] | None = None):
        self.root = root.resolve()
        self.readable = [self.root, *[p.resolve() for p in readable or []]]

    def _path(self, path: str, *, write: bool) -> Path:
        target = (self.root / path).resolve()
        allowed = [self.root] if write else self.readable
        if not any(target == base or base in target.parents for base in allowed):
            raise ValueError(f"path outside the workspace: {path}")
        if write and "node_modules" in target.relative_to(self.root).parts:
            raise ValueError("do not edit node_modules")
        return target

    def run(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
            return getattr(self, f"_{name}")(**args)
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

    def _bash(self, command: str, timeout: int = 180) -> str:
        return shell(command, self.root, min(max(timeout, 1), 600))


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
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        status = f"killed after {timeout}s timeout"
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # background children started by the command
        except ProcessLookupError:
            pass
    return clip(f"{out or ''}\n[{status}]")

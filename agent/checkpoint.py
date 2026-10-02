"""Session transcripts and workspace commits, so a run can resume from any recorded step.

Each session writes <root>/.agent/<label>.jsonl with one JSON record per line:
  {"type": "message", "message": {...}}                      appended message
  {"type": "compaction", "messages": [...], "state": {...}}  context replaced by a compaction
  {"type": "checkpoint", "step": n, "commit": sha, "count": k} after step n: first k messages + commit
The file is plain JSONL and may be edited by hand (e.g. rewrite a tool result, drop the last steps).
Run progress (finished phases) lives in <root>/.agent/run.json. The .agent directory is not tracked by git.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from tools import shell

AGENT_DIR = ".agent"


def commit(root: Path, message: str) -> str:
    """Commit every change in the workspace (possibly empty) and return the commit sha."""
    shell(f"git add -A && git commit -q --allow-empty -m {json.dumps(message)}", root, 60)
    return shell("git rev-parse HEAD", root, 30).split()[0]


def reset(root: Path, sha: str) -> None:
    shell(f"git reset -q --hard {sha} && git clean -qfd -e node_modules -e {AGENT_DIR}", root, 60)


class Transcript:
    def __init__(self, root: Path, label: str, commits: bool = True):
        self.root, self.commits = root, commits  # without commits: a record for reading, not for resuming
        self.path = root / AGENT_DIR / f"{label.replace(':', '-')}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, record: dict) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def message(self, message: dict) -> None:
        self._write({"type": "message", "message": message})

    def compaction(self, messages: list[dict], state: dict) -> None:
        self._write({"type": "compaction", "messages": messages, "state": state})

    def checkpoint(self, step: int, count: int, label: str) -> str:
        sha = commit(self.root, f"{label} step {step}") if self.commits else ""
        self._write({"type": "checkpoint", "step": step, "commit": sha, "count": count})
        return sha

    def load(self, step: int | None = None) -> tuple[list[dict], dict, int, str] | None:
        """Messages, compaction state, step and commit at checkpoint `step` (default: the last one)."""
        if not self.path.exists():
            return None
        messages: list[dict] = []
        state: dict = {}
        found = None
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record["type"] == "message":
                messages.append(record["message"])
            elif record["type"] == "compaction":
                messages = list(record["messages"])
                state = dict(record["state"])
            elif record["type"] == "checkpoint":
                found = ([dict(m) for m in messages[:record["count"]]], dict(state), record["step"], record["commit"])
                if record["step"] == step:
                    break
        if step is not None and (found is None or found[2] != step):
            raise ValueError(f"no checkpoint for step {step} in {self.path}")
        return found

    def archive(self) -> None:
        if self.path.exists():
            self.path.rename(self.path.with_suffix(f".replaced-{int(time.time())}.jsonl"))

    def truncate(self, step: int) -> None:
        """Keep the transcript up to and including checkpoint `step`; later records are archived."""
        lines = self.path.read_text().splitlines(keepends=True)
        for i, line in enumerate(lines):
            record = json.loads(line)
            if record["type"] == "checkpoint" and record["step"] == step:
                self.path.with_suffix(f".after-{step}.jsonl").write_text("".join(lines[i + 1:]))
                self.path.write_text("".join(lines[:i + 1]))
                return
        raise ValueError(f"no checkpoint for step {step} in {self.path}")


class RunState:
    """Finished phases and their commits; every call re-reads the file so instances never go stale."""

    def __init__(self, root: Path):
        self.path = root / AGENT_DIR / "run.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def data(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {"done": {}}

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))

    def done(self, phase: str) -> str | None:
        """Commit recorded when `phase` finished, or None."""
        return self.data["done"].get(phase)

    def finish(self, phase: str, sha: str) -> None:
        data = self.data
        data["done"][phase] = sha
        self._save(data)

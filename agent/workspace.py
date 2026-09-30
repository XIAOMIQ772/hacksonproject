"""Git worktrees for parallel workers and merges into the integration branch (the output directory)."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from tools import shell

MODULE_DIRS = ("backend/node_modules", "frontend/node_modules")


def git(root: Path, command: str, timeout: int = 120) -> tuple[bool, str]:
    out = shell(f"git {command}", root, timeout)
    return out.rstrip().endswith("[exit 0]"), out


def head(root: Path) -> str:
    return shell("git rev-parse HEAD", root, 30).split()[0]


def location(root: Path, node_id: str) -> Path:
    """Outside the output directory, so a worker never mistakes the integration branch for its own files."""
    key = hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:10]
    return Path(tempfile.gettempdir()).resolve() / "agent-worktrees" / key / node_id


def create(root: Path, node_id: str, base: str) -> Path:
    """A fresh worktree on branch node/<id> starting at `base`, sharing the installed dependencies."""
    path = location(root, node_id)
    remove(root, node_id)
    ok, out = git(root, f"worktree add -q -B node/{node_id} {path} {base}")
    if not ok:
        raise RuntimeError(f"git worktree add failed for {node_id}:\n{out}")
    for rel in MODULE_DIRS:
        target = root / rel
        if target.is_dir() and not (path / rel).exists():
            (path / rel).parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, path / rel)
    return path


def existing(root: Path, node_id: str) -> Path | None:
    path = location(root, node_id)
    return path if (path / ".git").exists() else None


def remove(root: Path, node_id: str) -> None:
    path = location(root, node_id)
    listing = shell("git worktree list --porcelain", root, 30)
    holders = [block.split("\n", 1)[0].removeprefix("worktree ") for block in listing.split("\n\n")
               if f"branch refs/heads/node/{node_id}" in block]  # includes worktrees left at older locations
    for holder in {*holders, str(path)}:
        if Path(holder).exists():
            git(root, f"worktree remove --force {holder}")
            shutil.rmtree(holder, ignore_errors=True)
    git(root, "worktree prune")
    try:
        path.parent.rmdir()  # the run's worktree folder, once its last worktree is gone
    except OSError:
        pass


def merge(root: Path, node_id: str) -> tuple[bool, str]:
    """Merge node/<id> into the integration branch; on conflict the merge is left in progress."""
    ok, out = git(root, f"merge --no-ff --no-edit -m 'merge {node_id}' node/{node_id}")
    return ok, out


def conflicts(root: Path) -> list[str]:
    return [line for line in shell("git diff --name-only --diff-filter=U", root, 30).splitlines()
            if line and not line.startswith("[")]


def abort(root: Path, sha: str) -> None:
    git(root, "merge --abort")
    git(root, f"reset -q --hard {sha}")


def sync(root: Path, node_id: str, sha: str) -> list[str]:
    """Merge the integration commit `sha` into the node's worktree and commit; returns files left with
    conflict markers for the node's engineer to resolve."""
    path = location(root, node_id)
    git(path, "add -A")
    git(path, "commit -q -m 'work in progress before sync'")
    ok, _ = git(path, f"merge --no-edit -m 'sync with integration {sha[:8]}' {sha}")
    files = [] if ok else conflicts(path)
    if not ok:
        git(path, "add -A")
        git(path, f"commit -q -m 'sync with integration {sha[:8]} (conflicts left to resolve)'")
    return files

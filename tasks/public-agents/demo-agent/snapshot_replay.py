from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from arcbench_agent_runtime import AgentRuntime


# Demo workspaces are read-only teaching views. Dependencies and build/runtime
# outputs belong to the single server-side pre-deployed preview for each step;
# copying them into every user's current-source view wastes hundreds of MB.
WORKSPACE_IGNORED_NAMES = {
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".cache",
    ".vite",
    "database.db",
    "database.db-wal",
    "database.db-shm",
    "database.db-journal",
}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value


def _copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("node_modules", "dist", "coverage", "*.db", "*.db-*"))


def _copy_file_or_dir(source: Path, target: Path) -> None:
    if not source.exists():
        return
    if source.is_dir():
        # Build the complete snapshot beside the live path, then swap it in
        # one rename so API readers never observe an empty traceability tree.
        temporary = target.with_name(f".{target.name}.next")
        backup = target.with_name(f".{target.name}.previous")
        if temporary.exists():
            shutil.rmtree(temporary) if temporary.is_dir() else temporary.unlink()
        if backup.exists():
            shutil.rmtree(backup) if backup.is_dir() else backup.unlink()
        shutil.copytree(source, temporary)
        if target.exists():
            target.rename(backup)
        temporary.rename(target)
        if backup.exists():
            shutil.rmtree(backup) if backup.is_dir() else backup.unlink()
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.next")
        shutil.copy2(source, temporary)
        temporary.replace(target)


def _publish_project_snapshot(source: Path, target: Path) -> None:
    """Publish every top-level project entry without exposing a half-copied tree."""
    preserved = {"requirements", ".arc", "tests"}
    source_names = {
        child.name
        for child in source.iterdir()
        if child.name not in preserved and child.name not in WORKSPACE_IGNORED_NAMES
    }
    for child in source.iterdir():
        if child.name in preserved or child.name in WORKSPACE_IGNORED_NAMES:
            continue
        _copy_file_or_dir(child, target / child.name)
    for child in list(target.iterdir()):
        if child.name in preserved or child.name in source_names:
            continue
        if child.name.startswith(".") and child.name.endswith((".next", ".previous")):
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink(missing_ok=True)


def run_snapshot_replay(*, bundle_root: Path, target_dir: Path, arc_dir: Path, requirement_dir: Path) -> int:
    configured_snapshot_root = os.environ.get("ARCBENCH_DEMO_SNAPSHOT_DIR", "").strip()
    snapshot_root = (
        Path(configured_snapshot_root).expanduser()
        if configured_snapshot_root
        else bundle_root / "snapshots" / "ticketbooking"
    )
    if not snapshot_root.is_dir():
        raise RuntimeError(f"Demo snapshot directory is missing: {snapshot_root}")
    manifest = _read_json(snapshot_root / "manifest.json", {})
    steps = manifest.get("steps") if isinstance(manifest, dict) else None
    if not isinstance(steps, list) or not steps:
        raise RuntimeError(f"Demo snapshot manifest is missing or empty: {snapshot_root}")
    # Repair snapshots are materialized explicitly by the demo TDD action;
    # the normal Quick Start replay intentionally ends at the failing baseline.
    checkpoint_path = arc_dir / "checkpoint.json"
    checkpoint = _read_json(checkpoint_path, {"last_completed_index": 0, "completed": [], "paused": False})
    initial_step_count = int(checkpoint.get("replay_max_index") or manifest.get("initial_step_count", len(steps)) or len(steps))
    steps = [step for step in steps if int(step.get("index", 0) or 0) <= initial_step_count]
    current_index = max(0, int(checkpoint.get("last_completed_index", 0) or 0))
    if current_index > len(steps):
        raise RuntimeError("Demo snapshot pointer is beyond the available snapshot set")

    runtime = AgentRuntime.from_env(
        project_dir=str(target_dir),
        runner_events_path=str(arc_dir / "runner-events.jsonl"),
        traceability_dir=str(arc_dir / "traceability"),
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    arc_dir.mkdir(parents=True, exist_ok=True)
    if current_index == 0:
        (arc_dir / "runner-events.jsonl").write_text("", encoding="utf-8")
        _write_json(checkpoint_path, {"last_completed_index": 0, "completed": [], "paused": False})
        runtime.events.mark_run_started("Demo snapshot replay started")

    for raw in steps[current_index:]:
        index = int(raw.get("index", 0) or 0)
        step_dir = snapshot_root / "steps" / f"{index:04d}"
        if not step_dir.is_dir():
            raise FileNotFoundError(f"Demo snapshot step not found: {step_dir}")
        project_snapshot = step_dir / "project"
        if not project_snapshot.is_dir():
            raise FileNotFoundError(f"Demo snapshot project not found: {project_snapshot}")

        # Keep the pointer on the previous snapshot while Stage 2 is visibly
        # running.  The pointer advances only after this delay and the next
        # snapshot has been fully materialized.
        delay = float(os.environ.get("ARCBENCH_REPLAY_STEP_DELAY_SECONDS", "1.5"))
        deadline = time.monotonic() + max(delay, 0.0)
        while time.monotonic() < deadline:
            if (arc_dir / "pause.request.json").exists():
                checkpoint["paused"] = True
                _write_json(checkpoint_path, checkpoint)
                runtime.events.mark_run_paused("Generation paused")
                return 0
            time.sleep(min(0.1, deadline - time.monotonic()))

        target_dir.mkdir(parents=True, exist_ok=True)
        _publish_project_snapshot(project_snapshot, target_dir)
        target_requirements_dir = target_dir / "requirements"
        # Incremental teaching snapshots carry their own requirement tree.
        # Re-copying the catalog document here would make steps 31/34 briefly
        # appear and then revert to the original requirements.
        snapshot_requirements_dir = project_snapshot / "requirements"
        requirements_source = snapshot_requirements_dir if snapshot_requirements_dir.is_dir() else requirement_dir
        if requirements_source.is_dir() and requirements_source.resolve() != target_requirements_dir.resolve():
            _copy_file_or_dir(requirements_source, target_requirements_dir)

        _copy_file_or_dir(step_dir / "traceability", arc_dir / "traceability")
        _copy_file_or_dir(step_dir / "runner-events.jsonl", arc_dir / "runner-events.jsonl")
        _copy_file_or_dir(step_dir / "queue.json", arc_dir / "processing_queue.json")
        _copy_file_or_dir(step_dir / "node-sessions", arc_dir / "node_sessions")
        checkpoint = _read_json(step_dir / "checkpoint.json", {})
        checkpoint["last_completed_index"] = index
        checkpoint["paused"] = False
        _write_json(checkpoint_path, checkpoint)
        current_index = index

    (arc_dir / "preview-ready.json").write_text(json.dumps({"ready": True, "reason": "demo snapshot replay completed"}) + "\n", encoding="utf-8")
    runtime.events.mark_run_completed("Demo snapshot replay completed")
    return 0

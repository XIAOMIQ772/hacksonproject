from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arcbench_agent_runtime import AgentRuntime


DEFAULT_STEP_DELAY_SECONDS = float(os.environ.get("ARCBENCH_REPLAY_STEP_DELAY_SECONDS", "1.5"))
DEFAULT_INTERFACE_DELAY_SECONDS = float(os.environ.get("ARCBENCH_REPLAY_INTERFACE_DELAY_SECONDS", "1.5"))
DEFAULT_TEST_DELAY_SECONDS = float(os.environ.get("ARCBENCH_REPLAY_TEST_DELAY_SECONDS", "1.5"))
DEFAULT_PHASE_DELAY_SECONDS = float(os.environ.get("ARCBENCH_REPLAY_PHASE_DELAY_SECONDS", "1.5"))
DEFAULT_INTERFACE_GROUP_DELAY_SECONDS = float(
    os.environ.get("ARCBENCH_REPLAY_INTERFACE_GROUP_DELAY_SECONDS", "1.5")
)
DEFAULT_TEST_GROUP_DELAY_SECONDS = float(os.environ.get("ARCBENCH_REPLAY_TEST_GROUP_DELAY_SECONDS", "1.5"))
DEFAULT_BEFORE_NODE_PASS_DELAY_SECONDS = float(
    os.environ.get("ARCBENCH_REPLAY_BEFORE_NODE_PASS_DELAY_SECONDS", "1.5")
)

CHECKPOINT_PATH = Path(os.environ.get("ARCBENCH_CHECKPOINT_PATH", ".arc/checkpoint.json"))
PAUSE_REQUEST_PATH = Path(os.environ.get("ARCBENCH_PAUSE_REQUEST_PATH", ".arc/pause.request.json"))
RESUME_REQUEST_PATH = Path(os.environ.get("ARCBENCH_RESUME_REQUEST_PATH", ".arc/resume.request.json"))
RUNNER_EVENTS_PATH = Path(os.environ.get("ARCBENCH_RUNNER_EVENTS_PATH", ".arc/runner-events.jsonl"))
TRACEABILITY_DIR = Path(os.environ.get("ARCBENCH_TRACEABILITY_DIR", ".arc/traceability"))
STATE_CHECKPOINTS_DIR = CHECKPOINT_PATH.parent / "state-checkpoints"

INTERFACE_GROUP_ORDER = ("UI", "API", "FUNC", "DB")
TEST_GROUP_ORDER = ("Unit", "Integration", "E2E")
DEMO_BASE_TREE_SENTINEL = "__arcbench_base_tree__"

FRONTEND_API_BRIDGES: dict[str, dict[str, str]] = {
    "API-BE-AUTH-REGISTER": {
        "fe_id": "API-FE-AUTH-REGISTER",
        "name": "Register User API Client",
        "description": "Posts the registration payload from the register page to the backend auth register route.",
        "file_path": "frontend/src/api/auth.ts",
        "first_line": "export function registerUser(payload: {",
    },
    "API-BE-AUTH-LOGIN": {
        "fe_id": "API-FE-AUTH-LOGIN",
        "name": "Login API Client",
        "description": "Posts the login payload from the login page to the backend auth login route.",
        "file_path": "frontend/src/api/auth.ts",
        "first_line": "export function loginUser(payload: { account: string; password: string }) {",
    },
    "API-BE-SEARCH-TICKETS": {
        "fe_id": "API-FE-SEARCH-TICKETS",
        "name": "Search Tickets API Client",
        "description": "Fetches the search result payload for the submitted route and departure date.",
        "file_path": "frontend/src/api/search.ts",
        "first_line": "export function searchTickets(params: { from?: string; to?: string; date?: string }) {",
    },
    "API-BE-SEARCH-TRAIN-DETAIL": {
        "fe_id": "API-FE-SEARCH-TRAIN-DETAIL",
        "name": "Train Detail API Client",
        "description": "Loads the selected train detail payload before the downstream booking flow continues.",
        "file_path": "frontend/src/api/search.ts",
        "first_line": "export function fetchTrainDetail(trainId: string, date: string) {",
    },
    "API-BE-BOOKING-OPTIONS": {
        "fe_id": "API-FE-BOOKING-OPTIONS",
        "name": "Booking Options API Client",
        "description": "Fetches the selected train summary and booking defaults for the booking page shell.",
        "file_path": "frontend/src/api/booking.ts",
        "first_line": "export function fetchBookingOptions(params: { trainId: string; date: string }) {",
    },
    "API-BE-BOOKING-ORDERS": {
        "fe_id": "API-FE-BOOKING-ORDERS",
        "name": "Create Booking API Client",
        "description": "Posts the booking passenger payload from the booking form to the backend booking create route.",
        "file_path": "frontend/src/api/booking.ts",
        "first_line": "export function createBooking(payload: {",
    },
    "API-BE-BOOKING-RESULT": {
        "fe_id": "API-FE-BOOKING-RESULT",
        "name": "Booking Result API Client",
        "description": "Fetches the stored booking result payload for the booking success page.",
        "file_path": "frontend/src/api/booking.ts",
        "first_line": "export function fetchBookingResult(bookingId: string) {",
    },
}

BUNDLE_ROOT = Path(__file__).resolve().parent
SOURCE_TEMPLATE_DIR = BUNDLE_ROOT / "template"
REPLAY_ROOT = SOURCE_TEMPLATE_DIR / "arc-replay"
QUEUE_PATH = REPLAY_ROOT / "queue.json"
TASKS_DIR = REPLAY_ROOT / "tasks"

_checkpoint_state: dict[str, Any] = {"payload": None}
_runtime_state: dict[str, AgentRuntime | None] = {"runtime": None}


class ResumePatchConflictError(RuntimeError):
    """Raised when replay patch application conflicts with the current workspace."""


@dataclass(slots=True)
class ReplayConfig:
    requirement_dir: Path
    source_template_dir: Path
    queue_path: Path
    tasks_dir: Path
    target_template_dir: Path
    arc_dir: Path
    submission_dir: Path | None
    step_delay_seconds: float
    interface_delay_seconds: float
    test_delay_seconds: float
    phase_delay_seconds: float
    interface_group_delay_seconds: float
    test_group_delay_seconds: float
    before_node_pass_delay_seconds: float


@dataclass(slots=True)
class ReplayStep:
    index: int
    node_id: str
    phase: str
    task_path: Path
    commit_message: str
    source_commit: str
    interfaces: list[dict[str, Any]]
    tests: list[dict[str, Any]]
    implemented_interface_ids: list[str]
    passed_test_ids: list[str]


def log(message: str) -> None:
    print(f"[demo-agent] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay the prepared ARC-Bench demo history into the runner template workspace.")
    parser.add_argument(
        "requirement_path",
        nargs="?",
        default=os.environ.get("ARCBENCH_TASK_DIR", "requirements"),
        help="Requirement directory containing requirements.yaml.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output workspace directory. For the demo replay this is the target template workspace.",
    )
    parser.add_argument(
        "--app-type",
        choices=["web", "android"],
        default="web",
        help="Application type for runtime context.",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=int(os.environ.get("ARCBENCH_WEB_PORT", "3000")),
        help="Backend port for generated web applications.",
    )
    parser.add_argument("--source-template", help="Source template repository containing git history and arc-replay metadata.")
    parser.add_argument("--queue", help="Queue JSON that defines replay order. Defaults to <source-template>/arc-replay/queue.json.")
    parser.add_argument("--tasks-dir", help="Task directory containing <node>.<phase>.json replay metadata.")
    parser.add_argument("--target-template", help="Target template workspace. Defaults to ARCBENCH_TEMPLATE_DIR.")
    parser.add_argument("--arc-dir", help="Runtime state directory. Defaults to <output-dir>/.arc.")
    parser.add_argument("--artifacts-dir", help=argparse.SUPPRESS)
    parser.add_argument("--submission-dir", help="Submission directory for logging only. Defaults to ARCBENCH_SUBMISSION_DIR when present.")
    parser.add_argument("--step-delay", type=float, default=DEFAULT_STEP_DELAY_SECONDS)
    parser.add_argument("--interface-delay", type=float, default=DEFAULT_INTERFACE_DELAY_SECONDS)
    parser.add_argument("--test-delay", type=float, default=DEFAULT_TEST_DELAY_SECONDS)
    parser.add_argument("--phase-delay", type=float, default=DEFAULT_PHASE_DELAY_SECONDS)
    parser.add_argument("--interface-group-delay", type=float, default=DEFAULT_INTERFACE_GROUP_DELAY_SECONDS)
    parser.add_argument("--test-group-delay", type=float, default=DEFAULT_TEST_GROUP_DELAY_SECONDS)
    parser.add_argument("--before-node-pass-delay", type=float, default=DEFAULT_BEFORE_NODE_PASS_DELAY_SECONDS)
    return parser.parse_args()


def prepare_config(args: argparse.Namespace) -> ReplayConfig:
    requirement_dir = Path(args.requirement_path).resolve()
    source_template_dir = Path(args.source_template or SOURCE_TEMPLATE_DIR).resolve()
    queue_path = Path(args.queue or (source_template_dir / "arc-replay" / "queue.json")).resolve()
    tasks_dir = Path(args.tasks_dir or (source_template_dir / "arc-replay" / "tasks")).resolve()

    target_template_value = args.output_dir or args.target_template or os.environ.get("ARCBENCH_TEMPLATE_DIR", "").strip() or "."
    target_template_dir = Path(target_template_value).resolve()

    arc_dir_value = args.arc_dir or args.artifacts_dir or os.environ.get("ARCBENCH_ARC_DIR", "").strip()
    arc_dir = Path(arc_dir_value).resolve() if arc_dir_value else target_template_dir / ".arc"

    submission_dir_value = args.submission_dir or os.environ.get("ARCBENCH_SUBMISSION_DIR", "").strip()
    submission_dir = Path(submission_dir_value).resolve() if submission_dir_value else None

    if not requirement_dir.is_dir():
        raise FileNotFoundError(f"Requirement directory not found: {requirement_dir}")
    snapshot_mode = (BUNDLE_ROOT / "snapshots" / "ticketbooking" / "manifest.json").is_file() or bool(os.environ.get("ARCBENCH_DEMO_SNAPSHOT_DIR", "").strip())
    if not source_template_dir.is_dir() and not snapshot_mode:
        raise FileNotFoundError(f"Source template directory not found: {source_template_dir}")
    if not (source_template_dir / ".git").exists() and not snapshot_mode:
        raise RuntimeError(f"Source template directory is missing git history: {source_template_dir}")
    if not queue_path.is_file() and not snapshot_mode:
        raise FileNotFoundError(f"Replay queue not found: {queue_path}")
    if not tasks_dir.is_dir() and not snapshot_mode:
        raise FileNotFoundError(f"Replay tasks directory not found: {tasks_dir}")
    if source_template_dir == target_template_dir and not snapshot_mode:
        raise RuntimeError("Source template dir and target template dir must be different directories.")

    return ReplayConfig(
        requirement_dir=requirement_dir,
        source_template_dir=source_template_dir,
        queue_path=queue_path,
        tasks_dir=tasks_dir,
        target_template_dir=target_template_dir,
        arc_dir=arc_dir,
        submission_dir=submission_dir,
        step_delay_seconds=float(args.step_delay),
        interface_delay_seconds=float(args.interface_delay),
        test_delay_seconds=float(args.test_delay),
        phase_delay_seconds=float(args.phase_delay),
        interface_group_delay_seconds=float(args.interface_group_delay),
        test_group_delay_seconds=float(args.test_group_delay),
        before_node_pass_delay_seconds=float(args.before_node_pass_delay),
    )


def _resolve_runtime_path(config: ReplayConfig, env_name: str, default_relative_path: str) -> Path:
    configured = os.environ.get(env_name, "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else config.target_template_dir / path
    return config.arc_dir / default_relative_path


def configure_runtime_paths(config: ReplayConfig) -> None:
    global CHECKPOINT_PATH, PAUSE_REQUEST_PATH, RESUME_REQUEST_PATH, RUNNER_EVENTS_PATH, TRACEABILITY_DIR, STATE_CHECKPOINTS_DIR

    CHECKPOINT_PATH = _resolve_runtime_path(config, "ARCBENCH_CHECKPOINT_PATH", "checkpoint.json")
    PAUSE_REQUEST_PATH = _resolve_runtime_path(config, "ARCBENCH_PAUSE_REQUEST_PATH", "pause.request.json")
    RESUME_REQUEST_PATH = _resolve_runtime_path(config, "ARCBENCH_RESUME_REQUEST_PATH", "resume.request.json")
    RUNNER_EVENTS_PATH = _resolve_runtime_path(config, "ARCBENCH_RUNNER_EVENTS_PATH", "runner-events.jsonl")
    TRACEABILITY_DIR = _resolve_runtime_path(config, "ARCBENCH_TRACEABILITY_DIR", "traceability")
    STATE_CHECKPOINTS_DIR = CHECKPOINT_PATH.parent / "state-checkpoints"


def append_runner_state(state: str, message: str) -> None:
    runtime = _runtime_state.get("runtime")
    if runtime is None:
        raise RuntimeError("Runtime is not initialized")
    events = runtime.events
    if state == "paused":
        events.mark_run_paused(message)
    elif state == "resumed":
        events.mark_run_resumed(message)
    elif state == "completed":
        events.mark_run_completed(message)
    elif state == "failed":
        events.mark_run_failed(message)
    else:
        events.mark_run_started(message)


def read_checkpoint() -> dict[str, Any]:
    default_payload = {
        "last_completed_index": 0,
        "completed": [],
        "paused": False,
        "pause_mode": "checkpoint",
        "manual_edit_session": None,
        "runtime_state_restored": False,
        "resume_patch_conflict": False,
    }
    if not CHECKPOINT_PATH.exists():
        return dict(default_payload)
    try:
        payload = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(default_payload)
    if not isinstance(payload, dict):
        return dict(default_payload)
    payload.setdefault("last_completed_index", 0)
    payload.setdefault("completed", [])
    payload.setdefault("paused", False)
    payload.setdefault("pause_mode", "checkpoint")
    payload.setdefault("manual_edit_session", None)
    payload.setdefault("runtime_state_restored", False)
    payload.setdefault("resume_patch_conflict", False)
    return payload


def write_checkpoint(payload: dict[str, Any]) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    last_error: OSError | None = None
    for delay in (0.0, 0.05, 0.1, 0.2, 0.5, 1.0):
        if delay > 0:
            time.sleep(delay)
        tmp_path = CHECKPOINT_PATH.with_suffix(f".json.{int(time.time() * 1000)}.tmp")
        try:
            tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp_path.replace(CHECKPOINT_PATH)
            return
        except OSError as exc:
            last_error = exc
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
    if last_error is not None:
        raise last_error


def state_checkpoint_dir(index: int) -> Path:
    normalized_index = max(int(index or 0), 0)
    return STATE_CHECKPOINTS_DIR / f"step-{normalized_index:04d}"


def current_head_commit(project_dir: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return None
    head = completed.stdout.strip()
    return head or None


def flush_traceability_checkpoint(runtime: AgentRuntime) -> None:
    runtime.paths.traceability_dir.mkdir(parents=True, exist_ok=True)


def save_runtime_state_checkpoint(
    runtime: AgentRuntime,
    checkpoint: dict[str, Any],
    *,
    step: "ReplayStep | None" = None,
) -> None:
    flush_traceability_checkpoint(runtime)
    completed_index = max(int(checkpoint.get("last_completed_index", 0) or 0), 0)
    target_dir = state_checkpoint_dir(completed_index)
    temp_dir = STATE_CHECKPOINTS_DIR / f".tmp-{completed_index:04d}-{int(time.time() * 1000)}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    for source_path, filename in (
        (runtime.paths.runner_events_path, "runner-events.jsonl"),
    ):
        if source_path.exists():
            shutil.copy2(source_path, temp_dir / filename)
    if runtime.paths.traceability_dir.is_dir():
        shutil.copytree(runtime.paths.traceability_dir, temp_dir / "traceability", dirs_exist_ok=True)

    metadata = {
        "last_completed_index": completed_index,
        "node_id": step.node_id if step else None,
        "phase": step.phase if step else None,
        "commit_message": step.commit_message if step else None,
        "workspace_commit_oid": current_head_commit(runtime.paths.project_dir),
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    }
    (temp_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    STATE_CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    backup_dir: Path | None = None
    if target_dir.exists():
        backup_dir = STATE_CHECKPOINTS_DIR / f".bak-{completed_index:04d}-{int(time.time() * 1000)}"
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        target_dir.replace(backup_dir)
    try:
        temp_dir.replace(target_dir)
    except Exception:
        if backup_dir and backup_dir.exists() and not target_dir.exists():
            backup_dir.replace(target_dir)
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if backup_dir and backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)


def should_pause() -> bool:
    return PAUSE_REQUEST_PATH.exists()


def clear_pause_requests() -> None:
    PAUSE_REQUEST_PATH.unlink(missing_ok=True)
    RESUME_REQUEST_PATH.unlink(missing_ok=True)


def maybe_pause(current_checkpoint: dict[str, Any]) -> None:
    if not should_pause():
        return
    paused_payload = dict(current_checkpoint)
    paused_payload["paused"] = True
    write_checkpoint(paused_payload)
    _checkpoint_state["payload"] = paused_payload
    append_runner_state("paused", "Generation paused")
    log("pause requested, checkpoint saved")
    raise SystemExit(0)


def pause(seconds: float, current_checkpoint: dict[str, Any] | None = None) -> None:
    deadline = time.monotonic() + max(seconds, 0.0)
    while True:
        if current_checkpoint is not None:
            maybe_pause(current_checkpoint)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


def _handle_sigterm(signum, frame) -> None:  # noqa: ARG001
    log("received SIGTERM, writing checkpoint and exiting")
    payload = _checkpoint_state.get("payload")
    if isinstance(payload, dict):
        write_checkpoint(payload)
    raise SystemExit(130)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_git(repo: Path, args: list[str], *, capture_bytes: bool = False) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(stderr or "git command failed")
    return completed.stdout if capture_bytes else completed.stdout


def list_source_commits(source_repo: Path) -> list[dict[str, str]]:
    output = run_git(source_repo, ["log", "--reverse", "--pretty=format:%H%x1f%s"]).decode("utf-8", "replace")
    commits: list[dict[str, str]] = []
    for line in output.splitlines():
        commit_oid, _, message = line.partition("\x1f")
        normalized_oid = commit_oid.strip()
        normalized_message = message.strip()
        if normalized_oid and normalized_message:
            commits.append({"oid": normalized_oid, "message": normalized_message})
    if not commits:
        raise RuntimeError(f"No commits found in source repo: {source_repo}")
    return commits


def build_commit_message_index(source_repo: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    duplicates: set[str] = set()
    for commit in list_source_commits(source_repo):
        message = commit["message"]
        if message in index:
            duplicates.add(message)
        index[message] = commit["oid"]
    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise RuntimeError(f"Replay commit messages must be unique in source repo, duplicates: {duplicate_list}")
    return index


def list_tracked_files(source_repo: Path, rev: str) -> list[str]:
    output = run_git(source_repo, ["ls-tree", "-r", "--name-only", rev]).decode("utf-8", "replace")
    return [line.strip() for line in output.splitlines() if line.strip()]


def extract_file_content(source_repo: Path, rev: str, rel_path: str) -> bytes:
    return run_git(source_repo, ["cat-file", "-p", f"{rev}:{rel_path}"], capture_bytes=True)


def reset_target_directory(target_dir: Path, preserve_names: set[str] | None = None) -> None:
    preserve_names = preserve_names or set()
    target_dir.mkdir(parents=True, exist_ok=True)
    for child in target_dir.iterdir():
        if child.name in preserve_names:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def reset_target_worktree(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for child in target_dir.iterdir():
        if child.name in {".git", ".arc", "requirements"}:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def ensure_requirements_directory(requirement_dir: Path, target_dir: Path) -> None:
    target_requirements_dir = target_dir / "requirements"
    if requirement_dir.resolve() == target_requirements_dir.resolve():
        target_requirements_dir.mkdir(parents=True, exist_ok=True)
        return
    if not requirement_dir.is_dir():
        target_requirements_dir.mkdir(parents=True, exist_ok=True)
        return
    shutil.copytree(requirement_dir, target_requirements_dir, dirs_exist_ok=True)


def sync_tree_from_commit(source_repo: Path, rev: str, target_dir: Path) -> None:
    tracked_files = list_tracked_files(source_repo, rev)
    reset_target_worktree(target_dir)
    for rel_path in tracked_files:
        if rel_path == "requirements" or rel_path.startswith("requirements/"):
            continue
        target_path = target_dir / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(extract_file_content(source_repo, rev, rel_path))


def empty_tree_oid(source_repo: Path) -> str:
    return run_git(source_repo, ["hash-object", "-t", "tree", "/dev/null"]).decode("utf-8", "replace").strip()


def build_patch_between_source_commits(source_repo: Path, from_rev: str, to_rev: str) -> bytes:
    normalized_from_rev = str(from_rev or "").strip() or DEMO_BASE_TREE_SENTINEL
    normalized_to_rev = str(to_rev or "").strip()
    if not normalized_to_rev:
        raise RuntimeError("Target source commit is required for patch replay")
    base_rev = empty_tree_oid(source_repo) if normalized_from_rev == DEMO_BASE_TREE_SENTINEL else normalized_from_rev
    return run_git(
        source_repo,
        ["diff", "--binary", "--full-index", "--find-renames", base_rev, normalized_to_rev],
        capture_bytes=True,
    )


def apply_patch_onto_workspace(target_repo: Path, patch_bytes: bytes) -> None:
    if not patch_bytes:
        return
    completed = subprocess.run(
        ["git", "apply", "--3way", "--index", "--whitespace=nowarn", "-"],
        cwd=str(target_repo),
        input=patch_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(stderr or "git apply failed")


def determine_resume_tree_mode(checkpoint: dict[str, Any]) -> str:
    return "patch_merge" if bool(checkpoint.get("runtime_state_restored")) else "full_sync"


def normalize_phase(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"design", "implement"}:
        raise ValueError(f"Unsupported replay phase: {value!r}")
    return normalized


def normalize_interface_type(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in set(INTERFACE_GROUP_ORDER):
        raise ValueError(f"Unsupported interface type: {value!r}")
    return normalized


def normalize_test_type(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized not in set(TEST_GROUP_ORDER):
        raise ValueError(f"Unsupported test type: {value!r}")
    return normalized


def interface_type_from_id(interface_id: str) -> str:
    prefix = str(interface_id or "").strip().split("-", 1)[0].upper()
    if prefix in set(INTERFACE_GROUP_ORDER):
        return prefix
    raise ValueError(f"Unable to infer interface type from id: {interface_id}")


def test_type_from_id(test_id: str) -> str:
    parts = [part.strip() for part in str(test_id or "").split("::") if part.strip()]
    if len(parts) >= 2 and parts[1] in set(TEST_GROUP_ORDER):
        return parts[1]
    raise ValueError(f"Unable to infer test type from id: {test_id}")


def group_interfaces_in_order(interfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    for group in INTERFACE_GROUP_ORDER:
        grouped.extend([item for item in interfaces if normalize_interface_type(item.get("type")) == group])
    return grouped


def group_tests_in_order(tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    for group in TEST_GROUP_ORDER:
        grouped.extend([item for item in tests if normalize_test_type(item.get("type")) == group])
    return grouped


def ordered_unique(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def parse_interface_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return dict(content)
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
    return {}


def update_interface_content_relations(interface: dict[str, Any]) -> None:
    content = parse_interface_content(interface.get("content"))
    if not content:
        content = {
            "interface_id": str(interface.get("interface_id") or "").strip(),
            "type": str(interface.get("type") or "").strip(),
        }
    content["callers"] = [str(item).strip() for item in interface.get("callers") or [] if str(item).strip()]
    content["callees"] = [str(item).strip() for item in interface.get("callees") or [] if str(item).strip()]
    if interface.get("file_path"):
        content.setdefault("file_path", str(interface.get("file_path")))
    interface["content"] = content


def build_frontend_api_interface(
    *,
    req_id: str,
    fe_interface_id: str,
    be_interface_id: str,
    callers: list[str],
) -> dict[str, Any]:
    for candidate_be_id, spec in FRONTEND_API_BRIDGES.items():
        if spec["fe_id"] != fe_interface_id:
            continue
        interface = {
            "interface_id": fe_interface_id,
            "req_ids": [req_id],
            "type": "API",
            "content": {
                "interface_id": fe_interface_id,
                "type": "API",
                "name": spec["name"],
                "description": spec["description"],
                "callers": ordered_unique(callers),
                "callees": [be_interface_id],
            },
            "file_path": spec["file_path"],
            "first_line": spec["first_line"],
            "implemented": False,
            "callers": ordered_unique(callers),
            "callees": [be_interface_id],
        }
        return interface
    raise ValueError(f"Unsupported frontend API interface bridge: {fe_interface_id}")


def resolve_backend_interface_for_frontend_api(fe_interface_id: str) -> str | None:
    normalized_fe_id = str(fe_interface_id or "").strip()
    for be_interface_id, spec in FRONTEND_API_BRIDGES.items():
        if spec["fe_id"] == normalized_fe_id:
            return be_interface_id
    return None


def normalize_step_interfaces(step: ReplayStep) -> None:
    interfaces_by_id: dict[str, dict[str, Any]] = {
        str(interface.get("interface_id") or "").strip(): interface
        for interface in step.interfaces
        if str(interface.get("interface_id") or "").strip()
    }
    fe_callers_by_id: dict[str, list[str]] = {}
    be_callee_by_fe_id: dict[str, str] = {}

    for interface in step.interfaces:
        interface_id = str(interface.get("interface_id") or "").strip()
        callers = ordered_unique([str(item).strip() for item in interface.get("callers") or []])
        callees = ordered_unique([str(item).strip() for item in interface.get("callees") or []])

        if normalize_interface_type(interface.get("type")) == "UI":
            rewritten_callees: list[str] = []
            for callee_id in callees:
                bridge = FRONTEND_API_BRIDGES.get(callee_id)
                if bridge is None:
                    if callee_id.startswith("API-FE-"):
                        rewritten_callees.append(callee_id)
                        fe_callers_by_id.setdefault(callee_id, []).append(interface_id)
                        be_interface_id = resolve_backend_interface_for_frontend_api(callee_id)
                        if be_interface_id:
                            be_callee_by_fe_id[callee_id] = be_interface_id
                    else:
                        rewritten_callees.append(callee_id)
                    continue
                fe_id = bridge["fe_id"]
                rewritten_callees.append(fe_id)
                fe_callers_by_id.setdefault(fe_id, []).append(interface_id)
                be_callee_by_fe_id[fe_id] = callee_id
            interface["callees"] = ordered_unique(rewritten_callees)
            update_interface_content_relations(interface)
            continue

        bridge = FRONTEND_API_BRIDGES.get(interface_id)
        if bridge is None:
            interface["callers"] = callers
            interface["callees"] = callees
            update_interface_content_relations(interface)
            continue

        fe_id = bridge["fe_id"]
        rewritten_callers = [fe_id if caller_id.startswith("UI-") else caller_id for caller_id in callers]
        interface["callers"] = ordered_unique(rewritten_callers)
        interface["callees"] = callees
        fe_callers_by_id.setdefault(fe_id, [])
        be_callee_by_fe_id[fe_id] = interface_id
        update_interface_content_relations(interface)

    referenced_fe_ids = ordered_unique(list(fe_callers_by_id) + list(be_callee_by_fe_id))
    for fe_id in referenced_fe_ids:
        callers = ordered_unique(fe_callers_by_id.get(fe_id, []))
        be_interface_id = be_callee_by_fe_id.get(fe_id, "")
        existing = interfaces_by_id.get(fe_id)
        if existing is None:
            existing = build_frontend_api_interface(
                req_id=step.node_id,
                fe_interface_id=fe_id,
                be_interface_id=be_interface_id,
                callers=callers,
            )
            step.interfaces.append(existing)
            interfaces_by_id[fe_id] = existing
        else:
            existing["req_ids"] = ordered_unique([*existing.get("req_ids", []), step.node_id])
            existing["callers"] = ordered_unique([*existing.get("callers", []), *callers])
            existing["callees"] = ordered_unique([*existing.get("callees", []), be_interface_id])
            update_interface_content_relations(existing)

    step.interfaces = group_interfaces_in_order(step.interfaces)


def normalize_step_tests(step: ReplayStep) -> None:
    frontend_api_by_ui_id: dict[str, list[str]] = {}
    for interface in step.interfaces:
        if normalize_interface_type(interface.get("type")) != "UI":
            continue
        frontend_api_by_ui_id[str(interface.get("interface_id") or "").strip()] = [
            callee_id
            for callee_id in (interface.get("callees") or [])
            if str(callee_id or "").strip().startswith("API-FE-")
        ]

    for test in step.tests:
        file_path = str(test.get("file_path") or "").replace("\\", "/")
        interface_ids = ordered_unique([str(item).strip() for item in test.get("interface_ids") or []])

        for interface_id in list(interface_ids):
            for fe_interface_id in frontend_api_by_ui_id.get(interface_id, []):
                interface_ids.append(fe_interface_id)

        if file_path.startswith("frontend/") or "/test-e2e/" in file_path:
            for be_interface_id, bridge in FRONTEND_API_BRIDGES.items():
                if be_interface_id in interface_ids:
                    interface_ids.append(bridge["fe_id"])

        test["interface_ids"] = ordered_unique(interface_ids)


def normalize_step_implemented_interfaces(step: ReplayStep) -> None:
    normalized_ids = ordered_unique(step.implemented_interface_ids)
    for interface_id in list(normalized_ids):
        bridge = FRONTEND_API_BRIDGES.get(interface_id)
        if bridge is None:
            continue
        normalized_ids.append(bridge["fe_id"])
    step.implemented_interface_ids = ordered_unique(normalized_ids)


def normalize_step(step: ReplayStep) -> ReplayStep:
    normalize_step_interfaces(step)
    normalize_step_tests(step)
    normalize_step_implemented_interfaces(step)
    return step


def extract_commit_message(task_payload: dict[str, Any]) -> str:
    for call in task_payload.get("sdk_calls", []):
        if not isinstance(call, dict):
            continue
        if str(call.get("sdk") or "").strip() != "runtime.git.commit":
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        message = str(params.get("message") or "").strip()
        if message:
            return message
    raise RuntimeError("Task metadata is missing runtime.git.commit message")


def extract_design_interfaces(task_payload: dict[str, Any]) -> list[dict[str, Any]]:
    interfaces: list[dict[str, Any]] = []
    for call in task_payload.get("sdk_calls", []):
        if not isinstance(call, dict):
            continue
        if str(call.get("sdk") or "").strip() != "runtime.traceability.upsert_interface":
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        if str(params.get("interface_id") or "").strip():
            interfaces.append(dict(params))
    return interfaces


def extract_design_tests(task_payload: dict[str, Any]) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    for call in task_payload.get("sdk_calls", []):
        if not isinstance(call, dict):
            continue
        if str(call.get("sdk") or "").strip() != "runtime.traceability.upsert_test":
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        if str(params.get("test_id") or "").strip():
            tests.append(dict(params))
    return tests


def extract_implemented_interface_ids(task_payload: dict[str, Any]) -> list[str]:
    interface_ids: list[str] = []
    for call in task_payload.get("sdk_calls", []):
        if not isinstance(call, dict):
            continue
        if str(call.get("sdk") or "").strip() != "runtime.traceability.set_interface_implemented":
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        interface_id = str(params.get("interface_id") or "").strip()
        if interface_id:
            interface_ids.append(interface_id)
    return interface_ids


def extract_passed_test_ids(task_payload: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for call in task_payload.get("sdk_calls", []):
        if not isinstance(call, dict):
            continue
        if str(call.get("sdk") or "").strip() != "runtime.traceability.set_test_pass_statuses":
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        mapping = params.get("status_by_test_id")
        if not isinstance(mapping, dict):
            continue
        for test_id, passed in mapping.items():
            normalized_test_id = str(test_id or "").strip()
            if not normalized_test_id or passed is not True or normalized_test_id in seen:
                continue
            seen.add(normalized_test_id)
            ordered.append(normalized_test_id)
    return ordered


def load_steps(config: ReplayConfig) -> list[ReplayStep]:
    queue_payload = load_json(config.queue_path)
    if not isinstance(queue_payload, list):
        raise RuntimeError(f"Replay queue must be a JSON array: {config.queue_path}")

    commit_index = build_commit_message_index(config.source_template_dir)
    steps: list[ReplayStep] = []
    for index, item in enumerate(queue_payload, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Replay queue item #{index} must be an object")
        node_id = str(item.get("node_id") or "").strip()
        phase = normalize_phase(item.get("phase"))
        if not node_id:
            raise RuntimeError(f"Replay queue item #{index} is missing node_id")
        task_path = (config.tasks_dir / f"{node_id}.{phase}.json").resolve()
        if not task_path.is_file():
            raise FileNotFoundError(f"Replay task not found: {task_path}")
        task_payload = load_json(task_path)
        if not isinstance(task_payload, dict):
            raise RuntimeError(f"Replay task must be a JSON object: {task_path}")
        commit_message = extract_commit_message(task_payload)
        source_commit = commit_index.get(commit_message)
        if not source_commit:
            raise RuntimeError(f"Unable to locate source commit for replay message: {commit_message}")
        interfaces = extract_design_interfaces(task_payload)
        tests = extract_design_tests(task_payload)
        steps.append(
            normalize_step(
                ReplayStep(
                    index=index,
                    node_id=node_id,
                    phase=phase,
                    task_path=task_path,
                    commit_message=commit_message,
                    source_commit=source_commit,
                    interfaces=interfaces,
                    tests=tests,
                    implemented_interface_ids=extract_implemented_interface_ids(task_payload),
                    passed_test_ids=extract_passed_test_ids(task_payload),
                )
            )
        )
    return steps


def current_completed_entries(previous_checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    completed = previous_checkpoint.get("completed")
    return list(completed) if isinstance(completed, list) else []


def build_placeholder_requirement_tree(steps: list[ReplayStep]) -> list[dict[str, Any]]:
    node_ids = sorted({step.node_id for step in steps}, key=lambda value: (value.count("."), value))
    children_by_parent: dict[str, list[str]] = {}
    for node_id in node_ids:
        parent_id = None if node_id == "ROOT" else node_id.rsplit(".", 1)[0]
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(node_id)
    requirements: list[dict[str, Any]] = []
    for node_id in node_ids:
        parent_id = None if node_id == "ROOT" else node_id.rsplit(".", 1)[0]
        requirements.append(
            {
                "req_id": node_id,
                "name": node_id,
                "description": f"Replay seed for {node_id}",
                "parent_id": parent_id,
                "children_ids": children_by_parent.get(node_id, []),
            }
        )
    return requirements


def ensure_requirements_seed(runtime: AgentRuntime, steps: list[ReplayStep]) -> None:
    existing = runtime.traceability.list_requirements()
    if existing:
        return
    for requirement in build_placeholder_requirement_tree(steps):
        runtime.traceability.upsert_requirement(
            req_id=requirement["req_id"],
            name=requirement["name"],
            description=requirement["description"],
            parent_id=requirement["parent_id"],
            children_ids=requirement["children_ids"],
            visual_reference=[],
            scenarios=[],
            dependencies=[],
        )


def write_preview_ready(arc_dir: Path) -> None:
    arc_dir.mkdir(parents=True, exist_ok=True)
    marker_path = arc_dir / "preview-ready.json"
    marker_path.write_text(
        json.dumps({"ready": True, "reason": "demo-agent replay completed"}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def ensure_target_repo(runtime: AgentRuntime, config: ReplayConfig) -> None:
    reset_target_directory(config.target_template_dir, preserve_names={"requirements"})
    ensure_requirements_directory(config.requirement_dir, config.target_template_dir)
    runtime.git.ensure_repo(create_initial_commit=False)


def maybe_delay(enabled: bool, seconds: float, checkpoint: dict[str, Any] | None) -> None:
    if not enabled or seconds <= 0:
        return
    pause(seconds, checkpoint)


def mark_node_state(runtime: AgentRuntime, node_id: str, state: str) -> None:
    runtime.traceability.upsert_node_state(node_id, state)


def mark_requirement_events(runtime: AgentRuntime, node_id: str, phase: str) -> None:
    if phase == "design":
        runtime.events.mark_design_done(node_id, f"{node_id} design completed")
    elif phase == "implement":
        runtime.events.mark_implementation_done(node_id, f"{node_id} implementation completed")
    else:
        raise ValueError(f"Unsupported event phase: {phase}")


def mark_requirement_passed(runtime: AgentRuntime, node_id: str) -> None:
    runtime.events.mark_test_passed(node_id, f"{node_id} tests passed")


def upsert_design_interfaces(
    runtime: AgentRuntime,
    step: ReplayStep,
    checkpoint: dict[str, Any] | None,
    *,
    enable_delays: bool,
    interface_delay_seconds: float,
    interface_group_delay_seconds: float,
) -> None:
    previous_group: str | None = None
    for interface in group_interfaces_in_order(step.interfaces):
        current_group = normalize_interface_type(interface.get("type"))
        if previous_group is not None and current_group != previous_group:
            maybe_delay(enable_delays, interface_group_delay_seconds, checkpoint)
        interface_id = str(interface.get("interface_id") or "").strip()
        existing = runtime.traceability.get_interface(interface_id)
        req_ids = ordered_unique([str(item).strip() for item in (interface.get("req_ids") or []) if str(item).strip()])
        callers = ordered_unique([str(item).strip() for item in (interface.get("callers") or []) if str(item).strip()])
        callees = ordered_unique([str(item).strip() for item in (interface.get("callees") or []) if str(item).strip()])
        if existing:
            req_ids = ordered_unique([*(existing.get("req_ids") or []), *req_ids])
            callers = ordered_unique([*(existing.get("callers") or []), *callers])
            callees = ordered_unique([*(existing.get("callees") or []), *callees])
        runtime.traceability.upsert_interface(
            interface_id=interface_id,
            req_ids=req_ids,
            type=current_group,
            content=(
                str(interface.get("content") or "").strip()
                if isinstance(interface.get("content"), str)
                else json.dumps(interface.get("content") or {}, ensure_ascii=False)
            ),
            file_path=str(interface.get("file_path") or "").strip() or None,
            first_line=str(interface.get("first_line") or "").strip() or None,
            implemented=bool(interface.get("implemented")) or bool(existing and existing.get("implemented")),
            callers=callers,
            callees=callees,
        )
        maybe_delay(enable_delays, interface_delay_seconds, checkpoint)
        previous_group = current_group


def upsert_design_tests(
    runtime: AgentRuntime,
    step: ReplayStep,
    checkpoint: dict[str, Any] | None,
    *,
    enable_delays: bool,
    test_delay_seconds: float,
    test_group_delay_seconds: float,
) -> None:
    previous_group: str | None = None
    for test in group_tests_in_order(step.tests):
        current_group = normalize_test_type(test.get("type"))
        if previous_group is not None and current_group != previous_group:
            maybe_delay(enable_delays, test_group_delay_seconds, checkpoint)
        runtime.traceability.upsert_test(
            test_id=str(test.get("test_id") or "").strip(),
            req_id=str(test.get("req_id") or step.node_id).strip(),
            type=current_group,
            file_path=str(test.get("file_path") or "").strip() or None,
            first_line=str(test.get("first_line") or "").strip() or None,
            interface_ids=[str(item).strip() for item in (test.get("interface_ids") or []) if str(item).strip()],
            passed=None,
        )
        maybe_delay(enable_delays, test_delay_seconds, checkpoint)
        previous_group = current_group


def mark_implemented_interfaces(
    runtime: AgentRuntime,
    step: ReplayStep,
    checkpoint: dict[str, Any] | None,
    *,
    enable_delays: bool,
    interface_delay_seconds: float,
) -> None:
    grouped_ids: dict[str, list[str]] = {group: [] for group in INTERFACE_GROUP_ORDER}
    for interface_id in step.implemented_interface_ids:
        interface = runtime.traceability.get_interface(interface_id)
        interface_type = (
            normalize_interface_type(interface.get("type"))
            if interface and interface.get("type")
            else interface_type_from_id(interface_id)
        )
        grouped_ids.setdefault(interface_type, []).append(interface_id)
    for group in INTERFACE_GROUP_ORDER:
        for interface_id in grouped_ids.get(group, []):
            runtime.traceability.set_interface_implemented(interface_id, True, emit_event=False)
            maybe_delay(enable_delays, interface_delay_seconds, checkpoint)


def mark_passed_tests(
    runtime: AgentRuntime,
    step: ReplayStep,
    checkpoint: dict[str, Any] | None,
    *,
    enable_delays: bool,
    test_delay_seconds: float,
    test_group_delay_seconds: float,
) -> None:
    grouped_ids: dict[str, list[str]] = {group: [] for group in TEST_GROUP_ORDER}
    for test_id in step.passed_test_ids:
        test = runtime.traceability.get_test(test_id)
        test_type = normalize_test_type(test.get("type")) if test and test.get("type") else test_type_from_id(test_id)
        grouped_ids.setdefault(test_type, []).append(test_id)
    previous_group: str | None = None
    for group in TEST_GROUP_ORDER:
        test_ids = grouped_ids.get(group, [])
        if not test_ids:
            continue
        if previous_group is not None:
            maybe_delay(enable_delays, test_group_delay_seconds, checkpoint)
        for test_id in test_ids:
            runtime.traceability.set_test_pass_status(test_id, True)
            maybe_delay(enable_delays, test_delay_seconds, checkpoint)
        previous_group = group


def pause_on_resume_patch_conflict(
    runtime: AgentRuntime,
    step: ReplayStep,
    checkpoint: dict[str, Any] | None,
    *,
    patch_from_rev: str,
    error_message: str,
) -> None:
    conflict_checkpoint = dict(checkpoint or read_checkpoint())
    conflict_checkpoint["paused"] = False
    conflict_checkpoint["pause_mode"] = "manual_edit"
    conflict_checkpoint["runtime_state_restored"] = True
    conflict_checkpoint["resume_patch_conflict"] = True
    conflict_checkpoint["current_node_id"] = step.node_id
    conflict_checkpoint["current_phase"] = step.phase
    conflict_checkpoint["manual_edit_session"] = {
        "base_completed_index": int(conflict_checkpoint.get("last_completed_index", 0) or 0),
        "current_node_id": step.node_id,
        "current_phase": step.phase,
        "base_source_commit": patch_from_rev or DEMO_BASE_TREE_SENTINEL,
        "has_workspace_changes": False,
        "has_traceability_changes": False,
        "pending_test_creations": [],
        "pending_commit_message": f"{step.node_id} ({step.phase}): user edit",
    }
    write_checkpoint(conflict_checkpoint)
    _checkpoint_state["payload"] = conflict_checkpoint
    runtime.events._emit_traceability_event(  # noqa: SLF001
        {
            "type": "resume_patch_conflict",
            "node_id": step.node_id,
            "phase": step.phase,
            "message": error_message,
        }
    )
    runtime.events._emit_refresh_signal(  # noqa: SLF001
        reason="resume_patch_conflict",
        submission=True,
        logs=True,
        commit_history=True,
        traceability_selected=True,
        traceability_all=True,
        preview=True,
    )
    append_runner_state("paused", "Replay patch merge conflict detected")


def replay_step(
    runtime: AgentRuntime,
    config: ReplayConfig,
    step: ReplayStep,
    checkpoint: dict[str, Any] | None,
    *,
    enable_delays: bool,
    commit_changes: bool,
    tree_mode: str,
    patch_from_rev: str | None = None,
) -> None:
    if tree_mode == "full_sync":
        sync_tree_from_commit(config.source_template_dir, step.source_commit, config.target_template_dir)
    elif tree_mode == "patch_merge":
        patch_base_rev = str(patch_from_rev or DEMO_BASE_TREE_SENTINEL)
        patch_bytes = build_patch_between_source_commits(
            config.source_template_dir,
            patch_base_rev,
            step.source_commit,
        )
        try:
            apply_patch_onto_workspace(config.target_template_dir, patch_bytes)
        except Exception as exc:  # noqa: BLE001
            try:
                run_git(config.target_template_dir, ["reset", "--hard", "HEAD"], capture_bytes=True)
                run_git(config.target_template_dir, ["clean", "-fd"], capture_bytes=True)
            except Exception:  # noqa: BLE001
                pass
            pause_on_resume_patch_conflict(
                runtime,
                step,
                checkpoint,
                patch_from_rev=patch_base_rev,
                error_message=str(exc),
            )
            raise ResumePatchConflictError(str(exc)) from exc
    else:
        raise RuntimeError(f"Unsupported replay tree mode: {tree_mode}")

    ensure_requirements_directory(config.requirement_dir, config.target_template_dir)

    if step.phase == "design":
        mark_node_state(runtime, step.node_id, "DESIGNED")
        mark_requirement_events(runtime, step.node_id, "design")
        maybe_delay(enable_delays, config.phase_delay_seconds, checkpoint)
        upsert_design_interfaces(
            runtime,
            step,
            checkpoint,
            enable_delays=enable_delays,
            interface_delay_seconds=config.interface_delay_seconds,
            interface_group_delay_seconds=config.interface_group_delay_seconds,
        )
        maybe_delay(enable_delays, config.phase_delay_seconds, checkpoint)
        upsert_design_tests(
            runtime,
            step,
            checkpoint,
            enable_delays=enable_delays,
            test_delay_seconds=config.test_delay_seconds,
            test_group_delay_seconds=config.test_group_delay_seconds,
        )
    else:
        mark_node_state(runtime, step.node_id, "IMPLEMENTED")
        mark_requirement_events(runtime, step.node_id, "implement")
        maybe_delay(enable_delays, config.phase_delay_seconds, checkpoint)
        mark_implemented_interfaces(
            runtime,
            step,
            checkpoint,
            enable_delays=enable_delays,
            interface_delay_seconds=config.interface_delay_seconds,
        )
        mark_passed_tests(
            runtime,
            step,
            checkpoint,
            enable_delays=enable_delays,
            test_delay_seconds=config.test_delay_seconds,
            test_group_delay_seconds=config.test_group_delay_seconds,
        )
        maybe_delay(enable_delays, config.before_node_pass_delay_seconds, checkpoint)
        mark_node_state(runtime, step.node_id, "PASSED")
        mark_requirement_passed(runtime, step.node_id)

    if commit_changes:
        runtime.git.commit(step.commit_message)
    maybe_delay(enable_delays, config.step_delay_seconds, checkpoint)


def checkpoint_payload(previous_checkpoint: dict[str, Any], step: ReplayStep) -> dict[str, Any]:
    completed = current_completed_entries(previous_checkpoint)
    completed.append(
        {
            "index": step.index,
            "node_id": step.node_id,
            "phase": step.phase,
            "task_path": str(step.task_path),
            "source_commit": step.source_commit,
            "commit_message": step.commit_message,
        }
    )
    return {
        "last_completed_index": step.index,
        "completed": completed,
        "paused": False,
    }


def rebuild_to_checkpoint(
    runtime: AgentRuntime,
    config: ReplayConfig,
    steps: list[ReplayStep],
    completed_count: int,
) -> None:
    raise RuntimeError(
        "demo-agent replay-based checkpoint rebuild has been removed; restore workspace state from saved checkpoints instead"
    )


def main() -> int:
    args = parse_args()
    config = prepare_config(args)
    configure_runtime_paths(config)

    # Production demo bundles use immutable, pre-expanded snapshots. Keep the
    # legacy Git replay path below as a build-time compatibility fallback.
    snapshot_manifest = BUNDLE_ROOT / "snapshots" / "ticketbooking" / "manifest.json"
    configured_snapshot_dir = os.environ.get("ARCBENCH_DEMO_SNAPSHOT_DIR", "").strip()
    if snapshot_manifest.is_file() or configured_snapshot_dir:
        from snapshot_replay import run_snapshot_replay

        return run_snapshot_replay(
            bundle_root=BUNDLE_ROOT,
            target_dir=config.target_template_dir,
            arc_dir=config.arc_dir,
            requirement_dir=config.requirement_dir,
        )

    log(f"bundle root: {BUNDLE_ROOT}")
    log(f"source template: {config.source_template_dir}")
    log(f"queue path: {config.queue_path}")
    log(f"tasks dir: {config.tasks_dir}")
    log(f"target template dir: {config.target_template_dir}")
    log(f"arc dir: {config.arc_dir}")
    log(f"submission dir: {config.submission_dir or '<missing>'}")
    log(f"runner events: {RUNNER_EVENTS_PATH}")
    log(f"traceability dir: {TRACEABILITY_DIR}")

    signal.signal(signal.SIGTERM, _handle_sigterm)

    runtime = AgentRuntime.from_env(
        project_dir=str(config.target_template_dir),
        runner_events_path=str(RUNNER_EVENTS_PATH),
        traceability_dir=str(TRACEABILITY_DIR),
    )
    _runtime_state["runtime"] = runtime
    steps = load_steps(config)
    checkpoint = read_checkpoint()
    last_completed_index = int(checkpoint.get("last_completed_index", 0) or 0)
    runtime_state_restored = bool(checkpoint.get("runtime_state_restored"))
    resume_tree_mode = determine_resume_tree_mode(checkpoint)

    try:
        if runtime_state_restored:
            log("detected pre-restored runtime state; preserving workspace/template and git history")
        else:
            ensure_target_repo(runtime, config)
        ensure_requirements_directory(config.requirement_dir, config.target_template_dir)
        runtime.traceability.init_db(reset=False)
        ensure_requirements_seed(runtime, steps)

        if checkpoint.get("paused"):
            checkpoint["paused"] = False
            write_checkpoint(checkpoint)
            append_runner_state("resumed", "Generation resumed")
            _checkpoint_state["payload"] = checkpoint
            log("cleared paused checkpoint state on resume")
        else:
            append_runner_state("running", "Demo replay started")
            _checkpoint_state["payload"] = checkpoint
            write_checkpoint(checkpoint)
            save_runtime_state_checkpoint(runtime, checkpoint)

        if resume_tree_mode == "patch_merge":
            checkpoint["runtime_state_restored"] = False
            checkpoint["resume_patch_conflict"] = False
            write_checkpoint(checkpoint)
            if last_completed_index > 0:
                log(f"skipping checkpoint rebuild because runtime state is already restored through step {last_completed_index}")
        elif last_completed_index > 0:
            raise RuntimeError(
                f"checkpointed runtime state is required to resume through step {last_completed_index}, but it was not restored"
            )

        for step in steps[last_completed_index:]:
            patch_from_rev = None
            if resume_tree_mode == "patch_merge":
                patch_from_rev = (
                    steps[step.index - 2].source_commit
                    if step.index > 1
                    else DEMO_BASE_TREE_SENTINEL
                )
            replay_step(
                runtime,
                config,
                step,
                checkpoint,
                enable_delays=True,
                commit_changes=True,
                tree_mode=resume_tree_mode,
                patch_from_rev=patch_from_rev,
            )
            checkpoint = checkpoint_payload(checkpoint, step)
            _checkpoint_state["payload"] = checkpoint
            write_checkpoint(checkpoint)
            save_runtime_state_checkpoint(runtime, checkpoint, step=step)
            maybe_pause(checkpoint)

        clear_pause_requests()
        write_preview_ready(config.arc_dir)
        append_runner_state("completed", "Demo replay completed")
        log("demo-agent replay finished successfully")
        return 0
    except ResumePatchConflictError as exc:
        log(f"demo-agent replay paused after patch conflict: {exc}")
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        append_runner_state("failed", str(exc))
        log(f"demo-agent replay failed: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())

"""ARC-Bench lean agent: template copy, requirement digest, unit pipeline, finalize.

    python3 main.py <requirements_dir> --output-dir <output> --type web

Pipeline (docs/lean-design.md, "Orchestration"): copy the template, start the npm
install in the background, set up the runtime (git/traceability/events), digest the
requirements, then run a foundation unit, one unit per requirement module and, when the
last check failed, a final fix unit.  Every unit gets a fresh context behind the same
system prompt.  Finalize always runs once the template is in place: final check, reset
to the last passing commit when the final check fails, cleanup, events, final commit and
.arc/agent/summary.json.  ``main()`` returns 0 on every path except KeyboardInterrupt.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from openai import AuthenticationError, BadRequestError, OpenAI, PermissionDeniedError

import agent_prompt
from agent_tools import TOOLS, ToolContext, clip, dispatch, file_index
from lean_checks import CheckResult, NpmBootstrap, cleanup_output, run_check
from prompt_cache import PromptCachePolicy, UsageRecorder
from run_budget import RunBudget
from spec_digest import build_digest

try:  # the platform installs it; without it the run degrades to "no runtime"
    from arcbench_agent_runtime import AgentRuntime
except ImportError:  # pragma: no cover - exercised only on broken installs
    AgentRuntime = None  # type: ignore[assignment,misc]


TEMPLATE_DIR = Path(__file__).resolve().parent / "template"
COPY_SKIP_NAMES = frozenset({"node_modules", "dist", ".arc-test-db", "template.yaml"})
COPY_SKIP_PATTERNS = ("*.db",)

DEFAULT_MODEL = "deepseek-v4-flash"
CLIENT_TIMEOUT = 300.0
CLIENT_MAX_RETRIES = 3

DEFAULT_UNIT_MAX_STEPS = 48     # the step caps bound a unit; the budget is a runaway guard
DEFAULT_FOUNDATION_MAX_STEPS = 64
DEFAULT_FIX_STEPS = 16
DEFAULT_CONTEXT_CHARS = 300_000  # ~95k tokens; the model's window is 1M
DEFAULT_RETRY_DELAY = 5.0

FOUNDATION_WEIGHT = 2.8
WEIGHT_MIN, WEIGHT_MAX = 0.6, 1.6  # module unit weight: unit text / mean, clamped
WARN_FRACTION = 0.75
KEEP_GROUPS = 3                 # assistant/tool groups kept verbatim by a compaction
AGGRESSIVE_KEEP_GROUPS = 1
AGGRESSIVE_CLIP = 1500
TRIM_KEEP_GROUPS = 3            # History.trim leaves the last groups verbatim
TRIM_ARG_CHARS = 400            # older write/edit payloads above this are elided
OLD_REASONING_CHARS = 3000      # older reasoning_content is clipped to this (never removed)
TRIM_ENOUGH = 0.75              # a trim that gets the history under 75% of the threshold replaces a compaction
ELIDED_NOTE = "<{chars} chars elided; re-read the file before editing it>"
ESTIMATE_UNITS = 3              # the cost of one response: mean over the last whole units
ESTIMATE_MIN_REQUESTS = 3
CHARS_PER_TOKEN = 3.2
CONTEXT_GROWTH = 1.7            # before measurements: a response costs 1.7x the opening prompt
DEFAULT_RESPONSE_SECONDS = 40.0  # a response with its tool calls, before measurements
MIN_ALLOWANCE_STEPS = 3
IDLE_MIN_RESPONSES = 6          # idle note after max(6, 30% of the allowance) responses
IDLE_FRACTION = 0.3
MAX_CONSECUTIVE_FAILURES = 3
FINALIZE_SECONDS = 240.0        # time kept free for finalize after the fix unit
MIN_FIX_UNIT_SECONDS = 60.0
TOOL_RESULT_LIMIT = 6000
LOG_LINE_LIMIT = 160

WARN_NOTE = "Budget nearly spent: finish the current slice, run check, then unit_done."
NUDGE_NOTE = ("You replied without calling any tool. Nobody will answer: call tools to "
              "continue, or call unit_done if this unit is finished.")
CONTINUE_NOTE = ("The check after this unit FAILED. Fix the problems below with minimal, "
                 "targeted changes (no new features), run `check` until it passes, then call "
                 "`unit_done` again.\n\n")
BAD_REQUEST_END = "request rejected (bad request)"
QUOTA_WORDS = ("quota", "insufficient", "balance")
FINGERPRINT_PATHS = ("frontend/src", "backend/src", "frontend/package.json",
                     "backend/package.json", "frontend/index.html",
                     "frontend/vite.config.ts", "frontend/vite.config.js")


# --------------------------------------------------------------------------- logging

def log(message: str) -> None:
    """One progress line on stdout, at most LOG_LINE_LIMIT characters."""
    print(_one_line(f"[agent] {message}"), flush=True)


def log_error(output_dir: Path | None, message: str, error: BaseException | None = None) -> None:
    """stderr + <output>/.arc/agent/error.log; never raises."""
    detail = f"{message}: {type(error).__name__}: {error}" if error is not None else message
    try:
        print(_one_line(f"[agent] ERROR {detail}"), file=sys.stderr, flush=True)
    except Exception:
        pass
    if output_dir is None:
        return
    try:
        path = Path(output_dir) / ".arc" / "agent" / "error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        text = f"[{stamp}] {detail}\n"
        if error is not None and error.__traceback__ is not None:
            text += "".join(traceback.format_exception(type(error), error, error.__traceback__))
        with path.open("a", encoding="utf-8") as stream:
            stream.write(text)
    except Exception:
        pass


def _one_line(text: Any, limit: int = LOG_LINE_LIMIT) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[:limit - 3] + "..."


def _human(value: float | int | None) -> str:
    if value is None:
        return "inf"
    number = float(value)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if number >= 1_000:
        return f"{number / 1_000:.0f}k"
    return str(int(number))


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(float(raw)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value >= 0 else default


# --------------------------------------------------------------------------- CLI / template

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ARC-Bench agent.")
    parser.add_argument("requirement_path", nargs="?",
                        default=os.environ.get("ARCBENCH_TASK_DIR", "requirements"))
    parser.add_argument("--output-dir", default=os.environ.get("ARCBENCH_OUTPUT_DIR", "."))
    parser.add_argument("--type", dest="task_type", default=os.environ.get("ARCBENCH_TASK_TYPE", "web"))
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        log(f"ignoring unknown arguments: {' '.join(unknown)}")
    return args


def _skip_copy(name: str) -> bool:
    return name in COPY_SKIP_NAMES or any(fnmatch.fnmatch(name, p) for p in COPY_SKIP_PATTERNS)


def copy_template(template_dir: Path, output_dir: Path) -> None:
    """Copy the template over output_dir (merge), skipping build/install/db artefacts."""
    template_dir = Path(template_dir)
    output_dir = Path(output_dir)
    if not template_dir.is_dir():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if _skip_copy(name)}

    for source in sorted(template_dir.iterdir()):
        if _skip_copy(source.name):
            continue
        destination = output_dir / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore)
        elif source.is_file():
            shutil.copy2(source, destination)


def source_fingerprint(root: Path) -> str:
    """Hash of the sources that decide build/start (frontend/src, backend/src, package.json...)."""
    root = Path(root)
    digest = hashlib.sha256()
    for relative in FINGERPRINT_PATHS:
        path = root / relative
        if path.is_file():
            files = [path]
        elif path.is_dir():
            files = sorted(p for p in path.rglob("*")
                           if p.is_file() and "node_modules" not in p.relative_to(root).parts)
        else:
            continue
        for item in files:
            digest.update(item.relative_to(root).as_posix().encode("utf-8") + b"\0")
            try:
                digest.update(hashlib.sha256(item.read_bytes()).digest())
            except OSError:
                digest.update(b"?")
    return digest.hexdigest()


# --------------------------------------------------------------------------- wire protocol

def selected_wire_api() -> str:
    """Chat Completions by default; OPENAI_WIRE_API=responses selects the Responses API."""
    value = os.environ.get("OPENAI_WIRE_API", "chat").strip().lower()
    if value in {"responses", "response"}:
        return "responses"
    if value in {"chat", "chat.completions", "completions"}:
        return "chat"
    raise ValueError("OPENAI_WIRE_API must be 'responses' or 'chat'")


def is_deepseek_model(model: str) -> bool:
    """Recognize direct or provider-prefixed DeepSeek model names."""
    return model.rsplit("/", 1)[-1].lower().startswith("deepseek-")


def deepseek_thinking_type() -> str:
    """Allow disabling DeepSeek thinking without changing the wire protocol."""
    value = os.environ.get("DEEPSEEK_THINKING", "enabled").strip().lower()
    if value in {"enabled", "true", "1", "on"}:
        return "enabled"
    if value in {"disabled", "false", "0", "off"}:
        return "disabled"
    raise ValueError("DEEPSEEK_THINKING must be 'enabled' or 'disabled'")


def responses_tools() -> list[dict[str, Any]]:
    """Convert the Chat Completions tool declarations to Responses declarations."""
    converted: list[dict[str, Any]] = []
    for tool in TOOLS:
        function = tool.get("function", {})
        converted.append({
            "type": "function",
            "name": function.get("name"),
            "description": function.get("description", ""),
            "parameters": function.get("parameters", {"type": "object", "properties": {}}),
            # Optional fields stay optional; Responses would otherwise default to strict.
            "strict": False,
        })
    return converted


def response_item_value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def response_function_calls(response: Any) -> list[Any]:
    output = response_item_value(response, "output", []) or []
    return [item for item in output if response_item_value(item, "type") == "function_call"]


def build_request(model: str, wire_api: str, messages: list[dict[str, Any]], *,
                  cache_fields: dict[str, Any] | None = None,
                  timeout: float | None = None) -> dict[str, Any]:
    """Keyword arguments for chat.completions.create / responses.create."""
    request: dict[str, Any] = {"model": model}
    if timeout is not None:
        request["timeout"] = timeout
    deepseek_chat = wire_api == "chat" and is_deepseek_model(model)
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "low" if deepseek_chat else "").strip()
    if wire_api == "responses":
        request.update(input=messages, tools=responses_tools(), store=False,
                       include=["reasoning.encrypted_content"])
        request.update(cache_fields or {})
        if effort:
            request["reasoning"] = {"effort": effort}
    else:
        request.update(messages=messages, tools=TOOLS)
        request.update(cache_fields or {})
        if deepseek_chat:
            try:
                thinking = deepseek_thinking_type()
            except ValueError:
                thinking = "enabled"
            request["extra_body"] = {"thinking": {"type": thinking}}
        if effort:
            request["reasoning_effort"] = effort
    return request


def classify_api_error(error: BaseException) -> str:
    """"fatal" (stop all model work), "bad_request" (our request) or "transient"."""
    status = getattr(error, "status_code", None)
    text = " ".join(str(part) for part in (error, getattr(error, "code", None),
                                           getattr(error, "body", None)) if part).lower()
    if isinstance(error, (AuthenticationError, PermissionDeniedError)) or status in (401, 402, 403):
        return "fatal"
    if status == 429 and any(word in text for word in QUOTA_WORDS):
        return "fatal"
    if isinstance(error, BadRequestError) or status in (400, 413):
        return "bad_request"
    return "transient"


def message_size(message: Any) -> int:
    return len(json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str))


def _as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump(exclude_none=True)
    return {k: v for k, v in vars(item).items() if v is not None}


def _shrink_arguments(arguments: Any, limit: int) -> Any:
    if not isinstance(arguments, str) or len(arguments) <= limit:
        return arguments
    try:
        parsed = json.loads(arguments)
    except ValueError:
        return json.dumps({"omitted": f"{len(arguments)} chars of arguments"})
    if isinstance(parsed, dict):
        parsed = {key: (f"<{len(value)} chars omitted>" if isinstance(value, str) and len(value) > 200
                        else value) for key, value in parsed.items()}
    text = json.dumps(parsed, ensure_ascii=False)
    return text if len(text) <= limit else json.dumps({"omitted": f"{len(arguments)} chars of arguments"})


def shrink_message(message: dict[str, Any], limit: int) -> dict[str, Any]:
    """Copy of a history item with long tool outputs/arguments/texts cut (valid JSON kept)."""
    item = dict(message)
    for key in ("content", "output", "reasoning_content"):
        if isinstance(item.get(key), str) and len(item[key]) > limit:
            item[key] = clip(item[key], limit)
    if "arguments" in item:
        item["arguments"] = _shrink_arguments(item["arguments"], limit)
    if isinstance(item.get("tool_calls"), list):
        calls = []
        for call in item["tool_calls"]:
            if isinstance(call, dict) and isinstance(call.get("function"), dict):
                call = dict(call)
                function = dict(call["function"])
                function["arguments"] = _shrink_arguments(function.get("arguments"), limit)
                call["function"] = function
            calls.append(call)
        item["tool_calls"] = calls
    return item


TRIM_FIELDS = {"write": ("content",), "edit": ("old", "new")}


def _elide_payload(name: Any, arguments: Any) -> Any:
    """write/edit arguments with long payload fields replaced by a marker (valid JSON, other
    keys kept); anything else unchanged."""
    fields = TRIM_FIELDS.get(str(name or ""))
    if not fields or not isinstance(arguments, str) or len(arguments) <= TRIM_ARG_CHARS:
        return arguments
    try:
        parsed = json.loads(arguments)
    except ValueError:  # never executed (invalid JSON): nothing on disk to point at
        return json.dumps({"omitted": f"{len(arguments)} chars of arguments"})
    if not isinstance(parsed, dict):
        return arguments
    changed = False
    for key in fields:
        value = parsed.get(key)
        if isinstance(value, str) and len(value) > TRIM_ARG_CHARS:
            parsed[key] = ELIDED_NOTE.format(chars=len(value))
            changed = True
    return json.dumps(parsed, ensure_ascii=False) if changed else arguments


def trim_message(message: dict[str, Any]) -> dict[str, Any]:
    """Copy of an old model turn item with write/edit payloads elided and reasoning_content
    clipped (the field stays: DeepSeek rejects a replayed turn without it)."""
    item = dict(message)
    if item.get("type") == "function_call":
        item["arguments"] = _elide_payload(item.get("name"), item.get("arguments"))
    if item.get("role") != "assistant":
        return item
    reasoning = item.get("reasoning_content")
    if isinstance(reasoning, str) and len(reasoning) > OLD_REASONING_CHARS:
        item["reasoning_content"] = clip(reasoning, OLD_REASONING_CHARS)
    if isinstance(item.get("tool_calls"), list):
        calls = []
        for call in item["tool_calls"]:
            if isinstance(call, dict) and isinstance(call.get("function"), dict):
                function = dict(call["function"])
                function["arguments"] = _elide_payload(function.get("name"), function.get("arguments"))
                call = {**call, "function": function}
            calls.append(call)
        item["tool_calls"] = calls
    return item


class History:
    """system + brief, an optional compaction summary, then one group per model turn.

    A group is the model's turn (assistant message / Responses output items) followed by
    its tool results and any user notes that came after it, so compaction never separates
    a call from its result.
    """

    def __init__(self, system: dict[str, Any], brief: dict[str, Any]):
        self.head: list[dict[str, Any]] = [system, brief]
        self.summary: dict[str, Any] | None = None
        self.groups: list[list[dict[str, Any]]] = []
        self.dropped = 0
        self.compactions = 0
        self.trimmed = 0                # leading groups already trimmed

    def messages(self) -> list[dict[str, Any]]:
        items = list(self.head)
        if self.summary is not None:
            items.append(self.summary)
        for group in self.groups:
            items.extend(group)
        return items

    def add_turn(self, items: list[dict[str, Any]]) -> None:
        self.groups.append(list(items))

    def add(self, message: dict[str, Any]) -> None:
        if self.groups:
            self.groups[-1].append(message)
        else:
            self.groups.append([message])

    def size(self) -> int:
        return sum(message_size(item) for item in self.messages())

    def droppable(self, keep: int) -> int:
        return max(0, len(self.groups) - keep)

    def trim(self, recent: int = TRIM_KEEP_GROUPS) -> int:
        """Trim every group but the last ``recent`` once (``trim_message``): write/edit payloads
        over TRIM_ARG_CHARS are elided, reasoning_content is clipped to OLD_REASONING_CHARS.
        Tool results, notes, call ids, the head and the summary are untouched; returns the
        number of groups trimmed by this call."""
        end = self.droppable(max(0, recent))
        if end <= self.trimmed:
            return 0
        for index in range(self.trimmed, end):
            self.groups[index] = [trim_message(item) for item in self.groups[index]]
        count, self.trimmed = end - self.trimmed, end
        return count

    def compact(self, summary_text: str, keep: int = KEEP_GROUPS, shrink: int | None = None) -> int:
        """Keep head + a new summary + the last ``keep`` groups; returns groups dropped."""
        drop = self.droppable(keep)
        if drop == 0 and shrink is None:
            return 0
        self.groups = self.groups[drop:]
        self.trimmed = max(0, self.trimmed - drop)
        if shrink is not None:
            self.groups = [[shrink_message(item, shrink) for item in group] for group in self.groups]
        self.dropped += drop
        self.compactions += 1
        self.summary = {"role": "user", "content": summary_text}
        return drop


# --------------------------------------------------------------------------- checks

def _as_check(raw: Any) -> CheckResult:
    if isinstance(raw, CheckResult):
        return raw
    if isinstance(raw, bool):
        return CheckResult(ok=raw, build_ok=raw, start_ok=raw,
                           feedback="CHECK PASSED" if raw else "CHECK FAILED")
    if isinstance(raw, dict):
        ok = bool(raw.get("ok"))
        return CheckResult(ok=ok, build_ok=bool(raw.get("build_ok", ok)),
                           start_ok=bool(raw.get("start_ok", ok)),
                           missing_strings=list(raw.get("missing_strings") or []),
                           feedback=str(raw.get("feedback") or ("CHECK PASSED" if ok else "CHECK FAILED")),
                           seconds=float(raw.get("seconds") or 0.0))
    ok = bool(getattr(raw, "ok", False))
    return CheckResult(ok=ok, build_ok=bool(getattr(raw, "build_ok", ok)),
                       start_ok=bool(getattr(raw, "start_ok", ok)),
                       missing_strings=list(getattr(raw, "missing_strings", None) or []),
                       feedback=str(getattr(raw, "feedback", "") or ("CHECK PASSED" if ok else "CHECK FAILED")),
                       seconds=float(getattr(raw, "seconds", 0.0) or 0.0))


def deliverable(result: CheckResult | None) -> bool:
    """The grader installs, builds once and starts once on a fresh database: a check that failed
    only in its restart round still delivers a working app."""
    if result is None:
        return False
    return bool(result.ok or (result.build_ok and getattr(result, "first_start_ok", False)
                              and getattr(result, "npm_ok", True)))


def upsert_section(text: str, key: str, body: str) -> str:
    """Replace (or append) the ``## key`` section of a markdown notes file."""
    header = f"## {key}"
    # "## " starts a section, so headings inside the body are demoted one level.
    body = "\n".join("#" + line if line.startswith("## ") else line for line in body.strip().splitlines())
    block = f"{header}\n{body}\n"
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.rstrip("\r\n") == header), None)
    if start is None:
        return (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rest = "".join(lines[end:])
    return "".join(lines[:start]) + block + ("\n" + rest if rest else "")


# --------------------------------------------------------------------------- units

def idle_after(allowance: int) -> int:
    """Responses without a write before IDLE_NOTE: max(6, 30% of the allowance), but always
    before the allowance runs out."""
    return min(max(IDLE_MIN_RESPONSES, round(IDLE_FRACTION * allowance)), max(1, allowance - 2))


def unit_ids(units: list[dict]) -> list[str]:
    return [str(spec.get("id") or f"unit-{index}") for index, spec in enumerate(units, start=1)]


def unit_weights(units: list[dict], unit_text: dict[str, str]) -> list[float]:
    """Budget weight per module unit: its requirement text length (the atomic count when a
    unit has no text) / the mean, clamped to [WEIGHT_MIN, WEIGHT_MAX], renormalised to mean 1."""
    sizes = [float(len(unit_text.get(uid) or "")) for uid in unit_ids(units)]
    if not all(sizes):
        sizes = [float(len(spec.get("atomic_ids") or [])) for spec in units]
    mean = sum(sizes) / len(sizes) if sizes else 0.0
    if mean <= 0:
        return [1.0] * len(units)
    clamped = [min(WEIGHT_MAX, max(WEIGHT_MIN, size / mean)) for size in sizes]
    scale = sum(clamped) / len(clamped)
    return [weight / scale for weight in clamped]


@dataclass
class Unit:
    label: str                      # U00 (foundation), U01..Unn, FIX
    uid: str                        # "foundation", the digest unit id, "fix"
    title: str
    kind: str                       # foundation | module | fix
    max_steps: int
    include_reserve: bool
    ui_strings: list[str] | None = None
    weight: float = 1.0
    allowance_steps: int = 0        # honest response count for the brief (<= max_steps)
    allowance_tokens: int | None = None
    allowance_seconds: float | None = None
    history: History | None = None
    steps: int = 0
    fix_steps: int = 0
    done: bool = False
    done_calls: int = 0
    warned: bool = False
    nudged: bool = False
    wrote: bool = False             # a write/edit succeeded in this unit
    idle_noted: bool = False
    aggressive_used: bool = False
    compact_at: int = 0
    end_reason: str = ""
    fix_end_reason: str = ""
    summary: str = ""
    files: dict[str, None] = field(default_factory=dict)
    tool_counts: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    last_check_feedback: str = ""
    check_ok: bool | None = None
    committed: bool = False
    tokens: int = 0
    seconds: float = 0.0


class Pipeline:
    def __init__(self, client: Any, model: str, requirements_dir: Path, output_dir: Path,
                 runtime: Any = None, check_fn: Callable[..., Any] | None = None):
        self.client = client
        self.model = model
        self.requirements_dir = Path(requirements_dir).resolve()
        self.root = Path(output_dir).resolve()
        self.runtime = runtime
        self.check_fn = check_fn
        self.budget = RunBudget()
        self.agent_dir = self.root / ".arc" / "agent"
        self.logs_dir = self.root / ".arc" / "logs"
        self.unit_max_steps = _env_int("AGENT_UNIT_MAX_STEPS", DEFAULT_UNIT_MAX_STEPS, 1)
        self.foundation_max_steps = _env_int("AGENT_FOUNDATION_MAX_STEPS", DEFAULT_FOUNDATION_MAX_STEPS, 1)
        self.fix_steps = _env_int("AGENT_FIX_STEPS", DEFAULT_FIX_STEPS, 0)
        self.context_chars = _env_int("AGENT_CONTEXT_CHARS", DEFAULT_CONTEXT_CHARS, 1000)
        self.retry_delay = _env_float("AGENT_RETRY_DELAY", DEFAULT_RETRY_DELAY)
        self.sleep = time.sleep
        self.finalize_seconds = min(FINALIZE_SECONDS, self.budget.reserve_seconds * 0.5)

        self.copied = False
        self.bootstrap: NpmBootstrap | None = None
        self.digest: dict[str, Any] | None = None
        self.wire_api = "chat"
        self.system_message: dict[str, Any] = {"role": "system", "content": ""}
        self.cache_policy: PromptCachePolicy = PromptCachePolicy(False, mode="off")
        self.recorder: UsageRecorder | None = None

        self.stopped: str | None = None
        self.consecutive_failures = 0
        self.global_step = 0
        self.request_costs: list[tuple[str, int, float]] = []  # (unit, tokens, seconds) per main-loop response
        self.last_check: CheckResult | None = None
        self.last_check_fp: str | None = None
        self.last_check_unit: str | None = None
        self.last_good: str | None = None
        self.checks: list[dict[str, Any]] = []
        self.units: list[Unit] = []
        self.notes_progress: dict[str, str] = {}
        self.errors: list[str] = []
        self.final: dict[str, Any] = {}
        self.not_started: list[str] = []
        self.budget_stop: str | None = None

    # ------------------------------------------------------------------ helpers
    def error(self, message: str, exc: BaseException | None = None) -> None:
        text = f"{message}: {type(exc).__name__}: {exc}" if exc is not None else message
        self.errors.append(_one_line(text, 400))
        log_error(self.root, message, exc)

    def rt(self, path: str, *args: Any, **kwargs: Any) -> Any:
        """Call runtime.<path>(...); failures are logged, never raised."""
        if self.runtime is None:
            return None
        try:
            target: Any = self.runtime
            for part in path.split("."):
                target = getattr(target, part)
            return target(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - runtime bookkeeping is never fatal
            self.error(f"runtime {path} failed", exc)
            return None

    def write_json(self, name: str, data: Any) -> None:
        try:
            self.agent_dir.mkdir(parents=True, exist_ok=True)
            (self.agent_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n",
                                               encoding="utf-8")
        except Exception as exc:
            self.error(f"could not write {name}", exc)

    def append_step(self, row: dict[str, Any]) -> None:
        try:
            self.agent_dir.mkdir(parents=True, exist_ok=True)
            with (self.agent_dir / "steps.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
        except Exception as exc:
            self.error("could not append steps.jsonl", exc)

    # ------------------------------------------------------------------ run
    def run(self) -> dict[str, Any]:
        try:
            try:
                self.setup()
                if self.copied:
                    self.run_units()
            except Exception as exc:  # noqa: BLE001 - finalize must still happen
                self.error("pipeline error", exc)
            if self.copied:
                try:
                    self.finalize()
                except Exception as exc:  # noqa: BLE001
                    self.error("finalize error", exc)
            summary = self.summary()
            if self.copied:
                self.write_json("summary.json", summary)
            return summary
        finally:
            if self.bootstrap is not None:
                try:
                    self.bootstrap.stop()
                except Exception:
                    pass

    def setup(self) -> None:
        # 1. template
        try:
            copy_template(TEMPLATE_DIR, self.root)
            self.copied = True
        except Exception as exc:
            self.error("copy_template failed", exc)
            self.copied = ((self.root / "frontend" / "package.json").is_file()
                           and (self.root / "backend" / "package.json").is_file())
        if not self.copied:
            return
        log(f"template copied to {self.root}")
        # 2. npm install in the background (only needed by the real check)
        if self.check_fn is None:
            try:
                self.bootstrap = NpmBootstrap(self.root, self.logs_dir)
                self.bootstrap.start()
            except Exception as exc:
                self.error("npm bootstrap failed to start", exc)
                self.bootstrap = None
            self.check_fn = self.default_check
        # 3. runtime
        if self.runtime is None and AgentRuntime is not None:
            try:
                self.runtime = AgentRuntime.from_env(project_dir=str(self.root))
            except Exception as exc:
                self.error("AgentRuntime.from_env failed", exc)
                self.runtime = None
        self.rt("events.mark_run_started", "agent run started")
        self.rt("traceability.init_db")
        self.rt("git.ensure_repo", create_initial_commit=True)
        # 4. digest
        try:
            self.digest = build_digest(self.requirements_dir, self.root / ".arc")
        except Exception as exc:
            self.error(f"requirement digest failed for {self.requirements_dir}", exc)
            self.digest = None
        if self.digest is not None:
            for req in self.digest.get("reqs") or []:
                req_id, name = req.get("id"), req.get("name") or req.get("id")
                self.rt("traceability.upsert_requirement", req_id=req_id, name=name,
                        description=req.get("description") or "", scenarios=req.get("scenarios"),
                        parent_id=req.get("parent_id"), children_ids=req.get("children_ids"),
                        dependencies=req.get("dependencies"))
                self.rt("events.mark_design_done", req_id, name)
                self.rt("events.mark_implementation_started", req_id, name)
            count = len(self.digest.get("units") or [])
            log(f"digest: {len(self.digest.get('reqs') or [])} requirements, {count} units")
            # the budget scales with the task (a limit set in the env is kept)
            self.budget.scale_to(count)
            self.finalize_seconds = min(FINALIZE_SECONDS, self.budget.reserve_seconds * 0.5)
            log(f"budget scaled for {count} units: tokens={_human(self.budget.max_tokens)} "
                f"seconds={_human(self.budget.max_seconds)}")
        # 5. model settings
        try:
            self.wire_api = selected_wire_api()
        except ValueError as exc:
            self.error("invalid OPENAI_WIRE_API; using chat", exc)
            self.wire_api = "chat"
        if self.digest is not None:
            system = agent_prompt.build_system_prompt(self.digest.get("overview") or "",
                                                      self.digest.get("seed") or "",
                                                      self.digest.get("domain") or {})
            self.system_message = {"role": "system", "content": system}
        tools = responses_tools() if self.wire_api == "responses" else TOOLS
        try:
            self.cache_policy = PromptCachePolicy.from_env(self.client, self.model, self.wire_api,
                                                           [self.system_message], tools)
        except Exception as exc:
            self.error("invalid prompt cache settings; prompt cache fields disabled", exc)
            self.cache_policy = PromptCachePolicy(False, mode="off")
        self.recorder = UsageRecorder(self.root, self.model, self.wire_api)

    def default_check(self, root: Path, *, ui_strings: list[str] | None = None,
                      deadline: float | None = None) -> CheckResult:
        return run_check(root, self.logs_dir, ui_strings=ui_strings, deadline=deadline, npm=self.bootstrap)

    # ------------------------------------------------------------------ checks
    def check(self, label: str, ui_strings: list[str] | None, deadline: float | None,
              unit: Unit | None = None) -> CheckResult:
        started = time.monotonic()
        try:
            result = _as_check(self.check_fn(self.root, ui_strings=ui_strings, deadline=deadline))
        except Exception as exc:  # noqa: BLE001 - a check must never crash the run
            self.error(f"check {label} crashed", exc)
            result = CheckResult(ok=False, build_ok=False, start_ok=False,
                                 feedback=f"CHECK FAILED: internal check error: {type(exc).__name__}: {exc}")
        self.last_check = result
        self.last_check_fp = source_fingerprint(self.root)
        self.last_check_unit = unit.label if unit is not None else None
        seconds = result.seconds or (time.monotonic() - started)
        self.checks.append({"label": label, "unit": unit.label if unit else None, "ok": result.ok,
                            "build_ok": result.build_ok, "start_ok": result.start_ok,
                            "first_start_ok": getattr(result, "first_start_ok", None),
                            "missing_strings": len(result.missing_strings or []),
                            "seconds": round(seconds, 1), "t": round(self.budget.elapsed())})
        if unit is not None:
            unit.last_check_feedback = result.feedback
            unit.check_ok = result.ok
        log(f"check {label}: {'PASSED' if result.ok else 'FAILED'} ({seconds:.0f}s)")
        return result

    def check_is_current(self) -> bool:
        return (self.last_check is not None and self.last_check.ok
                and self.last_check_fp == source_fingerprint(self.root))

    def commit_good(self, message: str) -> bool:
        if self.runtime is None:
            return False
        try:
            self.runtime.git.commit(message)
        except Exception as exc:  # noqa: BLE001
            self.error(f"git commit '{message}' failed", exc)
            return False
        head = self.rt("git.current_head")
        if head:
            self.last_good = str(head)
        return bool(head)

    # ------------------------------------------------------------------ notes
    def read_notes(self) -> str:
        try:
            return (self.root / ".arc" / "notes.md").read_text(encoding="utf-8")
        except OSError:
            return ""

    def progress_text(self) -> str:
        return "\n".join(self.notes_progress.values())

    def on_unit_done(self, unit: Unit, summary: str, notes: str) -> str:
        unit.done = True
        unit.done_calls += 1
        unit.summary = summary
        arc = self.root / ".arc"
        try:
            arc.mkdir(parents=True, exist_ok=True)
            if notes and notes.strip():
                (arc / "notes.md").write_text(upsert_section(self.read_notes(), unit.uid, notes),
                                              encoding="utf-8")
            line = f"- {unit.label} {unit.uid} {unit.title}: {_one_line(summary, 600) or '(no summary)'}"
            self.notes_progress[unit.label] = line
            (arc / "progress.md").write_text(self.progress_text() + "\n", encoding="utf-8")
        except Exception as exc:
            self.error("could not update notes/progress", exc)
        return (f"unit {unit.label} marked done; the orchestrator now runs the check and reports "
                "any failure back to you.")

    # ------------------------------------------------------------------ units
    def run_units(self) -> None:
        if self.client is None:
            self.stopped = "no model client (OPENAI_API_KEY missing or client creation failed)"
            log(f"skipping model work: {self.stopped}")
            return
        if self.digest is None:
            self.stopped = "requirement digest unavailable"
            log(f"skipping model work: {self.stopped}")
            return
        units = list(self.digest.get("units") or [])
        total = len(units)
        unit_text = self.digest.get("unit_text") or {}
        weights = unit_weights(units, unit_text)
        log(f"wire_api={self.wire_api} model={self.model} prompt_cache={self.cache_policy.mode} "
            f"units={total} budget tokens={_human(self.budget.max_tokens)} "
            f"seconds={_human(self.budget.max_seconds)}")

        # foundation
        reason = self.budget.exhausted(include_reserve=True)
        if reason:
            self.budget_stop = reason
            self.not_started = ["foundation"] + [u.get("id", "") for u in units]
            log(f"budget: {reason}; no unit started")
        else:
            foundation = Unit(label="U00", uid="foundation", title="Foundation", kind="foundation",
                              max_steps=self.foundation_max_steps, include_reserve=True,
                              weight=FOUNDATION_WEIGHT)
            deadline, cap = self.budget.unit_allowance(total + 1, weight=FOUNDATION_WEIGHT,
                                                       weight_left=FOUNDATION_WEIGHT + sum(weights))
            index_text = file_index(self.root)
            brief = self.plan(foundation, deadline, cap,
                              lambda _steps: agent_prompt.foundation_brief(units, index_text))
            self.run_unit(foundation, brief, deadline, cap)

        # module units
        for index, (uid, spec) in enumerate(zip(unit_ids(units), units), start=1):
            if self.stopped or self.budget_stop:
                self.not_started.extend(u.get("id", "") for u in units[index - 1:])
                break
            reason = self.budget.exhausted(include_reserve=True)
            if reason:
                self.budget_stop = reason
                self.not_started.extend(u.get("id", "") for u in units[index - 1:])
                log(f"budget: {reason}; not starting U{index:02d} or later units")
                break
            strings = list((self.digest.get("unit_strings") or {}).get(uid) or [])
            unit = Unit(label=f"U{index:02d}", uid=uid, title=str(spec.get("title") or uid), kind="module",
                        max_steps=self.unit_max_steps, include_reserve=True, ui_strings=strings or None,
                        weight=weights[index - 1])
            deadline, cap = self.budget.unit_allowance(total - index + 1, weight=unit.weight,
                                                       weight_left=sum(weights[index - 1:]))
            notes, progress, index_text = self.read_notes(), self.progress_text(), file_index(self.root)
            brief = self.plan(unit, deadline, cap, lambda steps: agent_prompt.unit_brief(
                spec, unit_text.get(uid, ""), strings, notes, progress, index_text, steps,
                index=index, total=total))
            self.run_unit(unit, brief, deadline, cap)

        # fix unit: only when the last check failed and the reserve allows it
        if self.stopped or self.last_check is None or self.last_check.ok:
            return
        reason = self.budget.exhausted(include_reserve=False)
        if reason:
            log(f"budget: {reason}; no fix unit")
            return
        deadline, cap = self.budget.unit_allowance(1, include_reserve=False)
        hard = self.budget.deadline
        if hard is not None:
            limit = hard - self.finalize_seconds
            deadline = limit if deadline is None else min(deadline, limit)
        if deadline is not None and deadline - time.monotonic() < MIN_FIX_UNIT_SECONDS:
            log("budget: too little time left for a fix unit")
            return
        fix = Unit(label="FIX", uid="fix", title="Final fix", kind="fix",
                   max_steps=self.unit_max_steps, include_reserve=False)
        feedback, notes, index_text = self.last_check.feedback, self.read_notes(), file_index(self.root)
        brief = self.plan(fix, deadline, cap, lambda _steps: agent_prompt.fix_brief(feedback, notes, index_text))
        self.run_unit(fix, brief, deadline, cap)

    def plan(self, unit: Unit, deadline: float | None, cap: int | None,
             make_brief: Callable[[int], str]) -> str:
        """Record the unit's allowance and return its brief, built with the step allowance
        (a draft at max_steps sizes the prompt for the first estimate)."""
        unit.allowance_tokens = cap
        unit.allowance_seconds = None if deadline is None else round(max(0.0, deadline - time.monotonic()), 1)
        draft = make_brief(unit.max_steps)
        unit.allowance_steps = self.step_allowance(unit.max_steps, deadline, cap, len(draft))
        return draft if unit.allowance_steps == unit.max_steps else make_brief(unit.allowance_steps)

    def step_allowance(self, max_steps: int, deadline: float | None, cap: int | None,
                       brief_chars: int) -> int:
        """Responses the allowance pays for: min(cap / tokens per response, time left / seconds
        per response), clamped to [MIN_ALLOWANCE_STEPS, max_steps]; an unlimited dimension is
        ignored.  Costs are the mean over every main-loop response (tool time included) of the
        last ESTIMATE_UNITS whole units once ESTIMATE_MIN_REQUESTS ran (a unit's late, long
        contexts alone would overstate a fresh unit), else (system + brief + tools) /
        CHARS_PER_TOKEN * CONTEXT_GROWTH tokens and DEFAULT_RESPONSE_SECONDS."""
        labels = set(list(dict.fromkeys(label for label, _, _ in self.request_costs))[-ESTIMATE_UNITS:])
        recent = [(tokens, seconds) for label, tokens, seconds in self.request_costs if label in labels]
        if len(recent) >= ESTIMATE_MIN_REQUESTS:
            est_tokens = sum(tokens for tokens, _ in recent) / len(recent)
            est_seconds = sum(seconds for _, seconds in recent) / len(recent)
        else:
            tools = responses_tools() if self.wire_api == "responses" else TOOLS
            chars = len(str(self.system_message.get("content") or "")) + brief_chars + len(json.dumps(tools))
            est_tokens = chars / CHARS_PER_TOKEN * CONTEXT_GROWTH
            est_seconds = DEFAULT_RESPONSE_SECONDS
        limits = []
        if cap is not None:
            limits.append(cap // max(1.0, est_tokens))
        if deadline is not None:
            limits.append(max(0.0, deadline - time.monotonic()) // max(1.0, est_seconds))
        if not limits:
            return max_steps
        return int(min(max_steps, max(MIN_ALLOWANCE_STEPS, min(limits))))

    def run_unit(self, unit: Unit, brief: str, deadline: float | None, cap: int | None) -> None:
        self.units.append(unit)
        started, tokens0 = time.monotonic(), self.budget.tokens_used
        unit.history = History(self.system_message, {"role": "user", "content": brief})
        unit.compact_at = self.context_chars
        left = "inf" if deadline is None else f"{max(0.0, deadline - started):.0f}s"
        log(f"{unit.label} start: {_one_line(unit.title, 80)} (steps<={unit.max_steps} "
            f"allowance={unit.allowance_steps or unit.max_steps} time<={left} tokens<={_human(cap)})")
        ctx = ToolContext(
            root=self.root, requirements_dir=self.requirements_dir, log_dir=self.logs_dir,
            run_check=lambda: self.check(f"{unit.label} tool", unit.ui_strings, self.budget.deadline, unit).feedback,
            on_unit_done=lambda summary, notes: self.on_unit_done(unit, summary, notes),
            command_deadline=self.budget.deadline)
        try:
            unit.end_reason = self.loop(unit, ctx, max_steps=unit.max_steps, deadline=deadline, cap=cap,
                                        warn=True, phase="step")
            log(f"{unit.label} ended: {unit.end_reason}")
            if not self.stopped:
                result = self.post_unit_check(unit)
                if not result.ok and self.can_continue(unit):
                    unit.done = False
                    unit.nudged = False
                    if unit.end_reason == BAD_REQUEST_END:
                        # the API rejected this context even after compaction: continue on a fresh one
                        fresh = agent_prompt.fix_brief(result.feedback, self.read_notes(), file_index(self.root))
                        unit.history = History(self.system_message, {"role": "user", "content": fresh})
                        unit.compact_at = self.context_chars
                        unit.aggressive_used = False
                    else:
                        unit.history.add({"role": "user", "content": CONTINUE_NOTE + result.feedback})
                    fix_deadline, fix_cap = self.boundary(unit.include_reserve)
                    unit.fix_end_reason = self.loop(unit, ctx, max_steps=self.fix_steps, deadline=fix_deadline,
                                                    cap=fix_cap, warn=False, phase="fix-step")
                    log(f"{unit.label} fix steps ended: {unit.fix_end_reason}")
                    if not self.stopped:
                        result = self.post_unit_check(unit)
                if deliverable(result):
                    unit.committed = self.commit_good(f"unit {unit.uid} ok")
        except Exception as exc:  # noqa: BLE001 - one broken unit never ends the run
            self.error(f"{unit.label} failed", exc)
            unit.end_reason = unit.end_reason or f"error: {type(exc).__name__}"
        finally:
            unit.tokens = self.budget.tokens_used - tokens0
            unit.seconds = round(time.monotonic() - started, 1)

    def post_unit_check(self, unit: Unit) -> CheckResult:
        """Check after a unit; an unchanged source tree reuses the last result (a failure only
        when this unit already saw it), so an unchanged app is never built twice in a row."""
        last = self.last_check
        if (last is not None and self.last_check_fp == source_fingerprint(self.root)
                and (last.ok or self.last_check_unit == unit.label)):
            log(f"check {unit.label}: reusing the last {'passing' if last.ok else 'failing'} check "
                "(no source change since)")
            unit.check_ok = last.ok
            unit.last_check_feedback = last.feedback
            return last
        return self.check(unit.label, unit.ui_strings, self.budget.deadline, unit)

    def can_continue(self, unit: Unit) -> bool:
        return (self.fix_steps > 0 and self.client is not None and not self.stopped
                and self.budget.exhausted(include_reserve=unit.include_reserve) is None)

    def boundary(self, include_reserve: bool) -> tuple[float | None, int | None]:
        deadline = self.budget.deadline
        if deadline is not None:
            deadline -= self.budget.reserve_seconds if include_reserve else self.finalize_seconds
        cap = self.budget.tokens_left()
        if cap is not None and include_reserve:
            cap = max(0, cap - self.budget.reserve_tokens)
        return deadline, cap

    def fraction(self, steps: int, max_steps: int, t0: float, deadline: float | None,
                 tokens0: int, cap: int | None) -> tuple[float, str]:
        if steps >= max_steps:  # a unit that ran its cap ends by it, whatever its last step spent
            return 1.0, "step cap"
        parts = [(steps / max_steps, "step cap")]
        if deadline is not None:
            span = deadline - t0
            parts.append((1.0 if span <= 0 else (time.monotonic() - t0) / span, "time allowance spent"))
        if cap is not None:
            parts.append((1.0 if cap <= 0 else (self.budget.tokens_used - tokens0) / cap, "token allowance spent"))
        return max(parts, key=lambda part: part[0])

    # ------------------------------------------------------------------ the loop
    def loop(self, unit: Unit, ctx: ToolContext, *, max_steps: int, deadline: float | None,
             cap: int | None, warn: bool, phase: str) -> str:
        history = unit.history
        assert history is not None
        steps = counted = 0
        t0, tokens0 = time.monotonic(), self.budget.tokens_used
        mark = (t0, tokens0)
        while True:
            if steps > counted:  # the last response with its tool calls (and any failed retries before it)
                counted, mark = steps, self.note_cost(unit, phase, mark)
            if unit.done:
                return "unit_done"
            if self.stopped:
                return f"stopped: {self.stopped}"
            hard = self.budget.exhausted(include_reserve=False)
            if hard:
                return hard
            used, why = self.fraction(steps, max_steps, t0, deadline, tokens0, cap)
            if used >= 1.0:
                return why
            if warn and not unit.warned and used >= WARN_FRACTION:
                unit.warned = True
                history.add({"role": "user", "content": WARN_NOTE if unit.wrote else agent_prompt.NO_WRITE_WARN})
            self.maybe_compact(unit)

            response, outcome = self.request(unit)
            if response is None:
                if outcome == "stop":
                    return f"stopped: {self.stopped}"
                if outcome == "end":
                    return BAD_REQUEST_END
                continue  # retry (transient failure or aggressive compaction)

            steps += 1
            if phase == "step":
                unit.steps += 1
            else:
                unit.fix_steps += 1
            self.global_step += 1
            log(f"{unit.label} {phase} {steps}/{max_steps} tokens={_human(self.budget.tokens_used)}/"
                f"{_human(self.budget.max_tokens)} t={self.budget.elapsed():.0f}s")
            calls = self.replay(unit, response)
            if calls is None:  # Responses status not completed: nothing usable to execute
                if unit.aggressive_used:
                    return "incomplete model response"
                unit.aggressive_used = True
                self.compact_aggressively(unit)
                continue
            if not calls:
                if unit.nudged:
                    self.step_row(unit, phase, steps, [])
                    return "no tool calls after a nudge"
                unit.nudged = True
                history.add({"role": "user", "content": NUDGE_NOTE})
                self.step_row(unit, phase, steps, [])
                continue
            unit.nudged = False
            names = []
            for name, arguments, call_id in calls:
                names.append(name)
                result = clip(dispatch(name, arguments, ctx), TOOL_RESULT_LIMIT)
                self.track_tool(unit, name, arguments, result)
                log(f"tool {name}: {result.splitlines()[0] if result else ''}")
                if self.wire_api == "responses":
                    history.add({"type": "function_call_output", "call_id": call_id, "output": result})
                else:
                    history.add({"role": "tool", "tool_call_id": call_id, "content": result})
            responses = unit.steps + unit.fix_steps
            allowance = unit.allowance_steps or unit.max_steps
            if (not unit.wrote and not unit.idle_noted and not unit.done
                    and responses >= idle_after(allowance)):
                # after the tool results: the note is the last user message of the turn
                unit.idle_noted = True
                history.add({"role": "user", "content": agent_prompt.IDLE_NOTE.format(
                    used=responses, allowance=allowance)})
            self.step_row(unit, phase, steps, names)

    def step_row(self, unit: Unit, phase: str, steps: int, names: list[str]) -> None:
        usage = self.recorder.rows[-1] if self.recorder is not None and self.recorder.rows else {}
        self.append_step({"step": self.global_step, "unit": unit.label, "phase": phase, "unit_step": steps,
                          "tools": names, "input_tokens": usage.get("input_tokens"),
                          "output_tokens": usage.get("output_tokens"),
                          "cached_tokens": usage.get("cached_input_tokens"),
                          "tokens_used": self.budget.tokens_used, "t": round(self.budget.elapsed(), 1)})

    def note_cost(self, unit: Unit, phase: str, mark: tuple[float, int]) -> tuple[float, int]:
        """Record the tokens and wall time since ``mark`` as one response of the unit's main loop
        (step_allowance's estimate); returns the mark for the next response."""
        now, tokens = time.monotonic(), self.budget.tokens_used
        if phase == "step":
            self.request_costs.append((unit.label, tokens - mark[1], now - mark[0]))
        return now, tokens

    def track_tool(self, unit: Unit, name: str, arguments: Any, result: str) -> None:
        unit.tool_counts[name] += 1
        if result.startswith("error"):
            unit.errors.append(f"{name}: {_one_line(result, 300)}")
            del unit.errors[:-6]
        if name in ("write", "edit") and not result.startswith("error"):
            unit.wrote = True
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
                path = str(args.get("path") or "").strip()
            except Exception:
                path = ""
            if path:
                unit.files.pop(path, None)
                unit.files[path] = None

    def summary_note(self, unit: Unit, dropped: int) -> str:
        history = unit.history
        total = (history.dropped if history else 0) + dropped
        files = list(unit.files)
        shown = ", ".join(files[-40:]) + (f" (+{len(files) - 40} earlier)" if len(files) > 40 else "")
        lines = [f"[context compacted] {total} earlier turns of this unit were removed from the context; "
                 "the files on disk are current. Progress so far in this unit:",
                 f"- Files written/edited: {shown or 'none'}",
                 "- Tool calls so far: " + (", ".join(f"{k} x{v}" for k, v in unit.tool_counts.items()) or "none"),
                 "- Last check: " + (clip(unit.last_check_feedback, 1500) if unit.last_check_feedback
                                     else "not run yet in this unit")]
        if unit.errors:
            lines.append("- Recent tool errors:\n" + "\n".join(f"  * {e}" for e in unit.errors[-4:]))
        lines.append("Continue where you left off; re-read a file before editing it when you need its "
                     "exact current content.")
        return "\n".join(lines)

    def maybe_compact(self, unit: Unit) -> None:
        """Once per crossing of the context threshold: trim the older turns (History.trim, all
        aged turns at once, so the cached prompt prefix changes only here), and compact when
        that leaves the history above TRIM_ENOUGH of the threshold."""
        history = unit.history
        if history is None:
            return
        size = history.size()
        if size <= unit.compact_at:
            return
        if history.trim():
            trimmed = history.size()
            log(f"{unit.label} context trimmed: {size} -> {trimmed} chars")
            if trimmed <= self.context_chars * TRIM_ENOUGH:
                return
            size = trimmed
        if history.droppable(KEEP_GROUPS) == 0:
            return
        dropped = history.compact(self.summary_note(unit, history.droppable(KEEP_GROUPS)), KEEP_GROUPS)
        after = history.size()
        # Re-arm at the threshold when back under it; otherwise only after real growth.
        unit.compact_at = self.context_chars if after <= self.context_chars else after + self.context_chars // 2
        log(f"{unit.label} context compacted: {size} -> {after} chars ({dropped} turns dropped)")

    def compact_aggressively(self, unit: Unit) -> None:
        history = unit.history
        if history is None:
            return
        size = history.size()
        note = self.summary_note(unit, history.droppable(AGGRESSIVE_KEEP_GROUPS))
        history.compact(note, AGGRESSIVE_KEEP_GROUPS, shrink=AGGRESSIVE_CLIP)
        unit.compact_at = max(self.context_chars, history.size() + self.context_chars // 2)
        log(f"{unit.label} context compacted aggressively: {size} -> {history.size()} chars")

    # ------------------------------------------------------------------ model I/O
    def request(self, unit: Unit) -> tuple[Any, str]:
        """(response, "ok") or (None, "retry" | "end" | "stop")."""
        history = unit.history
        assert history is not None
        messages = history.messages()
        timeout = None
        left = self.budget.seconds_left()
        if left is not None:
            timeout = max(10.0, min(CLIENT_TIMEOUT, left))
        request = build_request(self.model, self.wire_api, messages,
                                cache_fields=self.cache_policy.request_fields(), timeout=timeout)
        estimated_input = max(1, sum(message_size(m) for m in messages) // 4)
        try:
            if self.wire_api == "responses":
                response = self.client.responses.create(**request)
            else:
                response = self.client.chat.completions.create(**request)
        except Exception as exc:  # noqa: BLE001 - classified below
            return None, self.handle_api_error(unit, exc)
        row: dict[str, Any] = {}
        try:
            if self.recorder is not None:
                row = self.recorder.record(response, self.global_step + 1, self.cache_policy.mode,
                                           estimated_input_tokens=estimated_input)
        except Exception as exc:  # noqa: BLE001
            self.error("usage recording failed", exc)
        try:
            dumped = response.model_dump(exclude_none=True) if hasattr(response, "model_dump") else response
            estimated_output = max(1, message_size(dumped) // 4)
        except Exception:
            estimated_output = 1
        self.budget.record(row, estimated_input + estimated_output)
        if self.wire_api != "responses" and not (getattr(response, "choices", None) or []):
            return None, self.transient_failure(unit, "chat response without choices")
        self.consecutive_failures = 0
        return response, "ok"

    def transient_failure(self, unit: Unit, what: str) -> str:
        self.consecutive_failures += 1
        self.error(f"{unit.label} {what} (consecutive={self.consecutive_failures})")
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self.stopped = f"{self.consecutive_failures} consecutive model failures; last: {what}"
            return "stop"
        self.backoff()
        return "retry"

    def backoff(self) -> None:
        delay = min(30.0, self.retry_delay * self.consecutive_failures)
        left = self.budget.seconds_left()
        if left is not None:
            delay = min(delay, max(0.0, left - 1))
        if delay > 0:
            self.sleep(delay)

    def handle_api_error(self, unit: Unit, exc: Exception) -> str:
        kind = classify_api_error(exc)
        status = getattr(exc, "status_code", None)
        self.consecutive_failures += 1
        self.error(f"{unit.label} model request failed (status={status}, kind={kind}, "
                   f"consecutive={self.consecutive_failures})", exc)
        if kind == "fatal":
            self.stopped = f"model API error {status or type(exc).__name__}: {_one_line(exc, 200)}"
            return "stop"
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self.stopped = (f"{self.consecutive_failures} consecutive model failures; last: "
                            f"{status or type(exc).__name__}: {_one_line(exc, 200)}")
            return "stop"
        if kind == "bad_request":
            if unit.aggressive_used:
                return "end"
            unit.aggressive_used = True
            self.compact_aggressively(unit)
            return "retry"
        self.backoff()
        return "retry"

    def replay(self, unit: Unit, response: Any) -> list[tuple[str, Any, Any]] | None:
        """Append the model turn to the history; return its function calls (None = unusable)."""
        history = unit.history
        assert history is not None
        if self.wire_api == "responses":
            status = response_item_value(response, "status")
            if status not in (None, "completed"):
                details = response_item_value(response, "incomplete_details")
                self.error(f"{unit.label} Responses request did not complete (status={status}, "
                           f"details={_one_line(details, 200)})")
                return None
            output = [_as_dict(item) for item in (response_item_value(response, "output", []) or [])]
            history.add_turn(output)
            return [(str(response_item_value(call, "name") or ""), response_item_value(call, "arguments"),
                     response_item_value(call, "call_id"))
                    for call in response_function_calls(response)]
        choices = getattr(response, "choices", None) or []
        if not choices:  # request() retries these; never replay an empty turn
            return None
        message = choices[0].message
        # The SDK keeps DeepSeek's reasoning_content here; replay it verbatim within the unit.
        item = _as_dict(message)
        item.setdefault("role", "assistant")
        if "content" not in item and not item.get("tool_calls"):
            item["content"] = ""
        history.add_turn([item])
        calls = []
        for call in getattr(message, "tool_calls", None) or []:
            if getattr(call, "type", "function") != "function":
                continue
            function = getattr(call, "function", None)
            calls.append((str(getattr(function, "name", "") or ""), getattr(function, "arguments", None),
                          getattr(call, "id", None)))
        return calls

    # ------------------------------------------------------------------ finalize
    def finalize(self) -> None:
        log("finalize")
        final: dict[str, Any] = {"skipped": False, "reset_to_last_good": False}
        if self.check_is_current():
            final["skipped"] = True
            result = self.last_check
            log("final check skipped: the last check passed and no source changed since")
        else:
            result = self.check("final", None, None)
        assert result is not None
        final["ok"] = result.ok
        final["deliverable"] = deliverable(result)
        if not deliverable(result) and self.last_good and self.runtime is not None:
            log(f"final check failed; resetting to last good commit {self.last_good}")
            self.rt("git.reset_to_commit", self.last_good, hard=True)
            self.rt("git.clean_untracked")
            final["reset_to_last_good"] = True
            result = self.check("final-after-reset", None, None)
            final["ok_after_reset"] = result.ok
            final["deliverable"] = deliverable(result)
            log(f"after reset the check {'PASSED' if result.ok else 'FAILED'}")
        final["feedback_head"] = _one_line(result.feedback, 300)
        self.final = final
        try:
            cleanup_output(self.root)
        except Exception as exc:  # noqa: BLE001
            self.error("cleanup_output failed", exc)
        for req in (self.digest or {}).get("reqs") or []:
            self.rt("events.mark_implementation_done", req.get("id"), "implementation delivered")
        note = "agent run completed"
        if self.stopped or self.budget_stop:
            note += f" ({self.stopped or self.budget_stop})"
        self.rt("events.mark_run_completed", note)
        if self.runtime is not None:
            try:
                self.runtime.git.commit("final delivery")
            except Exception as exc:  # noqa: BLE001
                self.error("final delivery commit failed", exc)

    def summary(self) -> dict[str, Any]:
        return {
            "model": self.model, "wire_api": self.wire_api, "prompt_cache": self.cache_policy.mode,
            "requirements_dir": str(self.requirements_dir), "output_dir": str(self.root),
            "template_copied": self.copied, "digest_ok": self.digest is not None,
            "units_planned": len((self.digest or {}).get("units") or []),
            "units": [{"label": u.label, "id": u.uid, "title": u.title, "kind": u.kind, "steps": u.steps,
                       "fix_steps": u.fix_steps, "end_reason": u.end_reason, "fix_end_reason": u.fix_end_reason,
                       "unit_done": u.done_calls, "check_ok": u.check_ok, "committed": u.committed,
                       "compactions": u.history.compactions if u.history else 0,
                       "weight": round(u.weight, 3),
                       "allowance": {"steps": u.allowance_steps, "tokens": u.allowance_tokens,
                                     "seconds": u.allowance_seconds},
                       "tokens": u.tokens, "seconds": u.seconds, "tools": dict(u.tool_counts),
                       "summary": u.summary} for u in self.units],
            "not_started": self.not_started, "budget_stop": self.budget_stop, "stopped": self.stopped,
            "checks": self.checks, "last_good": self.last_good, "final": self.final,
            "requests": self.budget.requests, "budget": self.budget.summary(), "errors": self.errors[-30:],
        }


def run_pipeline(client: Any, model: str, requirements_dir: Path, output_dir: Path,
                 runtime: Any = None, check_fn: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Run the whole pipeline; never raises (except KeyboardInterrupt); returns the summary.

    ``client`` may be None (no model work).  ``check_fn(root, *, ui_strings, deadline)`` returns a
    CheckResult (or bool/dict); None wires lean_checks.run_check with a shared NpmBootstrap.
    ``runtime`` None creates ``AgentRuntime.from_env(project_dir=output_dir)``.
    """
    try:
        return Pipeline(client, model, Path(requirements_dir), Path(output_dir), runtime, check_fn).run()
    except Exception as exc:  # noqa: BLE001 - e.g. a broken env var in the constructor
        log_error(Path(output_dir), "pipeline setup failed", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}


def make_client(output_dir: Path | None) -> Any:
    """OpenAI client from the environment, or None (logged) when it cannot be created."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        log_error(output_dir, "OPENAI_API_KEY is not set; skipping all model work (the template is still delivered)")
        return None
    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": CLIENT_TIMEOUT, "max_retries": CLIENT_MAX_RETRIES}
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    if base_url:
        kwargs["base_url"] = base_url
    try:
        return OpenAI(**kwargs)
    except Exception as exc:  # noqa: BLE001
        log_error(output_dir, "could not create the OpenAI client", exc)
        return None


def main(argv: list[str] | None = None, *, client: Any = None, runtime: Any = None,
         check_fn: Callable[..., Any] | None = None) -> int:
    """CLI entry point; returns 0 on every path (KeyboardInterrupt excepted)."""
    output_dir: Path | None = None
    try:
        args = parse_args(argv)
        requirements_dir = Path(args.requirement_path).expanduser().resolve()
        output_dir = Path(args.output_dir).expanduser().resolve()
        os.environ["ARCBENCH_OUTPUT_DIR"] = str(output_dir)
        if str(args.task_type).strip().lower() != "web":
            log(f"task type {args.task_type!r} requested; building a web app anyway")
        model = os.environ.get("MODEL", "").strip() or DEFAULT_MODEL
        if client is None:
            client = make_client(output_dir)
        summary = run_pipeline(client, model, requirements_dir, output_dir, runtime=runtime, check_fn=check_fn)
        final = summary.get("final") or {}
        log(f"done: units={len(summary.get('units') or [])} final_ok={final.get('ok_after_reset', final.get('ok'))} "
            f"tokens={summary.get('budget', {}).get('tokens_used')}")
    except SystemExit as exc:  # argparse --help / usage errors
        if exc.code not in (0, None):
            log_error(output_dir, f"argument parsing failed (exit {exc.code})")
    except Exception as exc:  # noqa: BLE001 - the platform needs exit code 0
        log_error(output_dir, "unexpected error", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

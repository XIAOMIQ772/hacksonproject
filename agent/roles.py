"""Agent roles: the engineer who builds the app and the helpers it starts in the background."""
from __future__ import annotations

import os
import re
import concurrent.futures as futures
import threading
from pathlib import Path

import checkpoint
import checks
import loop
import spec
from llm import EFFORTS, LLM
from tools import Tools, shell

HERE = Path(__file__).resolve().parent
RULES = (HERE / "rules.md").read_text()
SOP = (HERE / "sop.md").read_text()
PLAN_FILE = "PLAN.md"
_print_lock = threading.Lock()

ENGINEER = f"""You are a senior full-stack engineer working in a git workspace that contains a React (Vite) \
frontend in frontend/ and an Express + SQLite backend in backend/ (dependencies are installed). Work with \
the tools read, write, edit, apply, bash, check, requirement, subagent, wait_subagent and done. Paths are relative to the workspace root. Do not start \
servers or browsers yourself; the check tool builds the frontend, starts the backend on a fresh database and \
runs the Playwright tests in backend/test-e2e.

## Tool calls
Every reply re-sends the whole conversation, so the number of replies sets the cost and the time of the build. \
Parallelize tool calls whenever possible: one reply may contain many tool calls, the read-only ones at its \
start (read, and shell commands such as cat, sed -n, grep, ls, wc, git show, git diff) run concurrently, and \
the rest run in order.
- Gather everything you need in one reply: all the files and searches for the next decision at once, never one \
read per reply.
- Write a whole slice in one reply: several write calls or one apply with every edit, followed in the same reply \
by check.
- Do not use python scripts to print large chunks of files or requirement text; use read and the requirement \
tool.
- Debug through a subagent: when a check fails for a reason you cannot see from the report, or you would \
otherwise try throwaway scripts (node -e, temporary test files, logging) to find out how your code behaves, \
start a subagent with the failing test, the error and the files involved, and let it run the experiments in \
its own context and report the cause and the fix. Keep working on something else meanwhile; every \
experiment you run yourself stays in your context for the rest of the build.

## Subagents
Your context is the most valuable resource of this build; a subagent spends its own. Keep one or two \
subagents busy most of the time, and delegate by default whenever one of these comes up:
- an area is finished: a subagent reviews it against its requirement ids;
- you start implementing an area: a subagent drafts the e2e tests of the next area into its spec file;
- a check fails and the cause is not obvious from the report: a subagent investigates and reports cause and fix;
- you need to understand more than two or three files you did not just write: a subagent surveys them and \
reports what you need.
Do the critical path yourself: the code of the area you are building and the fixes you know how to make.
Start subagents whose work does not block each other together, as several subagent calls in one reply (for \
example reviews of every finished area at once), using all free slots; never run them one after another. \
Before you call wait_subagent, start every other subagent you will need, and keep working while they run.

Read only files you need and keep code consistent with {PLAN_FILE}.

Build exactly what the requirements describe and nothing more (rule 4): tests locate elements by role, name, \
label and link target, so an extra feature or a second copy of a key element (another link to the same page, \
a repeated button, a translated duplicate of a label) makes them match twice and fail.

{RULES}

{SOP}

## End-to-end tests
- One Playwright test per scenario, in backend/test-e2e/<area>.spec.ts, using \
`import {{ test, expect }} from '@playwright/test'` and shared helpers from backend/test-e2e/helpers.ts.
- Tests start at page.goto('/') in a fresh browser context, use only getByRole/getByLabel/getByText with the \
exact names from the requirements, act by click/fill/press/paste/setInputFiles, and reload the page to \
assert that results persist. Tests run in parallel against one shared server and database: each test \
creates its own objects through the UI with unique names and enters the data it needs; tests may read \
seeded records but never modify them.
- Operate controls the way a user does: open an ARIA combobox by clicking it and click the `option` by role \
and name (use `selectOption` only for a native `<select>`); open menus by clicking their button.
- Pass `{{ exact: true }}` for short or numeric names ('3', 'A1', 'Save') so they do not also match '13', \
'A10' or 'Save rule'.
- Start waiting for an event before the action that triggers it: `const d = page.waitForEvent('download'); \
await button.click(); await d;` (same for popups and file choosers).
- A test that fails must be fixed in the app unless the test contradicts the requirement text.
"""

BUILD_TASK = """Build the product below as one working app in this workspace, end to end.

1. Plan from the outline below, without reading every requirement first: write {plan} (concise) at the level \
of architecture: data model (tables), seed data, API conventions, pages and URLs, shared UI components, and \
an ordered list of feature areas, each with its atomic requirement ids. Order the areas so each one builds on \
finished ones. Leave the details of an area for when you build it.
2. Build the shared base (schema, seeding, page shells, shared components, backend/test-e2e/helpers.ts with \
a unique-name helper), then implement the areas in order as the working procedure describes. When you start \
an area, read its requirements through the requirement tool (all its ids in one call); do not parse \
requirements.md or requirements.yaml yourself.
3. Write decisions down: the design you work out for an area (element structure, names, rules, edge cases) \
goes into {plan} under that area in the same reply as your next tool calls. Reasoning is not kept in the \
workspace; only files are.
4. Delegate proactively (see the subagent tool). Your context is the scarcest resource of this long build: \
everything you read stays in it and makes every later step slower and less focused. Hand to a subagent any \
work that would pull a lot of text into your context but whose result is short (investigating a failure, \
reading many files, reviewing an area, reading long requirement text or reference images), and any work that \
can run in parallel with your next step, such as a later feature area whose files do not overlap yours. \
Keep the critical path yourself.
5. When every area is done, run check without a pattern, fix what fails, then call done.

Reference images named in the requirements are readable under {req_dir}.

## Template files (current content)
{template}

{outline}

## Seed data stated in scenario preconditions
{seeds}"""

REFRESH_TASK = """Continue building the product below as one working app in this workspace; your earlier \
progress is summarised in the next message. Follow {plan}, get requirement text with the requirement tool, \
delegate sidecar work to subagents, and when every area is done run check without a pattern, fix what fails, \
then call done.

## {plan}
{plan_text}

## Code map (every source file with its declarations; read a file only when you need its body)
{outline_code}

{outline}"""


def log(label: str, text: str) -> None:
    with _print_lock:
        print(f"[{label}] {text}", flush=True)


SOURCE_DIRS = ("backend/src", "frontend/src", "backend/test-e2e")
SOURCE_TYPES = {".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".sql", ".json"}
SYMBOL = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|class|interface|type|enum)\s+[\w$]+"
    r"|(?:async\s+)?function\s+[\w$]+\s*\([^)]*\)"
    r"|module\.exports\s*=.*|exports\.[\w$]+\s*="
    r"|(?:router|app)\.(?:get|post|put|patch|delete|use)\(\s*['\"`][^'\"`]*['\"`]"
    r"|CREATE TABLE[^(]*"
    r"|<Route\b[^>]*path=[^>]*>)")


def code_map(root: Path, limit: int = 20000) -> str:
    """Every source file with its line count and top-level declarations (exports, functions, routes, tables).

    Given to each new session so it starts with the layout of the code instead of re-reading it."""
    lines: list[str] = []
    for part in SOURCE_DIRS:
        for path in sorted((root / part).rglob("*")) if (root / part).is_dir() else []:
            if not path.is_file() or path.suffix not in SOURCE_TYPES or "node_modules" in path.parts:
                continue
            text = path.read_text(errors="replace")
            found = [m.group(0).strip()[:120] for line in text.splitlines() if (m := SYMBOL.match(line))]
            lines.append(f"{path.relative_to(root)} ({text.count(chr(10)) + 1} lines)")
            lines.extend(f"    {item}" for item in dict.fromkeys(found[:25]))
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit] + "\n... (map truncated; use grep for the rest)"


def file_texts(root: Path, paths: list[str], limit: int = 40000) -> str:
    """Current content of the given files (those that exist), so a session need not read them first."""
    parts, used = [], 0
    for rel in dict.fromkeys(paths):
        path = root / rel
        if not path.is_file() or path.stat().st_size > limit - used:
            continue
        text = path.read_text(errors="replace")
        used += len(text)
        parts.append(f"--- {rel}\n{text.rstrip()}")
    return "\n\n".join(parts)


SESSIONS: list[LLM] = []  # every model client created in this run, for the usage total


def new_llm(model: str | None = None) -> LLM:
    SESSIONS.append(LLM(model))
    return SESSIONS[-1]


MAX_HELPERS = int(os.environ.get("AGENT_HELPERS", "4"))

SUBAGENT = {"name": "subagent", "description": f"""Start a subagent: another engineer with your model and \
tools who works in the background in this same workspace, so its edits are immediately visible to you. The \
call returns at once; the subagent's final answer arrives later as a message. Up to {MAX_HELPERS} run at once.

Delegate proactively: if at any point you can parallelize work by handing a task to a subagent, do so when it \
could save time or improve quality. Delegate also to keep your own context small: a subagent reads the files, \
logs and requirement text it needs in its own context and returns only its conclusion, while everything you \
read stays in yours for the rest of the build. First decide what you do yourself right now. Keep the critical path local: the step you are \
blocked on, and work that is tightly coupled, urgent or too hard to hand over. Delegate concrete, bounded \
sidecar tasks that materially advance the build and can run while you continue, for example: building a \
later area that touches files you are not editing, drafting the e2e tests of the next area while you \
implement the current one, reviewing a finished area against its requirements, investigating a failure \
(let it read the logs and code and report the root cause and fix), or summarising long requirement text or \
reference images. Run several \
independent subagents at once when their files do not overlap.

Designing the task: make it self-contained and name the concrete output you need. State in the task which files it \
may create or change; keep that set disjoint from what you and other subagents are editing and leave those \
files alone until it finishes. It cannot start subagents of its own. Do not delegate the same unresolved question twice.

After delegating: do meaningful non-overlapping work at once, and do not redo its task yourself. Call \
wait_subagent only when your next step is blocked on the result. When a result arrives, review the files it \
changed before relying on them.""",
            "parameters": {"type": "object", "properties": {
                "task": {"type": "string", "description": "Self-contained instructions and the output to report."},
                "fork_context": {"type": "boolean", "description": "Default false: the subagent starts "
                                 "with only your task, so write it self-contained (the files, requirement ids and "
                                 "facts it needs). Set true only when the task cannot be explained without this "
                                 "conversation; the subagent then carries your whole context."},
                "reasoning_effort": {"type": "string", "enum": ["low", "high", "max"],
                                     "description": "Omit to inherit yours: low for mechanical work, max for "
                                                    "a hard diagnosis."}},
                "required": ["task"]}}
WAIT = {"name": "wait_subagent", "description": "Block until a subagent finishes and return its final answer. "
        "Use only when your next step cannot proceed without it.",
        "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}}
CHECK = {"name": "check", "description": "Build the frontend, start the backend on a fresh database, run the e2e "
         "tests and the static rule checks. Pass pattern (e.g. 'sort.spec') to run only matching test files; "
         "omit it to run the whole suite.",
         "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}}}
REQUIREMENT = {"name": "requirement", "description": "Full text of atomic requirements (description, exact UI "
               "strings, reference images, acceptance scenarios) and the rules of their groups.",
               "parameters": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
                              "required": ["ids"]}}

SUBAGENT_ROLE = """You are now subagent {number}, started by the lead engineer for the task below. The lead \
keeps working in the same workspace, so files may change while you work. {context}Change only the files \
your task covers: the lead and other subagents edit the rest at the same time. subagent and wait_subagent \
belong to the lead and are refused. When finished, call done: its summary is delivered to the lead as your final answer, so make \
it complete and short (findings with file paths and exact names, and every file you changed).

When your task is a review, the hidden tests locate every element by the exact text of the requirements, so \
compare the user interface with the requirement text character by character and treat every difference as a \
defect:
- Accessible names: label text, aria-label, button and link text, headings, tab, menu item and option text \
must equal the quoted requirement string exactly: same characters, spacing, punctuation and language, with no \
added words, units, colons, icons-as-text or translations.
- Alternatives: where the requirement allows several names ("X (also accepts Y)", "X or Y", "X（同时兼容 Y）"), \
the name must be exactly one of them, never a combination such as "X Y" or "X / Y".
- Roles and attributes: the element type the requirement names (link or button, native select or custom \
list, checkbox, password, email), label association (the control is found by its label), default and \
initial values, option lists and their order, required and disabled states, and URLs.
- Messages: error, validation, empty-state and confirmation texts, and where they appear.
- Extras and duplicates: any control, text or link the requirements do not ask for, and any key element that \
appears twice in one view (a second link to the same page, a repeated button, a translated duplicate).
- Flows: each flow must work with only the controls and inputs the requirement names.
Report each defect as file:line, the current text or attribute, and the exact text or attribute the \
requirement demands, quoting the requirement.

## Task
{task}"""


class Helpers:
    """Subagents started with the subagent tool. They never block the lead: results arrive as messages, or on
    request with wait_subagent."""

    def __init__(self, root: Path, req_dir: Path, label: str, extras: dict):
        self.root, self.req_dir, self.label, self.extras = root, req_dir, label, extras
        self.pool = futures.ThreadPoolExecutor(max_workers=MAX_HELPERS)
        self.jobs: dict[int, tuple[str, futures.Future]] = {}
        self.delivered: set[int] = set()
        # numbering continues after a resume, so labels and transcript files stay unique
        found = [int(m[1]) for f in (root / checkpoint.AGENT_DIR).glob(f"{label}-helper*.jsonl")
                 if (m := re.match(rf"{re.escape(label)}-helper(\d+)", f.name))]
        self.first = max(found, default=0) + 1

    def start(self, task: str, effort: str = "", history: list[dict] | None = None) -> int:
        number = self.first + len(self.jobs)
        label = f"{self.label}:helper{number}"
        llm = new_llm()
        if effort in EFFORTS:
            llm.effort = effort
        context = "You have the conversation so far; everything after it is your own work. " if history else ""
        text = SUBAGENT_ROLE.format(number=number, context=context, task=task)
        tools = Tools(self.root, readable=[self.req_dir])
        future = self.pool.submit(loop.run, llm, ENGINEER, text, tools, extras=self.extras, max_steps=20,
                                  hard_limit=60, label=label, history=history,
                                  transcript=checkpoint.Transcript(self.root, label, commits=False))
        self.jobs[number] = (task, future)
        log(label, f"started{' (forked)' if history else ''}: {task[:200]}")
        return number

    def result(self, number: int) -> str:
        task, future = self.jobs[number]
        self.delivered.add(number)
        try:
            summary = future.result()
        except Exception as error:  # the lead decides what to do without it
            summary = f"failed: {type(error).__name__}: {error}"
        return f"Subagent {number} finished (task: {task[:160]}). Final answer:\n{summary}"

    def finished(self) -> list[str]:
        """Results that arrived since the last call."""
        ready = [n for n, (_, f) in self.jobs.items() if f.done() and n not in self.delivered]
        return [self.result(n) for n in ready]

    def running(self) -> list[int]:
        return [n for n, (_, f) in self.jobs.items() if not f.done()]

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


def forked(messages: list[dict], call_id: str) -> list[dict]:
    """The conversation up to the subagent call, with a result for every call of that reply, so a forked
    session starts from a valid history that shares the lead's cached prefix."""
    history = list(messages)
    last = max(i for i, m in enumerate(history) if m["role"] == "assistant")
    answered = {m.get("tool_call_id") for m in history[last:] if m["role"] == "tool"}
    for call in history[last].get("tool_calls") or []:
        if call["id"] not in answered:
            history.append({"role": "tool", "tool_call_id": call["id"], "content":
                            "started you as a subagent" if call["id"] == call_id else "(handled by the lead)"})
    return history


CHECK_LOCK = threading.Lock()  # one build and test run at a time: they share frontend/dist


class Engineer:
    """The session that builds the app, with a check tool, requirement lookup and helpers."""

    def __init__(self, llm: LLM, root: Path, req_dir: Path, tree: spec.Node, label: str, steps: int,
                 task_builder=None):
        self.llm, self.root, self.req_dir, self.tree, self.label = llm, root, req_dir, tree, label
        self.steps, self.task_builder = steps, task_builder
        self.atomics = {a.id: a for a in tree.atomics}
        self.common = frozenset(spec.boilerplate(tree))  # template sentences, stated once in the outline
        self.last_report = ""
        self.built: list[str] = []  # snapshot commit of the last successful build
        self.helpers = Helpers(root, req_dir, label, self.extras(lead=False))
        self.settled = False  # the whole suite passed since the last compaction check

    def check(self, args: dict) -> str:
        pattern = args.get("pattern") or ""
        with CHECK_LOCK:
            ok, report = checks.check(self.root, pattern)
            if report.startswith("build ok"):  # a snapshot of the working tree, without touching it
                found = re.findall(r"\b[0-9a-f]{40}\b", shell("git stash create", self.root, 60)) or \
                    re.findall(r"\b[0-9a-f]{40}\b", shell("git rev-parse HEAD", self.root, 30))
                self.built = found[:1]
            elif self.built and report.startswith("frontend build failed"):
                report += (f"\nThe frontend last built at snapshot {self.built[0][:12]}; `git diff "
                           f"{self.built[0][:12]} -- frontend/src` shows every change since then.")
        self.last_report = report
        self.settled = ok and not pattern
        return ("CHECK PASSED\n" if ok else "CHECK FAILED\n") + report

    def helper_check(self, args: dict) -> str:
        with CHECK_LOCK:
            ok, report = checks.check(self.root, args.get("pattern") or "")
        return ("CHECK PASSED\n" if ok else "CHECK FAILED\n") + report

    def requirement(self, args: dict) -> str:
        wanted = [str(i) for i in args.get("ids") or []]
        unknown = [i for i in wanted if i not in self.atomics]
        if unknown or not wanted:
            return f"ERROR: unknown ids {unknown}; atomic ids are: {', '.join(self.atomics)}"
        rules = spec.shared(self.tree, wanted)
        cards = "\n\n".join(spec.card(self.atomics[i], str(self.req_dir), self.common) for i in wanted)
        return (f"## Rules of the groups these requirements belong to\n{rules}\n\n" if rules else "") + cards

    def subagent(self, args: dict, messages: list[dict], call_id: str) -> str:
        if len(self.helpers.running()) >= MAX_HELPERS:
            return f"ERROR: {MAX_HELPERS} subagents are already running; wait for one with wait_subagent"
        number = self.helpers.start(str(args.get("task", "")), str(args.get("reasoning_effort", "")),
                                    forked(messages, call_id) if args.get("fork_context") else None)
        return f"Subagent {number} started; its final answer will arrive as a message. Keep working."

    def wait_subagent(self, args: dict) -> str:
        number = int(args.get("id", 0))
        if number not in self.helpers.jobs:
            return f"ERROR: no subagent {number}"
        return self.helpers.result(number)

    def on_step(self, _step: int, _messages: list[dict]) -> str | None:
        """Subagent results that arrived since the last step."""
        return "\n\n".join(self.helpers.finished()) or None

    def milestone(self) -> bool:
        settled, self.settled = self.settled, False
        return settled

    def refresh(self) -> tuple[str | None, str]:
        """Fresh task text and the facts a compaction must carry over verbatim."""
        facts = [f"## Latest check report\n{self.last_report[:8000]}"] if self.last_report else []
        running = [f"- subagent {n}: {self.helpers.jobs[n][0][:300]}" for n in self.helpers.running()]
        if running:
            facts.append("## Subagents still running (their results will arrive as messages)\n" + "\n".join(running))
        return (self.task_builder() if self.task_builder else None), "\n\n".join(facts)

    def extras(self, lead: bool) -> dict[str, loop.Extra]:
        """The same tool list for the lead and its subagents (a fork keeps the cached prefix); subagents cannot
        start subagents of their own."""
        def refused(*_args) -> str:
            return "ERROR: only the lead engineer can use this tool; report what it should do in your answer"
        return {"check": loop.Extra(CHECK, self.check if lead else self.helper_check),
                "requirement": loop.Extra(REQUIREMENT, self.requirement),
                "subagent": loop.Extra(SUBAGENT, self.subagent if lead else refused, context=True),
                "wait_subagent": loop.Extra(WAIT, self.wait_subagent if lead else refused)}

    def run(self, task: str, resume: int | str | None = None) -> str:
        extras = self.extras(lead=True)
        try:
            return loop.run(self.llm, ENGINEER, task, Tools(self.root, readable=[self.req_dir]), extras=extras,
                            max_steps=self.steps, on_step=self.on_step, label=self.label,
                            transcript=checkpoint.Transcript(self.root, self.label), resume=resume,
                            refresh=self.refresh, milestone=self.milestone)
        finally:
            self.helpers.close()

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
the tools apply_patch, bash, view_image, check, requirement, subagent, send_subagent, wait_subagent and done. \
Paths are relative to the workspace root. The check tool builds the frontend, starts the backend on a \
fresh database and runs the Playwright tests in backend/test-e2e; the lead engineer never starts servers, browsers or \
e2e runs by hand, while a subagent may, inside one bash command.

## Tool calls
Every reply re-sends the whole conversation, so the number of replies sets the cost and the time of the build. \
Parallelize tool calls whenever possible: one reply may contain many tool calls.
- Gather everything you need in one reply: all the files and searches for the next decision at once, never one \
read per reply, and no second read of a file that is in the conversation and unchanged.
- Write a whole slice in one reply: one apply_patch with its check argument set to the area's spec pattern.

## Subagents
Your context is the most valuable resource of this build: everything you read stays in it and slows every \
later step, while a subagent reads in its own context and returns only its conclusion. Keep one or two \
subagents busy most of the time, and delegate by default work that would pull a lot of text into your context \
for a short result, or that can run while you continue:
- an area is finished: a subagent reviews it against its requirement ids and the list of its files (once, when \
it is finished; never an area still being built or the whole app);
- you start building an area and write its tests with your first slice: a subagent drafts the e2e tests of the \
next area into its spec file;
- a later area touches files you are not editing: a subagent builds it;
- a check fails for a cause not obvious from the report, or you would otherwise run throwaway experiments \
(node -e, temporary test files, logging, a server or browser): a subagent investigates and reports the cause \
and the fix;
- you need to understand more than two or three files you did not just write, long requirement text or \
reference images: a subagent reads them and reports what you need.
Do the critical path yourself: the step you are blocked on, the code of the area you are building, tightly \
coupled or urgent work, and the fixes you know how to make.
Write each task self-contained and name the output you need. Start independent subagents together, as several \
subagent calls in one reply, never one after another, and all of them before any wait_subagent; keep working \
while they run, without redoing their task. Never wait for a subagent that builds an area or investigates a \
failure: such work takes many minutes, and its answer arrives as a message by itself. Give an investigation one \
narrow question (the failing test, its error, the files involved); never delegate the same unresolved question \
twice. When a result arrives, review the files the subagent changed before relying on them.
To correct or extend a subagent's task, use send_subagent instead of starting a new one: a running subagent \
gets the message after its current step, and a finished one continues with what it already read, so send \
follow-up work on the same files (fix what its review found, investigate the next failure there) to it.

{RULES}

{SOP}

## End-to-end tests
- One Playwright test per scenario, in backend/test-e2e/<area>.spec.ts, using \
`import {{ test, expect }} from '@playwright/test'` and shared helpers from backend/test-e2e/helpers.ts.
- Tests start at page.goto('/') in a fresh browser context, use only getByRole/getByLabel/getByText with the \
exact names from the requirements, act by click/fill/press/paste/setInputFiles, and reload the page to \
assert that results persist. Tests run in parallel against one shared server and database (each check \
starts it on a fresh database): tests use the seed accounts and records the scenario names, a scenario that \
changes a seed record is the only test touching it, and other objects are created through the UI with \
unique names.
- Operate controls the way a user does: open an ARIA combobox by clicking it and click the `option` by role \
and name (use `selectOption` only for a native `<select>`); open menus by clicking their button.
- Assert exact texts: `getByText(text, {{ exact: true }})` / `toHaveText`, never `toContainText`, which \
hides extra characters (an icon letter, a prefix) that break an exact accessible name; for each value the \
scenario looks for, the unanchored `getByText(value)` also matches one element.
- Pass `{{ exact: true }}` for short or numeric names ('3', 'A1', 'Save') so they do not also match '13', \
'A10' or 'Save rule'.
- Start waiting for an event before the action that triggers it: `const d = page.waitForEvent('download'); \
await button.click(); await d;` (same for popups and file choosers).
- A test that fails must be fixed in the app unless the test contradicts the requirement text.
- When the same test fails twice, stop changing code until you know why: the check report shows the page for the \
first failures (its elements, roles and names) under the failing test; compare it with what the test looks for. \
Never add debug assertions, logging or other temporary code to tests or the app, and remove any you find.
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
4. Delegate sidecar work to subagents as the Subagents section of your instructions describes.
5. When every area is done, run check without a pattern, fix what fails, then call done.

Reference images named in the requirements are under {req_dir}; look at them with view_image.

## Workspace files (the starter template; read the ones you need)
{template}

{notes}
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

{notes}
{outline}"""


SKILLS = HERE / "skills"  # <name>/SKILL.md (frontmatter: name, description), copied to .agent/skills by setup


def skills() -> dict[str, tuple[str, str]]:
    """Every skill by name: (description, body)."""
    found = {}
    for path in sorted(SKILLS.glob("*/SKILL.md")) if SKILLS.is_dir() else []:
        match = re.match(r"---\n(.*?)\n---\n(.*)", path.read_text(), re.S)
        if not match:
            continue
        meta = dict(re.findall(r"^(\w+):\s*(.+)$", match[1], re.M))
        found[meta.get("name", path.parent.name).strip()] = (meta.get("description", "").strip(), match[2].strip())
    return found


def skills_section() -> str:
    """The list of skills the task shows; the sessions read the files they need. Empty without skills."""
    listed = "\n".join(f"- `.agent/skills/{name}/SKILL.md`: {description}"
                       for name, (description, _) in skills().items())
    if not listed:
        return ""
    return ("## Skills (general techniques for building web products)\nRead a skill with `cat` when its "
            "description applies, before the work it covers; read several in one command. Follow a skill you read; "
            f"where it conflicts with the requirement text, the requirement wins.\n{listed}\n\n")


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


def new_llm(model: str | None = None) -> LLM:
    return LLM(model)


MAX_HELPERS = int(os.environ.get("AGENT_HELPERS", "4"))
HELPER_STEPS = 25  # a subagent is asked to wrap up here; the lead can continue it with send_subagent
WRAP_UP = (f"You have used {HELPER_STEPS} steps. Wrap up now: finish the item you are on in a few steps, then "
           "call done with your findings, every file you changed and what is left; the lead can continue you.")

SUBAGENT = {"name": "subagent", "description": f"""Start a subagent: another engineer with your model and \
tools who works in the background in this same workspace, so its edits are immediately visible to you. The \
call returns at once; the subagent's final answer arrives later as a message. Up to {MAX_HELPERS} run at once, \
and a subagent cannot start subagents of its own. State in the task which files it may create or change; keep \
that set disjoint from what you and other subagents are editing and leave those files alone until it finishes.""",
            "parameters": {"type": "object", "properties": {
                "task": {"type": "string", "description": "Self-contained instructions: the goal, the files and "
                         "requirement ids involved, the files it may change, and the output to report."},
                "fork_context": {"type": "boolean", "description": "Default false: the subagent starts "
                                 "with only your task, so write it self-contained (the files, requirement ids and "
                                 "facts it needs). Set true only when the task cannot be explained without this "
                                 "conversation; the subagent then carries your whole context."},
                "reasoning_effort": {"type": "string", "enum": ["low", "high", "max"],
                                     "description": "Default: yours (high). low for mechanical work, max for "
                                                    "a hard diagnosis."}},
                "required": ["task"]}}
SEND = {"name": "send_subagent", "description": "Send a follow-up message to a subagent you started: a "
        "correction, extra instructions, or a new task that builds on what it already read. A running subagent "
        "receives it after its current step. A finished subagent continues its own conversation with the message "
        "as its next task, keeping everything it read, and its next final answer arrives as a message again; this "
        "needs a free subagent slot. Returns at once.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer", "description": "Subagent number, as returned by the subagent tool."},
            "message": {"type": "string", "description": "The instructions, self-contained apart from what the "
                        "subagent already knows from its task and its own work."}},
            "required": ["id", "message"]}}
WAIT = {"name": "wait_subagent", "description": "Block until a subagent finishes and return its final answer. "
        "Results otherwise arrive by themselves as a message after one of your steps, so use this only when your "
        "next step cannot proceed without the result; nothing else happens in your session while you wait.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer", "description": "Subagent number, as returned by the subagent tool."}},
            "required": ["id"]}}
CHECK = {"name": "check", "description": "Build the frontend (npm run build), start the backend with npm start on "
         "a fresh empty database, run the Playwright e2e tests in backend/test-e2e against it (4 workers, 15 s per "
         "test, one retry) and the static rule checks. A whole-suite run reruns its failures one at a time, so "
         "failures caused by load are reported as flaky. Takes about half a minute for one spec file and several "
         "minutes for the whole suite; one check runs at a time across you and your subagents. The report starts "
         "with CHECK PASSED or CHECK FAILED and lists build errors, failed tests with their errors and pending "
         "locators, uncaught browser errors and rule violations.",
         "parameters": {"type": "object", "properties": {
             "pattern": {"type": "string", "description": "Run only test files whose path matches, e.g. "
                         "'sort.spec' or 'sheets'; several files in one run with 'sort.spec|filter.spec', not one "
                         "check per file. Default: empty, the whole suite."}}}}
REQUIREMENT = {"name": "requirement", "description": "Full text of atomic requirements: the description (the "
               "acceptance rule), exact UI strings, reference image paths, acceptance scenarios, and the rules of "
               "the groups they belong to. Ask for all the ids of a feature area in one call.",
               "parameters": {"type": "object", "properties": {
                   "ids": {"type": "array", "items": {"type": "string"},
                           "description": "Atomic requirement ids from the outline, e.g. [\"REQ-1-1-1\", \"REQ-1-2\"]."}},
                   "required": ["ids"]}}

SUBAGENT_ROLE = """{notes}## Your role
You are a subagent, started by the lead engineer for the task at the end of this message. The lead keeps \
working in the same workspace, so files may change while you work. Change only the files your task covers: the \
lead and other subagents edit the rest at the same time. The lead may send you further messages while you work; \
follow them. subagent, send_subagent and wait_subagent belong to the lead and are refused. Unlike the lead, you \
may start the backend or a browser script for an experiment, inside one bash command: its process group is \
killed when the command ends, so start, use and stop it there, on a free port.
Work in few steps: read every file you need in one reply (several reads at once), not one file per step. Call \
done when your task is finished, or after a coherent part of a large one: its summary is delivered to the lead as \
your final answer, so make it complete and short (findings with file paths and exact names, every file you \
changed, and what is left); the lead can continue you with send_subagent, so stopping early loses nothing.

When your task is a review, read the requirement text and the files your task names (grep for the rest), \
fix the defects you find in those files unless the task says report only, and add no tests: run check, \
with the area's pattern, only after you changed a file. When nothing differs, say so and call done. Quoted \
requirement strings are exact accessible names and messages, so compare the user interface with the \
requirement text character by character and treat every difference as a defect:
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

## Task of subagent {number}
{task}"""
FORKED = "You have the conversation so far; everything after it is your own work, as a subagent.\n\n"


class Helpers:
    """Subagents started with the subagent tool. They never block the lead: results arrive as messages, or on
    request with wait_subagent. send_subagent reaches a running subagent after its current step, and continues a
    finished one in its own conversation."""

    def __init__(self, root: Path, req_dir: Path, label: str, extras: dict, notes: str = ""):
        self.root, self.req_dir, self.label, self.extras, self.notes = root, req_dir, label, extras, notes
        self.pool = futures.ThreadPoolExecutor(max_workers=MAX_HELPERS)
        self.jobs: dict[int, tuple[str, futures.Future]] = {}
        self.delivered: set[int] = set()
        self.lock = threading.Lock()  # guards inbox and active: a message never lands after a subagent's last look
        self.inbox: dict[int, list[str]] = {}
        self.active: set[int] = set()  # subagents that still take messages in their running session
        self.sessions: dict[int, tuple[LLM, list[dict], int]] = {}  # model, final messages and turn of finished ones
        self.roles: dict[int, str] = {}  # each subagent's role and task: its first message again after a compaction
        self.stop = threading.Event()  # set when the lead's session ends
        # numbering continues after a resume, so labels and transcript files stay unique
        found = [int(m[1]) for f in (root / checkpoint.AGENT_DIR).glob(f"{label}-helper*.jsonl")
                 if (m := re.match(rf"{re.escape(label)}-helper(\d+)", f.name))]
        self.first = max(found, default=0) + 1

    def start(self, task: str, effort: str = "", history: list[dict] | None = None) -> int:
        number = self.first + len(self.jobs)
        llm = new_llm()
        if effort in EFFORTS:
            llm.effort = effort
        self.roles[number] = SUBAGENT_ROLE.format(number=number, notes=self.notes, task=task)
        text = FORKED + self.roles[number] if history else self.roles[number]
        with self.lock:
            self.active.add(number)
        self.jobs[number] = (task, self.pool.submit(self.work, number, llm, text, history, 1))
        log(f"{self.label}:helper{number}", f"started{' (forked)' if history else ''}: {task[:200]}")
        return number

    def work(self, number: int, llm: LLM, text: str, history: list[dict] | None, turn: int) -> str:
        """Run the subagent until it calls done with no message from the lead waiting."""
        while True:
            label = f"{self.label}:helper{number}" + (f"-{turn}" if turn > 1 else "")
            final: list[dict] = []
            try:
                summary = loop.run(llm, ENGINEER, text, Tools(self.root, readable=[self.req_dir]),
                                   extras=self.extras, max_steps=HELPER_STEPS, hard_limit=60, label=label,
                                   history=history, final=final,
                                   on_step=lambda step, _messages: self.take(number, step),
                                   refresh=lambda: (self.roles[number], ""),
                                   transcript=checkpoint.Transcript(self.root, label, commits=False))
            except BaseException:  # a failed subagent takes no more messages
                with self.lock:
                    self.active.discard(number)
                    self.inbox.pop(number, None)
                raise
            with self.lock:
                pending = self.inbox.pop(number, [])
                if not pending or self.stop.is_set():
                    self.active.discard(number)
                    self.sessions[number] = (llm, final, turn)
                    return summary
            history, text, turn = final, follow_up(pending), turn + 1

    def take(self, number: int, step: int = 0) -> str | None:
        """Messages from the lead waiting for subagent `number`, and the wrap-up request once its step budget is
        used, as one user message. Raises once the lead's session has ended, so the subagent changes no more files."""
        if self.stop.is_set():
            raise RuntimeError("the lead's session ended")
        with self.lock:
            pending = self.inbox.pop(number, [])
        parts = ([follow_up(pending)] if pending else []) + ([WRAP_UP] if step == HELPER_STEPS else [])
        return "\n\n".join(parts) or None

    def full(self) -> str:
        """The error for a new or continued subagent when every slot is taken, else empty."""
        if len(self.running()) >= MAX_HELPERS:
            return f"ERROR: {MAX_HELPERS} subagents are already running; wait for one with wait_subagent"
        return ""

    def send(self, number: int, message: str) -> str:
        with self.lock:
            if number in self.active:
                self.inbox.setdefault(number, []).append(message)
                self.jobs[number] = (message, self.jobs[number][1])  # the latest instruction, for listings
                return f"Message queued for subagent {number}; it receives it after its current step."
        if error := self.full():
            return error
        if number not in self.sessions:
            return f"ERROR: subagent {number} ended without a conversation to continue (it failed); start a new one"
        previous = "" if number in self.delivered else f"\n\nIts previous final answer:\n{self.result(number)}"
        llm, history, turn = self.sessions.pop(number)
        with self.lock:
            self.active.add(number)
        self.delivered.discard(number)
        self.jobs[number] = (message, self.pool.submit(self.work, number, llm, follow_up([message]), history, turn + 1))
        log(f"{self.label}:helper{number}", f"continued: {message[:200]}")
        return f"Subagent {number} continues with your message; its final answer will arrive as a message.{previous}"

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
        """Stop the subagents: a running one stops at its next step boundary (see take), and close waits for that,
        so no file changes after the lead's session ends."""
        self.stop.set()
        self.pool.shutdown(wait=True, cancel_futures=True)


def follow_up(messages: list[str]) -> str:
    return "\n\n".join(f"Message from the lead engineer:\n{m}" for m in messages)


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


RESUMED = ("The build was interrupted and resumes here. The subagents started before the interruption are gone: "
           "their results will not arrive and send_subagent cannot reach them. Check what they changed (git status, "
           "git diff) and start new subagents for their unfinished work.")
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
        self.helpers = Helpers(root, req_dir, label, self.extras(lead=False), skills_section())
        self.settled = False  # the whole suite passed since the last compaction check

    def check(self, args: dict, lead: bool = True) -> str:
        pattern = str(args.get("pattern") or "").strip()
        pattern = "" if pattern.lower() == "all" else pattern  # as apply_patch's check argument
        with CHECK_LOCK:
            ok, report = checks.check(self.root, pattern)
            if lead and report.startswith("build ok"):  # a snapshot of the working tree, without touching it
                found = re.findall(r"\b[0-9a-f]{40}\b", shell("git stash create", self.root, 60)) or \
                    re.findall(r"\b[0-9a-f]{40}\b", shell("git rev-parse HEAD", self.root, 30))
                self.built = found[:1]
            elif lead and self.built and report.startswith("frontend build failed"):
                report += (f"\nThe frontend last built at snapshot {self.built[0][:12]}; `git diff "
                           f"{self.built[0][:12]} -- frontend/src` shows every change since then.")
        if lead:
            self.last_report = report
            self.settled = ok and not pattern
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
        if error := self.helpers.full():
            return error
        number = self.helpers.start(str(args.get("task", "")), str(args.get("reasoning_effort", "")),
                                    forked(messages, call_id) if args.get("fork_context") else None)
        return f"Subagent {number} started; its final answer will arrive as a message. Keep working."

    def send_subagent(self, args: dict) -> str:
        number, message = int(args.get("id", 0)), str(args.get("message", "")).strip()
        if number not in self.helpers.jobs:
            return f"ERROR: no subagent {number}"
        if not message:
            return "ERROR: message is empty"
        return self.helpers.send(number, message)

    def wait_subagent(self, args: dict) -> str:
        number = int(args.get("id", 0))
        if number not in self.helpers.jobs:
            return f"ERROR: no subagent {number}"
        return self.helpers.result(number)

    def on_step(self, _step: int, _messages: list[dict]) -> str | None:
        """Subagent results that arrived since the last step."""
        return "\n\n".join(self.helpers.finished()) or None

    def refuse_done(self) -> str | None:
        running = self.helpers.running()
        if running:
            return (f"ERROR: done refused: subagents {', '.join(map(str, running))} are still running and would keep "
                    "changing files after the build ends. Wait for them with wait_subagent, or keep working until "
                    "their results arrive as messages, then call done.")
        return None

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
        return {"check": loop.Extra(CHECK, lambda args: self.check(args, lead)),
                "requirement": loop.Extra(REQUIREMENT, self.requirement),
                "subagent": loop.Extra(SUBAGENT, self.subagent if lead else refused, context=True),
                "send_subagent": loop.Extra(SEND, self.send_subagent if lead else refused),
                "wait_subagent": loop.Extra(WAIT, self.wait_subagent if lead else refused)}

    def run(self, task: str, resume: int | str | None = None) -> str:
        extras = self.extras(lead=True)
        try:
            tools = Tools(self.root, readable=[self.req_dir], experiments=False)
            return loop.run(self.llm, ENGINEER, task, tools, extras=extras, max_steps=self.steps, on_step=self.on_step, label=self.label,
                            transcript=checkpoint.Transcript(self.root, self.label), resume=resume, note=RESUMED,
                            refresh=self.refresh, milestone=self.milestone, refuse_done=self.refuse_done)
        finally:
            self.helpers.close()

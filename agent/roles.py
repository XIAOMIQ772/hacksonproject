"""Agent roles: planner, worker (test-driven), advisor (read-only reviewer) and integrator."""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

import checkpoint
import checks
import dag
import loop
import spec
from llm import LLM
from tools import Tools, clip, shell

HERE = Path(__file__).resolve().parent
RULES = (HERE / "rules.md").read_text()
SOP = (HERE / "sop.md").read_text()
PLAN_FILE = "PLAN.md"
_print_lock = threading.Lock()

ENGINEER = f"""You are a senior full-stack engineer working in a git workspace that contains a React (Vite) \
frontend in frontend/ and an Express + SQLite backend in backend/ (dependencies are installed). Work with \
the tools read, write, edit, apply, bash, check, set_reasoning and done. Paths are relative to the workspace root. Do not start \
servers or browsers yourself; the check tool builds the frontend, starts the backend on a fresh database and \
runs the Playwright tests in backend/test-e2e.

Be economical: read only files you need, write whole files when creating them, prefer small edits after. \
Keep code consistent with {PLAN_FILE}.

Build exactly what the requirements describe and nothing more (rule 4): tests locate elements by role, name, \
label and link target, so an extra feature or a second copy of a key element (another link to the same page, \
a repeated button, a translated duplicate of a label) makes them match twice and fail.

{RULES}

{SOP}

## End-to-end tests
- One Playwright test per scenario, in backend/test-e2e/<node>.spec.ts, using \
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

ADVISOR = f"""You are a staff engineer reviewing another engineer's work on a web app built from a \
requirements document. You can read files and run read-only shell commands (git diff, git log, grep, ls); \
never modify files. Be concrete: cite file paths, element names and requirement text. Keep the answer short.

Check every view the change touches for anything the requirements do not ask for (features, controls, text, \
links) and for key elements that appear more than once (two links to the same page, repeated buttons, a \
translated duplicate of a label); both are defects, because tests locate elements by role, name, label and link \
target and fail when a locator matches twice. Also walk each flow using only the controls the requirement \
names: a flow must not depend on an input the requirement does not mention (for example a required name field on \
a page described only by its submit button).

The team follows these rules:
{RULES}

Finish by calling submit_verdict (approve, issues: specific problems each with its fix, advice: next steps), \
then done."""

PLANNER_TASK = """Plan the implementation of the product below for a team of engineers who will work in \
parallel, each on one node of a task graph, in separate git branches that are merged afterwards.

1. Write {plan} (concise) describing the architecture every engineer must follow:
   - data model (tables), seed data, API conventions, pages and URLs, shared UI components;
   - extension points that let features be added in separate files so parallel work rarely touches the \
same file: e.g. one backend route module per feature registered from a directory, one frontend module per \
feature registered in a single list, table definitions per module;
   - for every atomic requirement: the page or dialog it lives on and the quoted names it needs.
2. Call submit_plan with JSON {{"nodes": [{{"id", "title", "requirements": [atomic ids], "depends_on": \
[node ids], "files": [files the node creates or changes], "notes"}}]}}. Rules: every atomic requirement \
belongs to exactly one node; a node usually covers one to three closely related requirements; a node that \
changes behaviour another node builds on depends on it; nodes that would edit the same files should depend \
on each other; do not include a foundation node (the foundation is built next, from {plan}, before any node).

Do not implement anything yourself.

The workspace currently contains these template files:
{template}

Requirement files, including reference images, are readable under {req_dir}.

{outline}

## Seed data stated in scenario preconditions
{seeds}

## Atomic requirements
{cards}"""

FOUNDATION_TASK = """Build the foundation described in {plan}: database schema and startup seeding, the \
extension points (route and page registries), routing and page shells, the shared UI components some \
requirement needs, and backend/test-e2e/helpers.ts with a unique-name helper. Add \
backend/test-e2e/foundation.spec.ts with one smoke test that opens '/' and checks the main heading. Do not \
implement feature behaviour that belongs to the task-graph nodes. Run check until it passes, then call done.

## {plan}
{plan_text}

## Template files (current content)
{template}

## Task graph (for orientation)
{graph}

## Product-wide rules from the requirement groups (the shared shell must satisfy them)
{shared}"""

NODE_TASK = """Implement node {id} ("{title}") of the task graph on top of the existing app, following \
{plan}. You work on your own branch; other engineers implement other nodes in parallel, so stay within this \
node's scope and prefer the files it owns: {files}. Planner notes: {notes}
Your checkout is the current directory; read and change files only there (and read the requirement files). \
Branches of other nodes (node/*) are unfinished work in progress: do not inspect them or depend on them; \
build on your checkout, and the orchestrator merges finished work.

Write the e2e tests for every scenario of this node's requirements in backend/test-e2e/{id}.spec.ts, \
implement until check with pattern "{id}.spec" passes, keep earlier features working, then call done. An \
advisor reviews your work when you call done.

## {plan}
{plan_text}

## Code map (every source file with its declarations; read a file only when you need its body)
{outline}

## Current content of the files this node owns and the test helpers
{owned}

{cards}"""


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


def advisor_llm() -> LLM:
    advisor = new_llm(os.environ.get("ADVISOR_MODEL") or None)
    advisor.effort = os.environ.get("ADVISOR_REASONING_EFFORT", "high")  # a wrong verdict costs a whole node
    return advisor


def advise(root: Path, req_dir: Path, mode: str, context: str, label: str) -> dict:
    """Read-only review. `mode` is "review" (the worker says it is done), "diagnose" (the worker is stuck) or
    "judge" (a merge left failing tests)."""
    ask = {
        "review": "Review the work below. Approve only if every requirement of the node is implemented with the "
                  "exact quoted names and roles, errors and persistence behave as required, the tests really "
                  "assert those names (not weaker substitutes) and isolate their data, no control was added that "
                  "the requirements do not ask for (especially a second link or button to the same destination "
                  "or action), and earlier features are not broken.",
        "diagnose": "The engineer is stuck: the tests have not improved for several checks. Find the root cause "
                    "from the failure report and the code (it may be the test, the app, or the test setup) and "
                    "give the next concrete steps. Set approve to false.",
        "judge": "A node branch was just merged into the integration branch and the full suite is not clean: "
                 "some tests that passed before now fail, or the node's own tests fail. Decide whether to keep "
                 "the merge. Compare each failing test with the requirement text: a test whose expectation the "
                 "requirements no longer support is stale; a test that still matches the requirements shows a "
                 "real regression. Set approve to true to keep the merge; then list in issues the follow-up "
                 "fixes another engineer must make (stale tests to update, small gaps), or leave issues empty. "
                 "Set approve to false to revert when the branch breaks required behaviour; then issues tell "
                 "the author what to fix.",
    }[mode]
    task = (f"{ask}\n\nThe work to review is in the current directory ({root}); stay there. Requirements are "
            f"readable under {req_dir}. The diff is below: read other files only when you need surrounding code, "
            f"and batch independent reads in one reply.\n\n{context}")
    tools = Tools(root, readable=[req_dir], read_only=True)
    verdict: dict = {}

    def submit(args: dict) -> str:
        if not isinstance(args.get("approve"), bool):
            return "ERROR: approve must be true or false"
        verdict.update(approve=args["approve"], issues=[str(i) for i in args.get("issues") or []],
                       advice=str(args.get("advice", "")))
        return "Verdict recorded. Call done."
    verdict_tool = loop.Extra({"name": "submit_verdict", "description": "Record the review verdict.",
                               "parameters": {"type": "object", "properties": {
                                   "approve": {"type": "boolean"},
                                   "issues": {"type": "array", "items": {"type": "string"}},
                                   "advice": {"type": "string"}}, "required": ["approve", "issues"]}}, submit)
    summary = loop.run(advisor_llm(), ADVISOR, task, tools, extras={"submit_verdict": verdict_tool}, max_steps=15,
                       on_done=lambda _s: "" if verdict else "Call submit_verdict first.", label=f"{label}:advisor")
    if not verdict:  # the session ended without a verdict (step limit)
        verdict = {"approve": {"review": True, "diagnose": False}.get(mode), "issues": [], "advice": summary}
    log(label, f"advisor {mode}: approve={verdict.get('approve')} issues={len(verdict.get('issues') or [])}")
    return verdict


def feedback(verdict: dict) -> str:
    issues = "\n".join(f"- {i}" for i in verdict.get("issues") or [])
    return f"Advisor feedback:\n{issues}\n{verdict.get('advice', '')}".strip()


UNCHECKED_LIMIT = 12


class Worker:
    """A test-driven engineering session with a check tool, advisor review on done and help when stuck."""

    def __init__(self, llm: LLM, root: Path, req_dir: Path, label: str, pattern: str, cards: str, steps: int,
                 base: str, reviews: int = 2, stuck_after: int = 3, task_builder=None):
        self.llm, self.root, self.req_dir, self.label = llm, root, req_dir, label
        self.pattern, self.cards, self.steps = pattern, cards, steps
        self.reviews_left, self.diagnoses_left, self.stuck_after = reviews, 2, stuck_after
        self.history: list[tuple[int, int]] = []  # (passed, total) per check
        self.last_report = ""
        self.task_builder = task_builder  # rebuilds the task with a fresh code map after a compaction
        self.last_feedback = ""  # most recent advisor verdict text, kept across compactions
        self.unchecked = 0  # steps since the last check
        self.base = base  # commit the work started from; the advisor reviews the diff against it

    def check(self, args: dict) -> str:
        self.unchecked = 0
        ok, report = checks.check(self.root, args.get("pattern") or "")
        if report.startswith("build ok"):
            numbers = report.split("e2e ", 1)[1].split(" ", 1)[0] if "e2e " in report else "0/0"
            passed, total = (int(x) for x in numbers.split("/"))
            self.history.append((passed, total))
        else:
            self.history.append((0, -1))
        self.last_report = report
        return ("CHECK PASSED\n" if ok else "CHECK FAILED\n") + report

    def context(self) -> str:
        stat = shell(f"git diff --stat {self.base} -- . ':!*.lock' | tail -40", self.root, 60)
        diff = shell(f"git diff {self.base} -- . ':!*.lock' ':!*.json'", self.root, 60)
        return (f"## Node requirements\n{self.cards}\n\n## Last check report\n{self.last_report[:5000]}\n\n"
                f"## Files changed since {self.base[:8]}\n{stat}\n\n## Full diff (clipped when very large)\n"
                f"{clip(diff, 60000)}")

    def on_done(self, _summary: str) -> str:
        if not self.history:
            return "Run the check tool before calling done."
        if self.reviews_left <= 0:
            return ""
        self.reviews_left -= 1
        verdict = advise(self.root, self.req_dir, "review", self.context(), self.label)
        if verdict.get("approve"):
            return ""
        self.last_feedback = feedback(verdict)
        return self.last_feedback + "\nAddress this, run check, then call done."

    def on_step(self, _step: int) -> str | None:
        self.unchecked += 1
        if self.unchecked >= UNCHECKED_LIMIT:
            self.unchecked = 0
            return (f"{UNCHECKED_LIMIT} steps without running check. Run check now: small verified increments "
                    "are cheaper to fix than a large untested change.")
        recent = self.history[-self.stuck_after:]
        if (len(recent) < self.stuck_after or any(p == t and t > 0 for p, t in recent)
                or len({p for p, _ in recent}) > 1):
            return None
        if self.diagnoses_left <= 0:
            self.history.append((-1, -1))
            self.reviews_left = 0  # finishing because stuck: the merge judge looks at the result instead
            return ("Still no progress after two reviews. Stop here: make sure the app builds and starts and the "
                    "passing tests still pass, then call done with an honest summary of what fails and why. The "
                    "orchestrator decides whether to continue this work later with fresh information.")
        self.diagnoses_left -= 1
        self.history.append((-1, -1))  # do not trigger again on the same run of checks
        self.last_feedback = feedback(advise(self.root, self.req_dir, "diagnose", self.context(), self.label))
        return self.last_feedback

    def refresh(self) -> tuple[str | None, str]:
        """Fresh task text and the facts a compaction must carry over verbatim."""
        facts = [f"## Latest check report\n{self.last_report[:8000]}"] if self.last_report else []
        if self.last_feedback:
            facts.append(f"## Most recent reviewer feedback (may already be addressed)\n{self.last_feedback}")
        return (self.task_builder() if self.task_builder else None), "\n\n".join(facts)

    def run(self, task: str, resume: int | str | None = None, note: str | None = None) -> str:
        check_tool = loop.Extra(
            {"name": "check", "description": "Build the frontend, start the backend on a fresh database, run the "
             f"e2e tests and the static rule checks. Pass pattern (e.g. '{self.pattern or 'foundation'}') to run "
             "only matching test files; omit it to run the whole suite.",
             "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}}}, self.check)
        return loop.run(self.llm, ENGINEER, task, Tools(self.root, readable=[self.req_dir]), extras={"check": check_tool},
                 max_steps=self.steps, on_done=self.on_done, on_step=self.on_step, label=self.label,
                 transcript=checkpoint.Transcript(self.root, self.label), resume=resume, note=note,
                 refresh=self.refresh)


def plan(llm: LLM, root: Path, req_dir: Path, tree: spec.Node, template: str, steps: int) -> list[dag.Node]:
    atomic_ids = [a.id for a in tree.atomics]
    result: dict = {}

    def submit(args: dict) -> str:
        nodes, problems = dag.parse(args.get("plan", ""), atomic_ids)
        if problems:
            return "Plan rejected:\n" + "\n".join(f"- {p}" for p in problems)
        result["nodes"] = nodes
        (root / checkpoint.AGENT_DIR / "plan.json").write_text(args["plan"])
        return f"Plan accepted: {len(nodes)} nodes. Call done."

    submit_tool = loop.Extra({"name": "submit_plan", "description": "Submit the task graph as JSON text.",
                              "parameters": {"type": "object", "properties": {"plan": {"type": "string"}},
                                             "required": ["plan"]}}, submit)
    task = PLANNER_TASK.format(plan=PLAN_FILE, template=template, req_dir=req_dir, outline=spec.outline(tree),
                               seeds=spec.seed_facts(tree) or "- none",
                               cards="\n\n".join(f"### {a.id} {a.name} ({len(a.scenarios)} scenarios)\n"
                                                 f"{a.description}" for a in tree.atomics))
    loop.run(llm, ENGINEER, task, Tools(root, readable=[req_dir]), extras={"submit_plan": submit_tool},
             max_steps=steps, on_done=lambda _s: "" if result else "Submit an accepted plan first.",
             label="plan", transcript=checkpoint.Transcript(root, "plan"), resume="last")
    return result.get("nodes") or load_plan(root, atomic_ids)


def load_plan(root: Path, atomic_ids: list[str]) -> list[dag.Node]:
    path = root / checkpoint.AGENT_DIR / "plan.json"
    if not path.exists():
        return []
    nodes, problems = dag.parse(path.read_text(), atomic_ids)
    return [] if problems else nodes


INTEGRATE_TASK = """Merging branch node/{id} into the integration branch produced conflicts in: {files}.
Resolve every conflict so that both sides' features keep working (keep both sets of routes, registrations, \
tests and helpers), remove all conflict markers, run check without a pattern, then call done. Do not commit; \
the orchestrator commits."""

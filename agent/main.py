"""ARC-Bench coding agent: requirements directory in, React + Express app out.

    python3 main.py REQUIREMENTS_DIR --output-dir OUTPUT_DIR [--type web]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

import checks
import loop
import spec
from llm import LLM, FatalModelError
from tools import Tools, shell

HERE = Path(__file__).resolve().parent
RULES = (HERE / "rules.md").read_text()
PLAN_FILE = "PLAN.md"

SYSTEM = f"""You are a senior full-stack engineer building a production web app from a requirements \
document, inside a workspace that already contains a React (Vite) frontend in frontend/ and an Express + \
SQLite backend in backend/ (dependencies are installed). Work with the tools: read, write, edit, bash, \
check, done. Paths are relative to the workspace root. Do not start servers yourself; the check tool builds \
the frontend, starts the backend on a fresh database and runs the Playwright tests in backend/test-e2e.

Be economical: read only files you need, write whole files when creating them, prefer small edits after. \
Keep code simple and consistent with {PLAN_FILE}.

{RULES}

## Acceptance tests you write
- One Playwright test per scenario of the requirement you implement, in backend/test-e2e/<requirement-group>.spec.ts, \
using `import {{ test, expect }} from '@playwright/test'` and shared helpers from backend/test-e2e/helpers.ts.
- Tests start at page.goto('/') in a fresh browser context, use only getByRole/getByLabel/getByText with the \
exact names from the requirements, act by click/fill/press/paste/setInputFiles, and reload the page to \
assert that results persist. Tests create their own objects with unique names instead of relying on \
state left by other tests; seeded records are only read or used where the requirement says they exist.
- A test that fails must be fixed in the app unless the test contradicts the requirement text.
"""


def run_check(root: Path, state: dict, pattern: str = "") -> str:
    ok, report = checks.check(root, pattern)
    state["checked"], state["ok"] = True, ok
    return ("CHECK PASSED\n" if ok else "CHECK FAILED\n") + report


def session(llm: LLM, tools: Tools, root: Path, task: str, label: str, steps: int, pattern: str = "") -> bool:
    state = {"checked": False, "ok": False}
    check_tool = loop.Extra(
        {"name": "check", "description": "Build the frontend, start the backend on a fresh database, run "
         "the e2e tests (optionally only files matching `pattern`, e.g. 'REQ-2-1') and the static rule checks.",
         "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}}},
        lambda args: run_check(root, state, args.get("pattern", pattern)))

    def on_done(_summary: str) -> str:
        return "" if state["checked"] else "Run the check tool before calling done."

    loop.run(llm, SYSTEM, task, tools, extras={"check": check_tool}, max_steps=steps,
             on_done=on_done, label=label)
    return state["ok"]


def commit(root: Path, message: str) -> None:
    shell(f"git add -A && git commit -qm {message!r} --allow-empty", root, 60)


def restore_if_broken(root: Path) -> None:
    """Deliver the last committed state that builds when the working tree no longer does."""
    if not checks.build(root):
        return
    print("[agent] build broken; restoring the last commit", flush=True)
    shell("git reset -q --hard HEAD && git clean -qfd -e node_modules", root, 60)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("requirement_path", nargs="?", default=os.environ.get("ARCBENCH_TASK_DIR", "requirements"))
    parser.add_argument("--output-dir", default=os.environ.get("ARCBENCH_OUTPUT_DIR", "."))
    parser.add_argument("--type", default=os.environ.get("ARCBENCH_TASK_TYPE", "web"))
    parser.add_argument("--steps", type=int, default=int(os.environ.get("AGENT_STEPS", "45")))
    args = parser.parse_args()
    started = time.time()
    req_dir, root = Path(args.requirement_path).resolve(), Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for item in (HERE / "template").iterdir():
        if not (root / item.name).exists():
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, root / item.name)
    if not (root / ".gitignore").exists():
        (root / ".gitignore").write_text(".arc/\nrequirements/\nnode_modules/\ndist/\n*.db\n")
    shell("git init -q 2>/dev/null; git config user.email agent@local; git config user.name agent", root, 30)
    problem = checks.install(root)
    if problem:
        print(problem, flush=True)
    commit(root, "template")

    tree = spec.load(req_dir)
    groups = spec.groups(tree)
    llm = LLM()
    tools = Tools(root, readable=[req_dir])
    print(f"[agent] {len(tree.atomics)} atomic requirements in {len(groups)} groups", flush=True)
    try:
        foundation = f"""Plan and lay the foundation for the whole product below.

1. Write {PLAN_FILE} (concise): data model (tables), seed data, API routes, pages and URLs, shared UI \
components, and which files each requirement group will touch.
2. Implement the foundation: database schema and startup seeding, API skeleton, routing and page shells, \
the shared components required by the rules (Combobox, Menu, Dialog, Tabs, and Grid if needed), and \
backend/test-e2e/helpers.ts with a unique-name helper.
3. Add backend/test-e2e/foundation.spec.ts with one smoke test that opens '/' and checks the main heading, \
then run check until it passes and call done.

Requirement files are also readable under {req_dir}.

{spec.outline(tree)}

## All atomic requirements (descriptions)
""" + "\n\n".join(f"### {a.id} {a.name}\n{a.description}" for a in tree.atomics)
        session(llm, tools, root, foundation, "foundation", args.steps + 20)
        restore_if_broken(root)
        commit(root, "foundation")

        for group in groups:
            ids = ", ".join(a.id for a in group.atomics)
            task = f"""Implement requirement group {group.id} ({ids}) on top of the existing app.
First read {PLAN_FILE} and the files you will change. Write the e2e tests for every scenario in \
backend/test-e2e/{group.id}.spec.ts, implement until `check` with pattern "{group.id}.spec" passes, keep \
earlier features working, update {PLAN_FILE} if the design changes, then call done.

{spec.group_card(group)}"""
            session(llm, tools, root, task, group.id, args.steps, pattern=f"{group.id}.spec")
            restore_if_broken(root)
            commit(root, group.id)

        ok, report = checks.check(root)
        print(f"[agent] final check: {'passed' if ok else 'failed'}\n{report[:3000]}", flush=True)
        if not ok:
            fix = f"""The full acceptance check fails. Fix the app (not the tests, unless a test contradicts \
the requirement) until check passes, then call done.

{report}"""
            session(llm, tools, root, fix, "final-fix", args.steps)
            restore_if_broken(root)
            commit(root, "final fixes")
    except FatalModelError as error:
        print(f"[agent] model unavailable, delivering current state: {error}", flush=True)
        restore_if_broken(root)
    print(f"[agent] finished in {time.time() - started:.0f}s; usage {llm.usage}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

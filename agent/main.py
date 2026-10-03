"""Coding agent: requirements directory in, tested React + Express app out.

    python3 main.py REQUIREMENTS_DIR --output-dir OUTPUT_DIR [--type web] [--resume]

One engineer session plans and builds the whole app in small tested slices in the output directory. It looks up
requirement text on demand and starts helper subagents in the background for work it does not need yet
(reviews, summaries, tests of later areas); their results reach it as messages, so nothing waits on them.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

import checkpoint
import checks
import roles
import spec
import llm
from llm import FatalModelError
from tools import shell

HERE = Path(__file__).resolve().parent
MAP_SKIP = {"package-lock.json", "README.md", ".gitignore", "eslint.config.js"}


def workspace_map(root: Path) -> str:
    """Paths and line counts of the template sources; the engineer reads the ones it needs."""
    lines = []
    for path in sorted(p for part in ("backend", "frontend") for p in (root / part).rglob("*")
                       if p.is_file() and "node_modules" not in p.parts and "dist" not in p.parts):
        if path.name in MAP_SKIP:
            continue
        lines.append(f"- {path.relative_to(root)} ({path.read_text(errors='replace').count(chr(10)) + 1} lines)")
    return "\n".join(lines)


def setup(root: Path) -> None:
    for item in (HERE / "template").iterdir():
        if not (root / item.name).exists():
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, root / item.name)
    if not (root / ".gitignore").exists():
        (root / ".gitignore").write_text(f".arc/\n{checkpoint.AGENT_DIR}/\nrequirements/\nnode_modules\ndist/\n*.db\n"
                                          "test-results/\nplaywright-report/\n")
    if roles.SKILLS.is_dir():  # read on demand; .agent stays out of git and resets
        shutil.copytree(roles.SKILLS, root / checkpoint.AGENT_DIR / "skills", dirs_exist_ok=True)
    shell("git init -q 2>/dev/null; git config user.email agent@local; git config user.name agent", root, 30)
    problem = checks.install(root)
    if problem:
        print(problem, flush=True)


STEPS_PER_REQUIREMENT = 25  # the session stops after 4x this per requirement: a guard against a runaway loop


class Builder:
    def __init__(self, root: Path, req_dir: Path, tree: spec.Node, steps: int, earlier: bool = False):
        self.root, self.req_dir, self.tree, self.steps, self.earlier = root, req_dir, tree, steps, earlier
        self.run = checkpoint.RunState(root)

    def plan_text(self) -> str:
        path = self.root / roles.PLAN_FILE
        return path.read_text() if path.is_file() else "(not written yet)"

    def earlier_note(self) -> str:
        return roles.EARLIER_WORK.format(plan=roles.PLAN_FILE) if self.earlier else ""

    def task(self) -> str:
        return roles.BUILD_TASK.format(plan=roles.PLAN_FILE, req_dir=self.req_dir, template=workspace_map(self.root),
                                       earlier=self.earlier_note(),
                                       notes=roles.skills_section(), outline=spec.outline(self.tree),
                                       seeds=spec.seed_facts(self.tree) or "- none")

    def refreshed_task(self) -> str:
        return roles.REFRESH_TASK.format(plan=roles.PLAN_FILE, plan_text=self.plan_text(),
                                         earlier=self.earlier_note(), outline_code=roles.code_map(self.root), notes=roles.skills_section(),
                                         outline=spec.outline(self.tree))

    def build(self, resume: bool) -> None:
        if self.run.done("build"):
            return
        engineer = roles.Engineer(roles.new_llm(), self.root, self.req_dir, self.tree, "engineer", self.steps,
                                  task_builder=self.refreshed_task)
        engineer.run(self.task(), resume="last" if resume else None)
        self.run.finish("build", checkpoint.commit(self.root, "build finished"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("requirement_path", nargs="?", default=os.environ.get("ARCBENCH_TASK_DIR", "requirements"))
    parser.add_argument("--output-dir", default=os.environ.get("ARCBENCH_OUTPUT_DIR", "."))
    parser.add_argument("--type", default=os.environ.get("ARCBENCH_TASK_TYPE", "web"))
    parser.add_argument("--steps", type=int, default=int(os.environ.get("AGENT_STEPS", "0")),
                        help="step scale of the runaway guard; default 25 per atomic requirement")
    parser.add_argument("--resume", action="store_true", help="continue an interrupted run in the output dir")
    args = parser.parse_args()
    started = time.time()
    req_dir, root = Path(args.requirement_path).resolve(), Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    earlier = not args.resume and checkpoint.start_over(root)
    setup(root)
    llm.USAGE_LOG = root / checkpoint.AGENT_DIR / "usage.jsonl"
    llm.LIVE_FILE = root / checkpoint.AGENT_DIR / "llm-live.json"
    run = checkpoint.RunState(root)
    if not run.done("template"):
        run.finish("template", checkpoint.commit(root, "template"))
    tree = spec.load(req_dir)
    builder = Builder(root, req_dir, tree, args.steps or STEPS_PER_REQUIREMENT * len(tree.atomics),
                      earlier=earlier or (root / checkpoint.EARLIER_PLAN).exists())
    print(f"[agent] {len(tree.atomics)} atomic requirements; model {llm.DEFAULT_MODEL}", flush=True)
    try:
        builder.build(args.resume)
    except FatalModelError as error:
        print(f"[agent] model unavailable, delivering current state: {error}", flush=True)
    print(f"[agent] finished in {time.time() - started:.0f}s", flush=True)
    report = llm.usage_report(llm.USAGE_LOG)  # whole run, including sessions before a resume
    (root / checkpoint.AGENT_DIR / "usage-report.txt").write_text(report + "\n")
    print(report, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

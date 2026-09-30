"""Coding agent: requirements directory in, tested React + Express app out.

    python3 main.py REQUIREMENTS_DIR --output-dir OUTPUT_DIR [--type web] [--workers 4] [--resume]

A planner writes the architecture and a task graph; a foundation worker builds the shared base; feature
workers implement graph nodes in parallel git worktrees with test-driven development, reviewed by a
read-only advisor; the orchestrator merges each node into the output directory and keeps only merges that
do not lower the full test suite.
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import checkpoint
import checks
import dag
import roles
import spec
import workspace
import llm
from llm import LLM, FatalModelError
from tools import shell

HERE = Path(__file__).resolve().parent
MAP_SKIP = {"package-lock.json", "README.md", ".gitignore", "eslint.config.js"}
SYSTEM = roles.ENGINEER  # kept for tests and tools that inspect the prompt


def workspace_map(root: Path) -> str:
    """Full text of the small template sources, so the planner does not spend steps exploring them."""
    parts = []
    for path in sorted(p for part in ("backend", "frontend") for p in (root / part).rglob("*")
                       if p.is_file() and "node_modules" not in p.parts and "dist" not in p.parts):
        if path.name in MAP_SKIP or path.stat().st_size > 6000:
            continue
        parts.append(f"--- {path.relative_to(root)}\n{path.read_text(errors='replace').rstrip()}")
    return "\n".join(parts)


def setup(root: Path) -> None:
    for item in (HERE / "template").iterdir():
        if not (root / item.name).exists():
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, root / item.name)
    if not (root / ".gitignore").exists():
        # node_modules without a slash also ignores the symlinks shared into worktrees
        (root / ".gitignore").write_text(f".arc/\n{checkpoint.AGENT_DIR}/\nrequirements/\nnode_modules\ndist/\n*.db\n"
                                          "test-results/\nplaywright-report/\n")
    shell("git init -q 2>/dev/null; git config user.email agent@local; git config user.name agent", root, 30)
    problem = checks.install(root)
    if problem:
        print(problem, flush=True)


def restore_if_broken(root: Path) -> None:
    """Go back to the last commit whose build passed when the working tree no longer builds."""
    if not checks.build(root):
        return
    good = checkpoint.RunState(root).data.get("good") or checkpoint.RunState(root).done("template")
    print(f"[agent] build broken; restoring {good[:8]}", flush=True)
    checkpoint.reset(root, good)


def suite(root: Path) -> tuple[int, int, str]:
    """(passed, total, report) of the whole test suite in `root`."""
    _, report = checks.check(root)
    if not report.startswith("build ok") or "e2e " not in report:
        return 0, 0, report
    passed, total = (int(x) for x in report.split("e2e ", 1)[1].split(" ", 1)[0].split("/"))
    return passed, total, report


@dataclass
class Outcome:
    merged: bool
    score: int  # full-suite passes with the node's branch merged; the node's progress measure
    feedback: str = ""  # for the node's next attempt when not merged
    followup: str = ""  # fixes the judge asked for after keeping the merge


MAX_ATTEMPTS = 6  # safety cap; a node normally stops earlier, when two attempts in a row make no progress


class Orchestrator:
    def __init__(self, root: Path, req_dir: Path, tree: spec.Node, steps: int, workers: int):
        self.root, self.req_dir, self.tree = root, req_dir, tree
        self.steps, self.workers = steps, workers
        self.run = checkpoint.RunState(root)
        self.atomics = {a.id: a for a in tree.atomics}

    def llm(self) -> LLM:
        return roles.new_llm()

    def plan_text(self, root: Path | None = None) -> str:
        path = (root or self.root) / roles.PLAN_FILE
        return path.read_text() if path.is_file() else "(missing)"

    def cards(self, node: dag.Node) -> str:
        rules = spec.shared(self.tree, node.requirements)
        cards = "\n\n".join(spec.card(self.atomics[r], str(self.req_dir)) for r in node.requirements)
        return (f"## Rules of the requirement groups this node belongs to\n{rules}\n\n" if rules else "") + cards

    def plan(self) -> list[dag.Node]:
        ids = list(self.atomics)
        nodes = roles.load_plan(self.root, ids) if self.run.done("plan") else []
        if not nodes:
            nodes = roles.plan(self.llm(), self.root, self.req_dir, self.tree, workspace_map(self.root),
                               self.steps)
        if not nodes:  # the planner failed: one node per requirement group, in document order
            groups = spec.groups(self.tree)
            nodes = [dag.Node(g.id, g.name, [a.id for a in g.atomics],
                              [groups[i - 1].id] if i else []) for i, g in enumerate(groups)]
            roles.log("plan", f"planner failed; falling back to {len(nodes)} sequential group nodes")
        if not self.run.done("plan"):
            self.run.finish("plan", checkpoint.commit(self.root, "plan"))
        roles.log("plan", "; ".join(f"{n.id}<-{','.join(n.depends_on) or '-'}" for n in nodes))
        return nodes

    def foundation(self, nodes: list[dag.Node], resume: bool) -> None:
        if self.run.done("foundation"):
            return
        graph = "\n".join(f"- {n.id}: {n.title} ({', '.join(n.requirements)}); depends on "
                          f"{', '.join(n.depends_on) or 'nothing'}" for n in nodes)
        worker = roles.Worker(self.llm(), self.root, self.req_dir, "foundation", "foundation.spec",
                              "(see PLAN.md)", self.steps + 20, base=workspace.head(self.root), reviews=0)
        worker.run(roles.FOUNDATION_TASK.format(plan=roles.PLAN_FILE, graph=graph, shared=spec.shared(self.tree),
                                                plan_text=self.plan_text(), template=workspace_map(self.root)),
                   resume="last" if resume else None)
        problem = checks.build(self.root)
        if problem:  # repair before falling back to the template, which would discard the whole foundation
            roles.log("foundation", "build broken at the end; running a repair session")
            repair = roles.Worker(self.llm(), self.root, self.req_dir, "foundation-repair", "foundation.spec",
                                  "(see PLAN.md)", 30, base=worker.base, reviews=0)
            repair.run(f"The foundation described in {roles.PLAN_FILE} is written but the app does not build or "
                       f"start. Fix the errors with minimal changes until check passes, then call done.\n\n{problem[:6000]}")
        restore_if_broken(self.root)
        self.run.finish("foundation", checkpoint.commit(self.root, "foundation finished"))

    def node_task(self, node: dag.Node, path: Path) -> str:
        return roles.NODE_TASK.format(id=node.id, title=node.title, plan=roles.PLAN_FILE, notes=node.notes or "-",
                                      files=", ".join(node.files) or "-", outline=roles.code_map(path),
                                      plan_text=self.plan_text(path),
                                      owned=roles.file_texts(path, [*node.files, "backend/test-e2e/helpers.ts"]) or "-",
                                      cards=self.cards(node))

    def work(self, node: dag.Node, path: Path, base: str, note: str | None, resume: bool, label: str) -> str:
        worker = roles.Worker(self.llm(), path, self.req_dir, label, f"{node.id}.spec", self.cards(node), self.steps,
                              base=base, task_builder=lambda: self.node_task(node, path))
        summary = worker.run(self.node_task(node, path), resume="last" if resume else None, note=note)
        checkpoint.commit(path, f"{label} finished")
        return summary

    def integrate(self, node: dag.Node) -> Outcome:
        """Merge the node's branch; keep it when the suite is clean, otherwise let the judge decide."""
        before = workspace.head(self.root)
        data = self.run.data
        best, failing_before = data.get("best", 0), set(data.get("failing", []))
        ok, out = workspace.merge(self.root, node.id)
        if not ok:
            files = workspace.conflicts(self.root)
            if not files:
                workspace.abort(self.root, before)
                return Outcome(False, -1, f"The merge failed:\n{out[-2000:]}")
            roles.log(node.id, f"merge conflicts in {', '.join(files)}; running integrator")
            integrator = roles.Worker(self.llm(), self.root, self.req_dir, f"merge-{node.id}", "", "", 30,
                                      base=before, reviews=0)
            integrator.run(roles.INTEGRATE_TASK.format(id=node.id, files=", ".join(files)))
            markers = shell("git grep -l -e '^<<<<<<< ' -e '^>>>>>>> ' -- . ; true", self.root, 60)
            if workspace.conflicts(self.root) or any(line and not line.startswith("[") for line in markers.splitlines()):
                workspace.abort(self.root, before)
                return Outcome(False, -1, f"Merging your branch conflicted with other nodes in {', '.join(files)} "
                                          "and could not be resolved automatically.")
            checkpoint.commit(self.root, f"merge {node.id} (conflicts resolved)")
        passed, total, report = suite(self.root)
        failing = checks.failed_tests(report)
        own = sorted(name for name in failing if name.startswith(f"{node.id}.spec"))
        broken = sorted(failing - failing_before - set(own))
        roles.log(node.id, f"merged: full suite {passed}/{total} (best before {best}); own failing {len(own)}, "
                           f"newly failing {len(broken)}")
        followup = ""
        if passed < best or own or broken:
            listing = "\n".join(f"- {name}" for name in [*own, *broken])
            context = (f"{self.cards(node)}\n\n## Suite\nPassing tests: {best} before the merge, {passed} of "
                       f"{total} after. Failing tests of this node:\n{chr(10).join(own) or '-'}\nTests that "
                       f"passed before the merge and fail now:\n{chr(10).join(broken) or '-'}\n\n"
                       f"## Check report\n{report[:12000]}\n\n## Merge\nInspect it with git diff {before[:8]} HEAD.")
            verdict = roles.advise(self.root, self.req_dir, "judge", context, f"judge-{node.id}")
            keep = verdict.get("approve")
            if keep is None:  # no usable verdict: fall back to the pass count
                keep = passed >= best
            if not keep:
                workspace.abort(self.root, before)
                return Outcome(False, passed, f"Your branch was merged into the latest integration branch and "
                               f"reverted: {roles.feedback(verdict)}\n\nFailing tests after the merge:\n{listing}")
            followup = "\n".join(f"- {issue}" for issue in verdict.get("issues") or [])
        data = self.run.data
        data["best"], data["good"], data["failing"] = passed, workspace.head(self.root), sorted(failing)
        data["done"][node.id] = data["good"]
        self.run._save(data)
        return Outcome(True, passed, followup=followup)

    def add_followup(self, nodes: list[dag.Node], node: dag.Node, fixes: str) -> None:
        number = sum(1 for n in nodes if n.id.startswith(f"{node.id}-fix")) + 1
        extra = dag.Node(f"{node.id}-fix{number}", f"Follow-up fixes after merging {node.id}", [],
                         notes=f"Make these fixes found when {node.id} was merged, then run check without a "
                               f"pattern:\n{fixes}")
        nodes.append(extra)
        data = self.run.data
        data.setdefault("extra_nodes", []).append(asdict(extra))
        self.run._save(data)
        roles.log(node.id, f"judge kept the merge; follow-up node {extra.id} added")

    def nodes(self, nodes: list[dag.Node], resume: bool) -> None:
        good = self.run.data.get("good") or self.run.done("foundation")
        if workspace.head(self.root) != good:  # an integration interrupted by a restart
            roles.log("agent", f"unfinished integration found; returning to the last good commit {good[:8]}")
            workspace.abort(self.root, good)
        nodes = [*nodes, *(dag.Node(**n) for n in self.run.data.get("extra_nodes", []))]
        merged = {n.id for n in nodes if self.run.done(n.id)}
        scores: dict[str, list[int]] = {}
        started: set[str] = set(merged)
        running: dict[futures.Future, dag.Node] = {}
        notes: dict[str, str] = {}
        if "best" not in self.run.data:
            data = self.run.data
            passed, _, report = suite(self.root)
            data["best"], data["failing"] = passed, sorted(checks.failed_tests(report))
            self.run._save(data)
        with futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            while len(merged) < len(nodes):
                for node in dag.ready(nodes, merged, started)[: max(0, self.workers - len(running))]:
                    attempt = len(scores.setdefault(node.id, [])) + 1
                    base = workspace.head(self.root)
                    path = workspace.existing(self.root, node.id) if resume or attempt > 1 else None
                    if path is None:
                        path = workspace.create(self.root, node.id, base)
                    elif attempt > 1:  # continue the same session on top of the new integration branch
                        files = workspace.sync(self.root, node.id, base)
                        checkpoint.Transcript(path, node.id).rebase(workspace.head(path))
                        if files:
                            notes[node.id] = (notes.get(node.id, "") + "\n\nThe latest integration branch was "
                                              "merged into your branch; resolve the conflict markers left in: "
                                              + ", ".join(files)).strip()
                    continuing = path is not None and (resume or attempt > 1) and \
                        (path / checkpoint.AGENT_DIR / f"{node.id}.jsonl").exists()
                    roles.log(node.id, f"start attempt {attempt} from {base[:8]}{' (continuing)' if continuing else ''}")
                    running[pool.submit(self.work, node, path, base, notes.pop(node.id, None), continuing,
                                        node.id)] = node
                    started.add(node.id)
                if not running:
                    break
                done, _ = futures.wait(running, return_when=futures.FIRST_COMPLETED)
                for future in done:
                    node = running.pop(future)
                    summary = ""
                    try:
                        summary = future.result() or ""
                    except FatalModelError:
                        raise
                    except Exception as error:  # a crashed worker counts as an attempt without progress
                        roles.log(node.id, f"worker crashed: {type(error).__name__}: {error}")
                    outcome = self.integrate(node)
                    history = scores[node.id]
                    history.append(outcome.score)
                    if outcome.merged:
                        merged.add(node.id)
                        workspace.remove(self.root, node.id)
                        if outcome.followup:
                            self.add_followup(nodes, node, outcome.followup)
                        continue
                    stalled = len(history) >= 3 and max(history[-2:]) <= max(history[:-2])
                    reason = ("no progress in the last two attempts" if stalled else
                              "its session used its whole step allowance" if summary == "step limit reached" else
                              f"{MAX_ATTEMPTS} attempts" if len(history) >= MAX_ATTEMPTS else "")
                    if reason:
                        roles.log(node.id, f"giving up: {reason}; the integration branch stays without it")
                        merged.add(node.id)
                        data = self.run.data
                        data["done"][node.id] = "gave-up"
                        self.run._save(data)
                        workspace.remove(self.root, node.id)
                    else:
                        roles.log(node.id, f"attempt {len(history)} not merged (score {outcome.score}); continuing")
                        notes[node.id] = outcome.feedback
                        started.discard(node.id)

    def final(self) -> None:
        if self.run.done("final"):
            return
        passed, total, report = suite(self.root)
        roles.log("final", f"full suite {passed}/{total}")
        if total and passed < total:
            fixer = roles.Worker(self.llm(), self.root, self.req_dir, "final", "", "", self.steps,
                                 base=workspace.head(self.root), reviews=0)
            fixer.run("The full test suite fails. Fix the app (not the tests, unless a test contradicts the "
                      f"requirement) until check passes, then call done.\n\n{report}")
            after, _, _ = suite(self.root)
            if after < passed and self.run.data.get("good"):
                checkpoint.reset(self.root, self.run.data["good"])
        restore_if_broken(self.root)
        self.run.finish("final", checkpoint.commit(self.root, "final"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("requirement_path", nargs="?", default=os.environ.get("ARCBENCH_TASK_DIR", "requirements"))
    parser.add_argument("--output-dir", default=os.environ.get("ARCBENCH_OUTPUT_DIR", "."))
    parser.add_argument("--type", default=os.environ.get("ARCBENCH_TASK_TYPE", "web"))
    parser.add_argument("--steps", type=int, default=int(os.environ.get("AGENT_STEPS", "60")))
    parser.add_argument("--workers", type=int, default=int(os.environ.get("AGENT_WORKERS", "4")))
    parser.add_argument("--resume", action="store_true", help="continue an interrupted run in the output dir")
    args = parser.parse_args()
    started = time.time()
    req_dir, root = Path(args.requirement_path).resolve(), Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    setup(root)
    llm.USAGE_LOG = root / checkpoint.AGENT_DIR / "usage.jsonl"
    run = checkpoint.RunState(root)
    if not run.done("template"):
        run.finish("template", checkpoint.commit(root, "template"))
    tree = spec.load(req_dir)
    orchestrator = Orchestrator(root, req_dir, tree, args.steps, args.workers)
    print(f"[agent] {len(tree.atomics)} atomic requirements; model {LLM().model}; workers {args.workers}", flush=True)
    try:
        nodes = orchestrator.plan()
        orchestrator.foundation(nodes, args.resume)
        orchestrator.nodes(nodes, args.resume)
        orchestrator.final()
    except FatalModelError as error:
        print(f"[agent] model unavailable, delivering current state: {error}", flush=True)
        restore_if_broken(root)
    sessions = roles.SESSIONS
    calls, prompt = sum(s.usage.calls for s in sessions), sum(s.usage.prompt for s in sessions)
    cached, completion = sum(s.usage.cached for s in sessions), sum(s.usage.completion for s in sessions)
    print(f"[agent] finished in {time.time() - started:.0f}s; calls={calls} prompt={prompt} cached={cached} "
          f"completion={completion} ({len(sessions)} sessions)", flush=True)
    report = llm.usage_report(llm.USAGE_LOG)  # whole run, including sessions before a resume
    (root / checkpoint.AGENT_DIR / "usage-report.txt").write_text(report + "\n")
    print(report, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

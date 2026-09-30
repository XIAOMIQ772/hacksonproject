import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import checks  # noqa: E402
import compaction  # noqa: E402
import loop  # noqa: E402
import spec  # noqa: E402
from tools import Tools  # noqa: E402

YAML = """
id: ROOT
name: Demo
type: FOLDER
description: Demo product.
children:
- id: REQ-1
  name: Area
  type: FOLDER
  children:
  - id: REQ-1-1
    name: Rename
    type: ATOMIC
    description: The "Rename" button opens a dialog named "Rename item".
    scenarios:
    - steps: [{keyword: GIVEN, content: seed}, {keyword: WHEN, content: act}]
    - steps: [{keyword: GIVEN, content: seed}, {keyword: WHEN, content: act}]
"""


class PromptTest(unittest.TestCase):
    def test_system_prompt_renders(self):
        import main
        self.assertIn("exact: true", main.SYSTEM)
        self.assertIn("test-driven", main.SYSTEM)


class SpecTest(unittest.TestCase):
    def test_groups_and_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "requirements.yaml").write_text(YAML)
            root = spec.load(Path(tmp))
        groups = spec.groups(root)
        self.assertEqual([g.id for g in groups], ["REQ-1"])
        card = spec.group_card(groups[0])
        self.assertIn('"Rename"; "Rename item"', card)
        self.assertIn("Scenario (x2)", card)
        self.assertIn("Acceptance scenarios: 2", card)


class ToolsTest(unittest.TestCase):
    def test_edit_requires_unique_match_and_paths_stay_inside(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Tools(Path(tmp))
            tools.run("write", json.dumps({"path": "a/b.txt", "content": "x x"}))
            self.assertIn("2 times", tools.run("edit", json.dumps({"path": "a/b.txt", "old_text": "x", "new_text": "y"})))
            self.assertIn("outside", tools.run("read", json.dumps({"path": "../etc/passwd"})))
            self.assertIn("node_modules", tools.run("write", json.dumps({"path": "node_modules/x.js", "content": ""})))

    def test_bash_kills_background_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Tools(Path(tmp)).run("bash", json.dumps({"command": "sleep 30 & echo started", "timeout": 2}))
            self.assertIn("started", out)
            self.assertIn("timeout", out)


class StaticTest(unittest.TestCase):
    def test_browser_dialogs_flagged_native_select_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "frontend", "src")
            src.mkdir(parents=True)
            (src / "A.tsx").write_text('<select id="a">\nconfirm("x")\nwindow.alert("y")\n')
            found = checks.static(Path(tmp))
        self.assertEqual(len(found), 2)


class FakeLLM:
    def __init__(self):
        self.requests = []

    def chat(self, system, messages, tools, tool_choice=None):
        self.requests.append((messages, tool_choice))
        return type("R", (), {"text": f"summary {len(self.requests)}"})()


class CompactionTest(unittest.TestCase):
    def setUp(self):  # the production threshold is far above what these histories reach
        self.trigger, compaction.TRIGGER_TOKENS = compaction.TRIGGER_TOKENS, 60000
        self.keep, compaction.KEEP_RECENT_TOKENS = compaction.KEEP_RECENT_TOKENS, 16000

    def tearDown(self):
        compaction.TRIGGER_TOKENS, compaction.KEEP_RECENT_TOKENS = self.trigger, self.keep

    def history(self, turns):
        messages = [{"role": "user", "content": "task"}]
        for i in range(turns):
            args = json.dumps({"path": f"f{i}.js", "content": "x" * 3000})
            messages.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": str(i), "type": "function", "function": {"name": "write", "arguments": args}}]})
            messages.append({"role": "tool", "tool_call_id": str(i), "content": "y" * 3000})
        return messages

    def test_session_summarizes_itself_and_gets_a_fresh_task(self):
        llm, state = FakeLLM(), {}
        old = self.history(80)
        new = compaction.compact(llm, "sys", [], old, state, lambda: ("fresh task", "## Latest check report\nok"))
        sent, choice = llm.requests[0]
        self.assertEqual(sent[:-1], old)  # the whole conversation, so the cached prefix is reused
        self.assertEqual(sent[-1]["content"], compaction.SUMMARY_REQUEST)
        self.assertEqual(choice, "none")
        self.assertEqual(new[0]["content"], "fresh task")
        self.assertTrue(new[1]["content"].startswith(compaction.SUMMARY_TAG + "\nsummary 1"))
        self.assertIn("Latest check report", new[1]["content"])
        self.assertEqual(new[2]["role"], "assistant")
        self.assertEqual(new[-1], old[-1])
        self.assertLess(compaction.estimate(new), compaction.TRIGGER_TOKENS)
        again = compaction.compact(llm, "sys", [], new + self.history(80)[1:], state)
        self.assertEqual(again[0], new[0])  # without refresh the task stays
        self.assertIn("summary 1", llm.requests[1][0][1]["content"])  # the earlier summary is in the request

    def test_small_history_untouched(self):
        small = self.history(3)
        self.assertIs(compaction.compact(FakeLLM(), "sys", [], small, {}), small)


class ImageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        Path(self.tmp.name, "shot.png").write_bytes(b"\x89PNG fake")
        self.tools = Tools(Path(self.tmp.name))
        loop._visual.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_vision_model_gets_image_attached(self):
        llm = type("L", (), {"vision": True})()
        text, attachment = loop.read_image(llm, self.tools, json.dumps({"path": "shot.png"}))
        self.assertIn("attached", text)
        self.assertEqual(attachment["content"][1]["type"], "image_url")
        self.assertTrue(attachment["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertLess(compaction.estimate([attachment]), compaction.IMAGE_TOKENS + 100)

    def test_text_model_gets_description_from_visual_model(self):
        llm = type("L", (), {"vision": False})()
        loop._visual["llm"] = type("V", (), {"chat": lambda self, *a: type("R", (), {"text": "a toolbar"})()})()
        text, attachment = loop.read_image(llm, self.tools, json.dumps({"path": "shot.png"}))
        self.assertIn("a toolbar", text)
        self.assertIsNone(attachment)

    def test_text_files_are_not_images(self):
        self.assertIsNone(loop.read_image(type("L", (), {"vision": True})(), self.tools, json.dumps({"path": "a.ts"})))


class ScriptedLLM:
    """Writes step<n>.txt on each call, then calls done on the fourth call."""
    vision = False

    def __init__(self):
        self.calls = 0

    def chat(self, system, messages, tools):
        self.calls += 1
        n = self.calls
        if n >= 4:
            call = {"id": f"c{n}", "name": "done", "arguments": json.dumps({"summary": "ok"})}
        else:
            call = {"id": f"c{n}", "name": "write", "arguments": json.dumps({"path": f"step{n}.txt", "content": str(n)})}
        message = {"role": "assistant", "content": "", "tool_calls": [
            {"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": call["arguments"]}}]}
        return type("R", (), {"message": message, "tool_calls": [call], "text": ""})()


class CheckpointTest(unittest.TestCase):
    def test_resume_restores_files_and_transcript(self):
        from checkpoint import Transcript, commit
        from tools import shell
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell("git init -q && git config user.email t@t && git config user.name t", root, 30)
            (root / ".gitignore").write_text(".agent/\n")
            commit(root, "init")
            tools = Tools(root)
            loop.run(ScriptedLLM(), "sys", "task", tools, transcript=Transcript(root, "p"), max_steps=10)
            self.assertTrue((root / "step3.txt").exists())
            messages, _, step, _ = Transcript(root, "p").load(1)
            self.assertEqual(step, 1)
            self.assertEqual([m["role"] for m in messages], ["user", "assistant", "tool"])
            llm = ScriptedLLM()
            llm.calls = 1  # the resumed session continues with step 2
            loop.run(llm, "sys", "task", tools, transcript=Transcript(root, "p"), resume=1, max_steps=10)
            self.assertTrue((root / "step2.txt").exists())
            self.assertTrue(list((root / ".agent").glob("p.after-1.jsonl")))
            last = Transcript(root, "p").load()
            self.assertEqual(last[2], 4)
            self.assertEqual(len(last[0]), 9)  # task + 4 x (assistant, tool)

    def test_resume_resets_files_written_after_the_checkpoint(self):
        from checkpoint import Transcript, commit
        from tools import shell
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell("git init -q && git config user.email t@t && git config user.name t", root, 30)
            (root / ".gitignore").write_text(".agent/\n")
            commit(root, "init")
            loop.run(ScriptedLLM(), "sys", "task", Tools(root), transcript=Transcript(root, "p"), max_steps=10)
            done = ScriptedLLM()
            done.calls = 3  # next call is done: nothing new is written
            loop.run(done, "sys", "task", Tools(root), transcript=Transcript(root, "p"), resume=1, max_steps=10)
            self.assertFalse((root / "step2.txt").exists())
            self.assertFalse((root / "step3.txt").exists())


class SharedRulesTest(unittest.TestCase):
    def test_group_descriptions_reach_planner_and_nodes(self):
        a = spec.Node("R-1-1", "A", "ATOMIC", "a")
        b = spec.Node("R-2-1", "B", "ATOMIC", "b")
        root = spec.Node("ROOT", "P", "FOLDER", "product", children=[
            spec.Node("R-1", "G1", "FOLDER", 'The grid is named "Worksheet grid".', children=[a]),
            spec.Node("R-2", "G2", "FOLDER", "", children=[b])])
        self.assertIn("Worksheet grid", spec.outline(root))
        self.assertIn("Worksheet grid", spec.shared(root))
        self.assertIn("Worksheet grid", spec.shared(root, ["R-1-1"]))
        self.assertNotIn("Worksheet grid", spec.shared(root, ["R-2-1"]))
        self.assertIn("product", spec.shared(root, ["R-2-1"]))


class ParallelReadTest(unittest.TestCase):
    def test_reads_in_one_reply_run_concurrently_and_keep_order(self):
        import time as clock
        with tempfile.TemporaryDirectory() as tmp:
            tools = Tools(Path(tmp))
            for name in "abc":
                (Path(tmp) / f"{name}.txt").write_text(name)
            original = tools.run

            def slow(name, arguments):
                clock.sleep(0.3)
                return original(name, arguments)
            tools.run = slow
            calls = [{"id": n, "name": "read", "arguments": json.dumps({"path": f"{n}.txt"})} for n in "abc"]
            started = clock.time()
            results = loop.prefetch_reads(FakeLLM(), tools, calls + [{"id": "w", "name": "write", "arguments": "{}"}])
            self.assertLess(clock.time() - started, 0.8)
            self.assertEqual(list(results), ["a", "b", "c"])
            self.assertIn("a", results["a"][0])
            self.assertEqual(loop.prefetch_reads(FakeLLM(), tools, [calls[0], {"id": "w", "name": "edit",
                                                                              "arguments": "{}"}, calls[1]]), {})


class HarnessSpeedTest(unittest.TestCase):
    def test_apply_is_all_or_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools, root = Tools(Path(tmp)), Path(tmp)
            (root / "a.js").write_text("one\ntwo\n")
            bad = tools.run("apply", json.dumps({"changes": [
                {"path": "new.js", "content": "x"}, {"path": "a.js", "old_text": "missing", "new_text": "y"}]}))
            self.assertIn("nothing written", bad)
            self.assertFalse((root / "new.js").exists())
            ok = tools.run("apply", json.dumps({"changes": [
                {"path": "new.js", "content": "x"}, {"path": "a.js", "old_text": "one", "new_text": "1"},
                {"path": "a.js", "old_text": "two", "new_text": "2"}]}))
            self.assertIn("applied", ok)
            self.assertEqual((root / "a.js").read_text(), "1\n2\n")

    def test_reviewer_tools_cannot_modify(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Tools(Path(tmp), read_only=True)
            self.assertEqual({s["name"] for s in tools.schemas}, {"read", "bash"})
            self.assertIn("read-only", tools.run("write", json.dumps({"path": "x", "content": "y"})))
            self.assertIn("read-only", tools.run("bash", json.dumps({"command": "touch x"})))
            self.assertFalse((Path(tmp) / "x").exists())
            self.assertIn("exit 0", tools.run("bash", json.dumps({"command": "ls"})))

    def test_read_only_commands(self):
        from tools import is_read_only
        for command in ("grep -rn x src | head", "git diff --stat", "cd backend && cat package.json"):
            self.assertTrue(is_read_only(command), command)
        for command in ("npm test", "sed -i s/a/b/ f", "echo x > f", "git checkout .", "find . -delete"):
            self.assertFalse(is_read_only(command), command)

    def test_set_reasoning_changes_effort(self):
        llm = FakeLLM()
        self.assertIn("ERROR", loop.set_reasoning(llm, json.dumps({"level": "max"})))
        loop.set_reasoning(llm, json.dumps({"level": "high"}))
        self.assertEqual(llm.effort, "high")

    def test_usage_report_groups_by_role(self):
        import llm
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.jsonl"
            rows = [{"model": "m", "label": "plan", "prompt": 100, "cached": 50, "completion": 10, "reasoning": 5,
                     "seconds": 1.0}, {"model": "m", "label": "N1:advisor", "prompt": 10, "cached": 0,
                                       "completion": 1, "reasoning": 0, "seconds": 0.5}]
            path.write_text("\n".join(json.dumps(r) for r in rows))
            report = llm.usage_report(path)
            self.assertIn("role=plan: calls=1 prompt=100 cached=50 (50%)", report)
            self.assertIn("role=advisor", report)

    def test_code_map_lists_declarations(self):
        import roles
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backend/src").mkdir(parents=True)
            (root / "backend/src/routes.js").write_text(
                "const x = 1;\nrouter.get('/api/items', h);\nfunction load(id) {}\nmodule.exports = { load };\n")
            text = roles.code_map(root)
            self.assertIn("backend/src/routes.js (5 lines)", text)
            self.assertIn("router.get('/api/items'", text)
            self.assertIn("function load(id)", text)
            self.assertNotIn("const x", text)


class SchedulingTest(unittest.TestCase):
    def run_nodes(self, outcomes):
        """Run Orchestrator.nodes with scripted merge outcomes per node; returns (log of attempts, orchestrator)."""
        import dag
        import main
        import workspace
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = main.Orchestrator.__new__(main.Orchestrator)
            orchestrator.root, orchestrator.workers = root, 2
            orchestrator.run = main.checkpoint.RunState(root)
            orchestrator.run._save({"done": {"foundation": "f"}, "best": 0, "failing": [], "good": "f"})
            attempts = []
            orchestrator.work = lambda node, path, base, note, resume, label: attempts.append((node.id, note)) or "ok"
            orchestrator.integrate = lambda node: outcomes[node.id].pop(0)
            nodes = [dag.Node("a", "A", ["R-1"]), dag.Node("b", "B", ["R-2"], ["a"])]
            with mock.patch.object(workspace, "head", return_value="f"), \
                    mock.patch.object(workspace, "create", return_value=root), \
                    mock.patch.object(workspace, "existing", return_value=root), \
                    mock.patch.object(workspace, "sync", return_value=[]), \
                    mock.patch.object(workspace, "remove"):
                orchestrator.nodes(nodes, resume=False)
            return attempts, orchestrator.run.data

    def test_node_continues_while_it_progresses_and_gives_up_when_stalled(self):
        import main
        outcomes = {"a": [main.Outcome(False, 3, "f1"), main.Outcome(False, 5, "f2"), main.Outcome(False, 5, "f3"),
                          main.Outcome(False, 4, "f4")],
                    "b": [main.Outcome(True, 6, followup="- update stale test")], "b-fix1": [main.Outcome(True, 7)]}
        attempts, data = self.run_nodes(outcomes)
        self.assertEqual([a for a, _ in attempts], ["a", "a", "a", "a", "b", "b-fix1"])
        self.assertEqual(attempts[1][1], "f1")  # the next attempt gets the previous feedback
        self.assertEqual(data["done"]["a"], "gave-up")  # 3 -> 5 progressed; 5 and 4 did not
        self.assertEqual(data["extra_nodes"][0]["id"], "b-fix1")

    def test_worktree_sync_brings_in_integration_work(self):
        import workspace
        from checkpoint import commit
        from tools import shell
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell("git init -q && git config user.email t@t && git config user.name t", root, 30)
            (root / ".gitignore").write_text(".agent/\nnode_modules\n")
            (root / "a.txt").write_text("base\n")
            base = commit(root, "init")
            path = workspace.create(root, "n", base)
            (path / "mine.txt").write_text("node work")
            (root / "other.txt").write_text("merged by another node")
            upstream = commit(root, "other")
            self.assertEqual(workspace.sync(root, "n", upstream), [])
            self.assertTrue((path / "other.txt").exists() and (path / "mine.txt").exists())
            (path / "a.txt").write_text("node\n")
            (root / "a.txt").write_text("upstream\n")
            self.assertEqual(workspace.sync(root, "n", commit(root, "conflict")), ["a.txt"])
            self.assertIn("<<<<<<<", (path / "a.txt").read_text())
            workspace.remove(root, "n")


class ReportTest(unittest.TestCase):
    def test_failed_tests_excludes_flaky(self):
        report = ("build ok; fresh-database start ok; e2e 1/2 passed\nFAILED TESTS:\n- a.spec.ts :: breaks\n"
                  "E2E FAILURES:\n- a.spec.ts :: breaks\n  boom")
        self.assertEqual(checks.failed_tests(report), {"a.spec.ts :: breaks"})


class DagTest(unittest.TestCase):
    def test_parse_reports_coverage_and_cycles(self):
        import dag
        ids = ["R-1", "R-2", "R-3"]
        nodes, problems = dag.parse(json.dumps({"nodes": [
            {"id": "a", "requirements": ["R-1"]},
            {"id": "b", "requirements": ["R-2", "R-3"], "depends_on": ["a"]}]}), ids)
        self.assertEqual(problems, [])
        self.assertEqual([n.id for n in dag.ready(nodes, set(), set())], ["a"])
        self.assertEqual([n.id for n in dag.ready(nodes, {"a"}, {"a"})], ["b"])
        _, problems = dag.parse(json.dumps({"nodes": [
            {"id": "a", "requirements": ["R-1", "R-9"], "depends_on": ["b"]},
            {"id": "b", "requirements": ["R-1"], "depends_on": ["a"]}]}), ids)
        text = "\n".join(problems)
        self.assertIn("R-9", text)
        self.assertIn("not assigned", text)
        self.assertIn("more than one", text)
        _, problems = dag.parse(json.dumps({"nodes": [
            {"id": "a", "requirements": ["R-1"], "depends_on": ["b"]},
            {"id": "b", "requirements": ["R-2", "R-3"], "depends_on": ["a"]}]}), ids)
        self.assertEqual(problems, ["dependencies contain a cycle"])
        self.assertTrue(dag.parse("not json", ids)[1])


class WorkspaceTest(unittest.TestCase):
    def test_parallel_branches_merge_and_conflicts_abort(self):
        import workspace
        from checkpoint import commit
        from tools import shell
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell("git init -q && git config user.email t@t && git config user.name t", root, 30)
            (root / ".gitignore").write_text(".agent/\nnode_modules\n")
            (root / "backend" / "node_modules").mkdir(parents=True)
            (root / "shared.txt").write_text("base\n")
            base = commit(root, "init")
            a, b = workspace.create(root, "a", base), workspace.create(root, "b", base)
            self.assertTrue((a / "backend" / "node_modules").is_symlink())
            (a / "a.txt").write_text("a")
            (b / "b.txt").write_text("b")
            commit(a, "a")
            commit(b, "b")
            self.assertTrue(workspace.merge(root, "a")[0])
            self.assertTrue(workspace.merge(root, "b")[0])
            self.assertTrue((root / "a.txt").exists() and (root / "b.txt").exists())
            c, d = workspace.create(root, "c", workspace.head(root)), workspace.create(root, "d", workspace.head(root))
            (c / "shared.txt").write_text("c\n")
            (d / "shared.txt").write_text("d\n")
            commit(c, "c")
            commit(d, "d")
            self.assertTrue(workspace.merge(root, "c")[0])
            before = workspace.head(root)
            self.assertFalse(workspace.merge(root, "d")[0])
            self.assertEqual(workspace.conflicts(root), ["shared.txt"])
            workspace.abort(root, before)
            self.assertEqual((root / "shared.txt").read_text(), "c\n")
            workspace.remove(root, "d")
            self.assertIsNone(workspace.existing(root, "d"))
            old = root / "old-place"  # a worktree left elsewhere still holding the branch
            shell(f"git worktree add -q -B node/c {old} HEAD", root, 30)
            again = workspace.create(root, "c", workspace.head(root))
            self.assertTrue((again / "shared.txt").exists())
            self.assertFalse(old.exists())
            for node in "abc":  # worktrees live outside the temporary repository
                workspace.remove(root, node)


if __name__ == "__main__":
    unittest.main()

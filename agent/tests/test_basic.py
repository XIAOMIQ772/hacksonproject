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
        import roles
        self.assertIn("exact: true", roles.ENGINEER)
        self.assertIn("small verified slices", roles.ENGINEER)


class SpecTest(unittest.TestCase):
    def test_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "requirements.yaml").write_text(YAML)
            root = spec.load(Path(tmp))
        card = spec.card(root.atomics[0])
        self.assertIn('"Rename"; "Rename item"', card)
        self.assertIn("(same as above)", card)
        self.assertIn("Acceptance scenarios: 2", card)

    def test_card_drops_template_sentences_and_keeps_values(self):
        template = "Every value is entered through a visible, labelled control and nothing else is assumed."
        root = spec.Node("ROOT", "P", "FOLDER", children=[spec.Node(f"R-{i}", "A", "ATOMIC", "d", [
            {"steps": [{"keyword": "GIVEN", "content": "The seed contains `v1.0` and `README.md`. " + template},
                       {"keyword": "THEN", "content": f"Shows `alice.dev@example.test` for {i}. " + template}]}])
            for i in range(3)])
        common = frozenset(spec.boilerplate(root))
        self.assertEqual(common, {template})
        card = spec.card(root.atomics[0], "", common)
        for value in ("`v1.0`", "`README.md`", "`alice.dev@example.test`"):
            self.assertIn(value, card)
        self.assertNotIn(template, card)
        self.assertIn(template, spec.outline(root))


def patch(tools: Tools, body: str) -> str:
    return tools.run("apply_patch", json.dumps({"input": f"*** Begin Patch\n{body}\n*** End Patch"}))


class ToolsTest(unittest.TestCase):
    def test_patch_refuses_ambiguous_changes_and_paths_stay_inside(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Tools(Path(tmp))
            self.assertIn("A a/b.txt", patch(tools, "*** Add File: a/b.txt\n+x\n+x"))
            self.assertIn("match 2 places", patch(tools, "*** Update File: a/b.txt\n-x\n+y"))
            self.assertIn("outside", patch(tools, "*** Add File: ../escape.txt\n+x"))
            self.assertIn("node_modules", patch(tools, "*** Add File: node_modules/x.js\n+x"))
            self.assertIn("A c.txt", tools.run("apply_patch", json.dumps({"input": "*** Add File: c.txt\n+x"})))
            self.assertIn("A e.txt", patch(tools, "*** Add File: d.txt\n+x\n*** End Patch\n*** Add File: e.txt\n+y"))
            self.assertEqual((Path(tmp) / "d.txt").read_text(), "x\n")
            patch(tools, "*** Add File: q.js\n+db.all(`SELECT 1\n   FROM t`);")
            self.assertEqual((Path(tmp) / "q.js").read_text(), "db.all(`SELECT 1\n   FROM t`);\n")

    def test_bash_refuses_e2e_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            lead = Tools(Path(tmp), experiments=False)
            for command in ("cd backend && npx playwright test a.spec.ts", "npm run test:e2e -- a.spec.ts",
                            "node src/index.js & sleep 2; curl localhost:3000", "cd backend && npm start"):
                self.assertIn("subagent", lead.run("bash", json.dumps({"command": command})), command)
            self.assertIn("exit 0", lead.run("bash", json.dumps({"command": "grep -rn start . || true"})))
            # read-only searches for such commands are not experiments
            self.assertIn("[exit", lead.run("bash", json.dumps({"command": 'rg -n "npm start" . || true'})))
            self.assertNotIn("subagent", lead.run("bash", json.dumps({"command": 'grep -rn "playwright test" .'})))
            self.assertNotIn("subagent", Tools(Path(tmp)).run("bash", json.dumps({"command": "echo npm start"})))

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
            (src / "A.tsx").write_text('<select id="a">\nconfirm("x")\nwindow.alert("y")\n<Link to="/a">\n'
                                       'const go = useNavigate();\n<a href="/b">\n<Routes>\n')
            found = checks.static(Path(tmp))
        self.assertEqual(len(found), 4)


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
        text, attachment = loop.view_image(llm, self.tools, json.dumps({"path": "shot.png"}))
        self.assertIn("attached", text)
        self.assertEqual(attachment["content"][1]["type"], "image_url")
        self.assertTrue(attachment["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertLess(compaction.estimate([attachment]), compaction.IMAGE_TOKENS + 100)

    def test_text_model_gets_description_from_visual_model(self):
        llm = type("L", (), {"vision": False})()
        loop._visual["llm"] = type("V", (), {"chat": lambda self, *a: type("R", (), {"text": "a toolbar"})()})()
        text, attachment = loop.view_image(llm, self.tools, json.dumps({"path": "shot.png"}))
        self.assertIn("a toolbar", text)
        self.assertIsNone(attachment)

    def test_text_files_are_not_images(self):
        text, attachment = loop.view_image(type("L", (), {"vision": True})(), self.tools, json.dumps({"path": "a.ts"}))
        self.assertIn("not an image", text)
        self.assertIsNone(attachment)


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
            call = {"id": f"c{n}", "name": "apply_patch", "arguments": json.dumps(
                {"input": f"*** Begin Patch\n*** Add File: step{n}.txt\n+{n}\n*** End Patch"})}
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

    def test_start_over_archives_an_earlier_run(self):
        from checkpoint import RunState, start_over
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(start_over(root))
            RunState(root).finish("build", "abc")
            (root / ".agent" / "skills").mkdir()
            (root / ".agent" / "engineer.jsonl").write_text("{}")
            (root / "PLAN.md").write_text("stage 1")
            self.assertTrue(start_over(root))
            self.assertIsNone(RunState(root).done("build"))
            self.assertTrue((root / ".agent" / "skills").is_dir())
            self.assertFalse((root / ".agent" / "engineer.jsonl").exists())
            self.assertEqual(len(list((root / ".agent").glob("earlier-*/engineer.jsonl"))), 1)
            self.assertEqual((root / "PLAN-earlier.md").read_text(), "stage 1")

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
            calls = [{"id": n, "name": "bash", "arguments": json.dumps({"command": f"cat {n}.txt"})} for n in "abc"]
            started = clock.time()
            results = loop.prefetch_reads(FakeLLM(), tools, calls + [{"id": "w", "name": "apply_patch", "arguments": "{}"}])
            self.assertLess(clock.time() - started, 0.8)
            self.assertEqual(list(results), ["a", "b", "c"])
            self.assertIn("a", results["a"][0])
            self.assertEqual(loop.prefetch_reads(FakeLLM(), tools, [calls[0], {"id": "w", "name": "apply_patch",
                                                                              "arguments": "{}"}, calls[1]]), {})


class HarnessSpeedTest(unittest.TestCase):
    def test_patch_writes_good_files_and_reports_failed_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools, root = Tools(Path(tmp)), Path(tmp)
            (root / "a.js").write_text("one\ntwo\n")
            bad = patch(tools, "*** Add File: new.js\n+x\n*** Update File: a.js\n-missing\n+y")
            self.assertIn("1 of 2 file sections failed", bad)
            self.assertIn("A new.js", bad)
            self.assertIn("change 1", bad)
            self.assertEqual((root / "new.js").read_text(), "x\n")
            half = patch(tools, "*** Update File: a.js\n-one\n+1\n@@\n-nope\n+y")
            self.assertIn("left unchanged", half)
            self.assertEqual((root / "a.js").read_text(), "one\ntwo\n")  # never half edited
            ok = patch(tools, "*** Update File: a.js\n-one\n+1\n@@\n-two\n+2\n*** Delete File: new.js")
            self.assertIn("Success", ok)
            self.assertEqual((root / "a.js").read_text(), "1\n2\n")
            self.assertFalse((root / "new.js").exists())

    def test_patch_locates_changes_like_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools, root = Tools(Path(tmp)), Path(tmp)
            (root / "a.js").write_text("function a() {\n  return 1;\n}\nfunction b() {\n  return 1;\n}\n")
            # an @@ line picks the second of two equal lines; indentation differences are tolerated
            self.assertIn("Success", patch(tools, "*** Update File: a.js\n@@ function b() {\n-return 1;\n+  return 2;"))
            self.assertEqual((root / "a.js").read_text().count("return 2"), 1)
            self.assertIn("return 2;\n}\n", (root / "a.js").read_text())
            # a context line without its leading space is still context
            self.assertIn("Success", patch(tools, "*** Update File: a.js\n function a() {\n-  return 1;\n+  return 0;\n}"))
            self.assertTrue((root / "a.js").read_text().startswith("function a() {\n  return 0;\n}\n"))
            # the @@ line repeated as the first context line, as in a unified diff
            self.assertIn("Success", patch(tools, "*** Update File: a.js\n@@ function b() {\n+// b\n function b() {"))
            self.assertIn("}\n// b\nfunction b() {", (root / "a.js").read_text())
            # + lines ended by *** End of File are appended; Move to renames
            self.assertIn("Add File to replace", patch(tools, "*** Update File: a.js\n+// end"))
            self.assertIn("M b.js", patch(tools, "*** Update File: a.js\n*** Move to: b.js\n+// end\n*** End of File"))
            self.assertTrue((root / "b.js").read_text().endswith("}\n// end\n"))
            self.assertFalse((root / "a.js").exists())
            near = patch(tools, "*** Update File: b.js\n function b() {\n-  return 3;\n+  return 4;")
            self.assertIn("first 1 lines match file lines 5-5", near)
            self.assertIn("'  return 2;' (file line 6)", near)
            self.assertIn("Closest lines", patch(tools, "*** Update File: b.js\n-  return 3;\n+  return 4;"))

    def test_read_only_commands(self):
        from tools import is_read_only
        for command in ("grep -rn x src | head", "git diff --stat", "cd backend && cat package.json"):
            self.assertTrue(is_read_only(command), command)
        for command in ("npm test", "sed -i s/a/b/ f", "echo x > f", "git checkout .", "find . -delete"):
            self.assertFalse(is_read_only(command), command)

    def test_usage_report_groups_by_role(self):
        import llm
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.jsonl"
            rows = [{"model": "m", "label": "engineer", "prompt": 100, "cached": 50, "completion": 10, "reasoning": 5,
                     "seconds": 1.0}, {"model": "m", "label": "engineer:helper1", "prompt": 10, "cached": 0,
                                       "completion": 1, "reasoning": 0, "seconds": 0.5}]
            path.write_text("\n".join(json.dumps(r) for r in rows))
            report = llm.usage_report(path)
            self.assertIn("role=engineer: calls=1 prompt=100 cached=50 (50%)", report)
            self.assertIn("role=helper", report)

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


class MilestoneTest(unittest.TestCase):
    def test_milestone_compacts_a_long_history_early_and_keeps_the_recent_turns(self):
        turn = [{"role": "assistant", "content": "x" * 6000}, {"role": "user", "content": "r"}]
        turns = (compaction.MILESTONE_TOKENS + compaction.TRIGGER_TOKENS) // 2 // compaction.estimate(turn)
        messages = [{"role": "user", "content": "task"}]
        for i in range(turns):  # between the milestone threshold and the regular trigger
            messages += [{"role": "assistant", "content": "x" * 6000}, {"role": "user", "content": f"r{i}"}]
        size = compaction.estimate(messages)
        self.assertTrue(compaction.MILESTONE_TOKENS < size < compaction.TRIGGER_TOKENS)
        state = {}
        self.assertIs(compaction.compact(FakeLLM(), "s", [], messages, state), messages)  # no milestone: wait
        new = compaction.compact(FakeLLM(), "s", [], messages, state, milestone=True)
        self.assertLess(compaction.estimate(new), compaction.KEEP_RECENT_TOKENS + 10000)
        self.assertEqual(new[-1], messages[-1])


class TrimTest(unittest.TestCase):
    def history(self, turns):
        messages = [{"role": "user", "content": "task"}]
        for i in range(turns):
            path = "once.ts" if i == 0 else "app.ts"  # app.ts is rewritten every turn, once.ts never again
            args = json.dumps({"input": f"*** Begin Patch\n*** Add File: {path}\n+{'x' * 5000}\n*** End Patch"})
            messages += [{"role": "assistant", "content": "", "reasoning_content": "r" * 8000,
                          "tool_calls": [{"id": f"c{i}", "type": "function",
                                          "function": {"name": "apply_patch", "arguments": args}}]},
                         {"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 8000}]
        return messages

    def test_short_history_is_untouched(self):
        messages = self.history(3)
        self.assertIs(compaction.trim(messages), messages)

    def test_old_turns_are_trimmed_and_recent_kept(self):
        messages = self.history(40)
        trimmed = compaction.trim(messages)
        self.assertEqual(trimmed[0], messages[0])
        self.assertEqual(trimmed[-4:], messages[-4:])
        self.assertLess(compaction.estimate(trimmed), compaction.estimate(messages) * 2 // 3)  # reasoning stays
        self.assertEqual(trimmed[1]["reasoning_content"], "r" * 8000)  # passed back verbatim
        self.assertEqual(trimmed[1], messages[1])  # once.ts was not changed again: its content stays
        rewritten = json.loads(trimmed[3]["tool_calls"][0]["function"]["arguments"])
        self.assertIn("app.ts", rewritten["input"])
        self.assertIn("trimmed", rewritten["input"])  # a later patch superseded it
        self.assertIn("trimmed", trimmed[2]["content"])
        skill = {"role": "tool", "tool_call_id": "s", "content": "---\nname: grids\n" + "x" * 2000}
        self.assertEqual(compaction._trim_message(skill), skill)  # loaded skills are kept whole
        self.assertIs(compaction.trim(trimmed), trimmed)  # stable until enough new history accumulates


class LoadTest(unittest.TestCase):
    """Whole-suite failures caused by machine load must not count as regressions."""

    def test_confirm_keeps_only_failures_that_repeat(self):
        failures = ("- a.spec.ts :: slow one\n  Timeout 3000ms exceeded\n- b.spec.ts :: broken\n  not visible\n"
                    "FLAKY (passed on retry; tests probably share state with parallel tests):\n- c.spec.ts :: x")
        calls = []
        original = checks.e2e
        checks.e2e = lambda root, url, pattern="", config="", workers=4: (
            calls.append((pattern, workers)) or (0, 2, "- b.spec.ts :: broken\n  not visible"))
        try:
            remaining, recovered = checks.confirm(Path("."), "http://x", failures)
        finally:
            checks.e2e = original
        self.assertEqual(recovered, 1)
        self.assertEqual(checks.failure_names(remaining), ["b.spec.ts :: broken"])
        self.assertIn("- a.spec.ts :: slow one", remaining.split("FLAKY (failed in the whole-suite run", 1)[1])
        self.assertIn("- c.spec.ts :: x", remaining)
        self.assertEqual(calls[0][1], 1)
        self.assertIn("--max-failures=", calls[0][0])


class CheckPatternTest(unittest.TestCase):
    def test_several_spec_files_reach_playwright_as_quoted_filters(self):
        self.assertEqual(checks.spec_filter("sort.spec|filter.spec"), "sort.spec filter.spec")
        self.assertEqual(checks.spec_filter("TEMP DIAGNOSTIC"), "TEMP DIAGNOSTIC")
        self.assertEqual(checks.spec_filter("a;b"), "'a;b'")
        self.assertEqual(checks.spec_filter(""), "")
        seen = []

        class Server:
            url = "http://x"

            def __init__(self, root):
                pass

            def wait(self):
                return ""

            def output(self):
                return ""

            def stop(self):
                pass
        saved = checks.build, checks.Server, checks.e2e, checks.static
        checks.build, checks.Server, checks.static = (lambda root: ""), Server, (lambda root: [])
        checks.e2e = lambda root, url, pattern="", config="", workers=4: seen.append(pattern) or (2, 2, "")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "backend" / "test-e2e").mkdir(parents=True)
                for name in ("sort", "filter"):
                    (Path(tmp) / "backend" / "test-e2e" / f"{name}.spec.ts").write_text("")
                ok, report = checks.check(Path(tmp), "sort.spec|filter.spec")
        finally:
            checks.build, checks.Server, checks.e2e, checks.static = saved
        self.assertTrue(ok)
        self.assertEqual(seen, ["sort.spec filter.spec"])


class PatchCheckTest(unittest.TestCase):
    """apply_patch with a check argument runs the check in the same step instead of a reply of its own."""

    def run_patch(self, patch: str, check: str) -> tuple[list, str]:
        class LLM:
            vision, calls = False, 0

            def chat(self, system, messages, tools):
                self.calls += 1
                call = ({"id": "p", "name": "apply_patch", "arguments": json.dumps({"input": patch, "check": check})}
                        if self.calls == 1 else {"id": "d", "name": "done", "arguments": json.dumps({"summary": "ok"})})
                message = {"role": "assistant", "content": "", "tool_calls": [{"id": call["id"], "type": "function",
                           "function": {"name": call["name"], "arguments": call["arguments"]}}]}
                return type("R", (), {"message": message, "tool_calls": [call], "text": ""})()
        runs, final = [], []
        tool = loop.Extra({"name": "check"}, lambda args: runs.append(args) or "CHECK PASSED\ne2e 1/1 passed")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("a\n")
            loop.run(LLM(), "sys", "task", Tools(Path(tmp)), extras={"check": tool}, final=final)
        return runs, next(m["content"] for m in final if m.get("tool_call_id") == "p")

    def test_check_runs_after_a_successful_patch(self):
        runs, result = self.run_patch("*** Begin Patch\n*** Add File: b.txt\n+b\n*** End Patch", "b.spec|c.spec")
        self.assertEqual(runs, [{"pattern": "b.spec|c.spec"}])
        self.assertTrue(result.startswith("Success"))
        self.assertIn("CHECK PASSED", result)
        runs, _ = self.run_patch("*** Begin Patch\n*** Add File: b.txt\n+b\n*** End Patch", "all")
        self.assertEqual(runs, [{"pattern": ""}])

    def test_no_check_after_a_failed_patch(self):
        runs, result = self.run_patch("*** Begin Patch\n*** Update File: a.txt\n-zzz\n+y\n*** End Patch", "b.spec")
        self.assertEqual(runs, [])
        self.assertIn("check was not run", result)


class HelperTest(unittest.TestCase):
    def test_results_arrive_as_messages_without_waiting(self):
        import threading
        import roles
        release = threading.Event()
        original = roles.loop.run

        def slow(*args, **kwargs):
            release.wait(5)
            return "found it"
        roles.loop.run = slow
        original_llm = roles.new_llm
        roles.new_llm = lambda model=None: FakeLLM()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                helpers = roles.Helpers(Path(tmp), Path(tmp), "engineer", {})
                number = helpers.start("look into it")
                self.assertEqual(helpers.finished(), [])  # still running: nothing delivered, nothing blocked
                release.set()
                self.assertIn("found it", helpers.result(number))
                self.assertEqual(helpers.finished(), [])  # delivered once
                helpers.close()
        finally:
            roles.loop.run, roles.new_llm = original, original_llm


    def test_messages_reach_running_and_finished_subagents(self):
        import threading
        import roles
        release, seen = threading.Event(), []
        original, original_llm = roles.loop.run, roles.new_llm

        def session(llm, system, text, tools, **kwargs):
            seen.append(text)
            if len(seen) == 1:
                release.wait(5)
                seen.append(kwargs["on_step"](1, []))  # a step boundary: the queued message is taken
            kwargs["final"][:] = [{"role": "user", "content": text}]
            return f"answer {len(seen)}"
        roles.loop.run, roles.new_llm = session, (lambda model=None: FakeLLM())
        try:
            with tempfile.TemporaryDirectory() as tmp:
                helpers = roles.Helpers(Path(tmp), Path(tmp), "engineer", {})
                number = helpers.start("review area 1")
                self.assertIn("queued", helpers.send(number, "also check the dialog"))
                release.set()
                self.assertIn("answer 2", helpers.result(number))
                self.assertIn("also check the dialog", seen[1])
                self.assertIn("continues", helpers.send(number, "now fix what you found"))
                self.assertIn("answer 3", helpers.result(number))
                self.assertIn("now fix what you found", seen[2])
                helpers.close()
        finally:
            roles.loop.run, roles.new_llm = original, original_llm


    def test_subagents_are_asked_to_wrap_up_at_their_budget(self):
        import roles
        original, original_llm = roles.loop.run, roles.new_llm
        steps = {}

        def session(llm, system, text, tools, **kwargs):
            steps[text] = {n: kwargs["on_step"](n, []) for n in (1, roles.REVIEW_STEPS, roles.HELPER_STEPS)}
            return "done"
        roles.loop.run, roles.new_llm = session, (lambda model=None: FakeLLM())
        try:
            with tempfile.TemporaryDirectory() as tmp:
                helpers = roles.Helpers(Path(tmp), Path(tmp), "engineer", {})
                helpers.result(helpers.start("build area 1"))
                helpers.result(helpers.start("Review area 1"))
                helpers.close()
            build, review = (next(v for k, v in steps.items() if task in k) for task in ("build area 1", "Review area 1"))
            self.assertIsNone(build[1])
            self.assertIsNone(build[roles.REVIEW_STEPS])
            self.assertEqual(build[roles.HELPER_STEPS], roles.WRAP_UP.format(steps=roles.HELPER_STEPS))
            self.assertEqual(review[roles.REVIEW_STEPS], roles.WRAP_UP.format(steps=roles.REVIEW_STEPS))
            self.assertIsNone(review[roles.HELPER_STEPS])
        finally:
            roles.loop.run, roles.new_llm = original, original_llm


class UnmatchedPatternTest(unittest.TestCase):
    def test_off_values_and_unmatched_patterns_skip_the_run(self):
        self.assertIsNone(loop.requested_check(json.dumps({"input": "", "check": "false"})))
        self.assertEqual(loop.requested_check(json.dumps({"input": "", "check": "all"})), "")
        with tempfile.TemporaryDirectory() as tmp:
            specs = Path(tmp) / "backend" / "test-e2e"
            specs.mkdir(parents=True)
            (specs / "sort.spec.ts").write_text("")
            self.assertEqual(checks.unmatched(Path(tmp), "sort|filter"), "")
            self.assertIn("sort.spec.ts", checks.unmatched(Path(tmp), "pivot"))
            ok, report = checks.check(Path(tmp), "pivot")
            self.assertFalse(ok)
            self.assertIn("no e2e spec file matches", report)


class SnapshotTest(unittest.TestCase):
    def test_failure_shows_the_page_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "error-context.md"
            path.write_text('# Page snapshot\n\n```yaml\n- main [ref=e2]:\n  - button "Save" [ref=e4]\n```\n')
            snapshot = checks.page_snapshot({"attachments": [{"name": "error-context", "path": str(path)}]})
            self.assertEqual(snapshot, '    - main:\n      - button "Save"')
            self.assertEqual(checks.page_snapshot({"attachments": []}), "")
            self.assertEqual(checks.failure_names(f"- a.spec.ts :: t\n  boom\n  Page at the failure:\n{snapshot}"),
                             ["a.spec.ts :: t"])


class SkillTest(unittest.TestCase):
    def test_skills_are_listed_and_copied_for_reading_on_demand(self):
        import main
        import roles
        saved = roles.SKILLS
        try:
            with tempfile.TemporaryDirectory() as tmp:
                roles.SKILLS = Path(tmp) / "skills"
                self.assertEqual(roles.skills_section(), "")
                (roles.SKILLS / "org-pages").mkdir(parents=True)
                (roles.SKILLS / "org-pages" / "SKILL.md").write_text(
                    "---\nname: org-pages\ndescription: URLs of organization pages. Load before planning.\n---\n"
                    "Organization pages live at /<org>.\n")
                section = roles.skills_section()
                self.assertIn("- `.agent/skills/org-pages/SKILL.md`: URLs of organization pages.", section)
                self.assertNotIn("/<org>", section)
                workspace = Path(tmp) / "ws"
                workspace.mkdir()
                original = main.checks.install
                main.checks.install = lambda root: ""
                try:
                    main.setup(workspace)
                finally:
                    main.checks.install = original
                self.assertIn("/<org>", (workspace / ".agent" / "skills" / "org-pages" / "SKILL.md").read_text())
        finally:
            roles.SKILLS = saved

class ForkTest(unittest.TestCase):
    def test_fork_keeps_the_prefix_and_answers_every_pending_call(self):
        import roles
        messages = [{"role": "user", "content": "task"},
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"id": "a", "type": "function", "function": {"name": "read", "arguments": "{}"}},
                        {"id": "s", "type": "function", "function": {"name": "subagent", "arguments": "{}"}},
                        {"id": "b", "type": "function", "function": {"name": "check", "arguments": "{}"}}]},
                    {"role": "tool", "tool_call_id": "a", "content": "file"}]
        history = roles.forked(messages, "s")
        self.assertEqual(history[:3], messages)  # the lead's cached prefix is reused unchanged
        self.assertEqual({m["tool_call_id"] for m in history[2:]}, {"a", "s", "b"})
        self.assertEqual(len(messages), 3)  # the lead's own conversation is untouched

    def test_subagent_sees_the_same_tools_but_cannot_nest(self):
        import roles
        with tempfile.TemporaryDirectory() as tmp:
            tree = spec.Node("ROOT", "Demo", "FOLDER", "", [], [])
            engineer = roles.Engineer.__new__(roles.Engineer)
            engineer.atomics, engineer.tree = {}, tree
            lead, child = engineer.extras(lead=True), engineer.extras(lead=False)
            self.assertEqual([e.schema for e in lead.values()], [e.schema for e in child.values()])
            self.assertIn("only the lead", child["subagent"].run({}, [], "x"))


class ReportTest(unittest.TestCase):
    def test_failed_tests_excludes_flaky(self):
        report = ("build ok; fresh-database start ok; e2e 1/2 passed\nFAILED TESTS:\n- a.spec.ts :: breaks\n"
                  "E2E FAILURES:\n- a.spec.ts :: breaks\n  boom")
        self.assertEqual(checks.failed_tests(report), {"a.spec.ts :: breaks"})


class FirstTokenTest(unittest.TestCase):
    def setUp(self):
        import llm
        self.saved = llm.HEDGE_SECONDS, llm.FIRST_TOKEN_SECONDS
        llm.HEDGE_SECONDS, llm.FIRST_TOKEN_SECONDS = 0.5, 1.5

    def tearDown(self):
        import llm
        llm.HEDGE_SECONDS, llm.FIRST_TOKEN_SECONDS = self.saved

    @staticmethod
    def chunk(text):
        from types import SimpleNamespace as N
        return N(choices=[N(delta=N(content=text, tool_calls=None, reasoning_content=None, model_extra={}),
                            finish_reason=None)], usage=None)

    def test_a_stuck_request_is_hedged_and_a_silent_one_cut_short(self):
        import time as clock
        import llm
        calls = []

        def first_stuck():
            calls.append(1)
            if len(calls) == 1:
                clock.sleep(5)
            return (c for c in [self.chunk("a"), self.chunk("b")])
        started = clock.time()
        texts = [c.choices[0].delta.content for c in llm.paced(first_stuck, {"sent": clock.time()})]
        self.assertEqual(texts, ["a", "b"])  # the second request answered
        self.assertLess(clock.time() - started, 1.2)
        self.assertEqual(len(calls), 2)

        def silent():
            clock.sleep(5)
            return (c for c in [])
        started = clock.time()
        with self.assertRaises(llm.FirstTokenTimeout):
            list(llm.paced(silent, {"sent": clock.time()}))
        self.assertLess(clock.time() - started, 2)


class StreamTest(unittest.TestCase):
    def test_stream_is_assembled_into_a_replayable_message(self):
        from types import SimpleNamespace as N
        import llm

        def chunk(delta=None, finish=None, usage=None):
            fields = {"content": None, "tool_calls": None, "model_extra": {}, **(delta or {})}
            choices = [N(delta=N(**fields), finish_reason=finish)] if delta is not None or finish else []
            return N(choices=choices, usage=usage)
        call = lambda i, id=None, name=None, args=None: N(index=i, id=id, function=N(name=name, arguments=args))
        stream = [chunk({"reasoning_content": "think "}), chunk({"reasoning_content": "more"}),
                  chunk({"content": "ok"}),
                  chunk({"tool_calls": [call(0, "c1", "read", '{"pa')]}), chunk({"tool_calls": [call(0, args='th": 1}')]}),
                  chunk({"tool_calls": [call(1, "c2", "bash", "{}")]}), chunk(finish="tool_calls"),
                  chunk(usage=N(prompt_tokens=5, completion_tokens=3))]
        message, finish, usage = llm.LLM._receive(stream)
        self.assertEqual(message["reasoning_content"], "think more")
        self.assertEqual(message["content"], "ok")
        self.assertEqual([c["function"]["arguments"] for c in message["tool_calls"]], ['{"path": 1}', "{}"])
        self.assertEqual(message["tool_calls"][0]["id"], "c1")
        self.assertEqual(finish, "tool_calls")
        self.assertEqual(usage.prompt_tokens, 5)


class BrokenStreamTest(unittest.TestCase):
    def test_a_cut_stream_is_resent_with_low_effort_and_is_not_an_outage(self):
        from types import SimpleNamespace as N
        import json as js
        import llm

        def chunk(text=None, finish=None, usage=None):
            delta = N(content=text, tool_calls=None, reasoning_content=None, model_extra={})
            return N(choices=[N(delta=delta, finish_reason=finish)] if text or finish else [], usage=usage)
        efforts, limits = [], []

        def create(**request):
            efforts.append(request["extra_body"]["reasoning_effort"])
            limits.append(request["max_tokens"])
            def stream():
                yield chunk("partial ")
                if len(efforts) < 3:
                    raise js.JSONDecodeError("Unterminated string", "{", 1)
                yield chunk("done", finish="stop")
                yield chunk(usage=N(prompt_tokens=5, completion_tokens=2, prompt_tokens_details=None,
                                    completion_tokens_details=None))
            return stream()
        saved = llm.RETRY_SECONDS
        llm.RETRY_SECONDS = 1  # a cut stream that just delivered data must not count as an outage
        try:
            client = llm.LLM("deepseek-v4-flash-vision-exp", api_key="x", base_url="http://127.0.0.1:9")
            client.client = N(chat=N(completions=N(create=create)))
            reply = client.chat("sys", [{"role": "user", "content": "hi"}], [])
        finally:
            llm.RETRY_SECONDS = saved
        self.assertEqual(reply.text, "partial done")
        self.assertEqual(efforts, ["high", "high", "low"])
        self.assertEqual(limits[1:], [4096, 4096])  # below the cut, never under 4096 tokens


def done_llm():
    """Calls done on every reply, with summary s<n>."""
    class LLM:
        vision, calls = False, 0

        def chat(self, system, messages, tools):
            self.calls += 1
            call = {"id": f"d{self.calls}", "name": "done", "arguments": json.dumps({"summary": f"s{self.calls}"})}
            message = {"role": "assistant", "content": "", "tool_calls": [
                {"id": call["id"], "type": "function", "function": {"name": "done", "arguments": call["arguments"]}}]}
            return type("R", (), {"message": message, "tool_calls": [call], "text": ""})()
    return LLM()


def lead(tmp: str, helpers=None):
    """An Engineer without a model or requirements."""
    import roles
    engineer = roles.Engineer.__new__(roles.Engineer)
    engineer.root, engineer.req_dir, engineer.label, engineer.steps = Path(tmp), Path(tmp), "engineer", 10
    engineer.llm, engineer.task_builder, engineer.last_report, engineer.built = FakeLLM(), None, "", []
    engineer.settled, engineer.helpers = False, helpers
    return engineer


class SessionEndTest(unittest.TestCase):
    def test_done_is_refused_while_subagents_run_and_close_stops_them(self):
        import threading
        import roles
        refusals, final = ["busy", None], []
        with tempfile.TemporaryDirectory() as tmp:
            summary = loop.run(done_llm(), "sys", "task", Tools(Path(tmp)), refuse_done=lambda: refusals.pop(0),
                               final=final)
        self.assertEqual(summary, "s2")  # the refused done got the refusal as its result
        self.assertEqual(next(m["content"] for m in final if m.get("tool_call_id") == "d1"), "busy")

        release = threading.Event()
        original, original_llm = roles.loop.run, roles.new_llm

        def session(llm, system, text, tools, **kwargs):
            release.wait(5)
            kwargs["on_step"](1, [])  # the step boundary after close raises
            (tools.root / "late.txt").write_text("x")
            return "done"
        roles.loop.run, roles.new_llm = session, (lambda model=None: FakeLLM())
        try:
            with tempfile.TemporaryDirectory() as tmp:
                engineer = lead(tmp, roles.Helpers(Path(tmp), Path(tmp), "engineer", {}))
                number = engineer.helpers.start("build area 2")
                self.assertIn("still running", engineer.refuse_done())
                threading.Timer(0.2, release.set).start()
                engineer.helpers.close()  # returns once the subagent stopped
                self.assertFalse((Path(tmp) / "late.txt").exists())
                self.assertIn("session ended", engineer.helpers.result(number))
                self.assertIsNone(engineer.refuse_done())
        finally:
            roles.loop.run, roles.new_llm = original, original_llm


class SubagentTaskTest(unittest.TestCase):
    def test_compaction_restores_the_subagent_task_and_listings_show_the_latest_message(self):
        import threading
        import roles
        seen, release = [], threading.Event()
        original, original_llm = roles.loop.run, roles.new_llm

        def session(llm, system, text, tools, **kwargs):
            seen.append((text, kwargs["refresh"]()))
            release.wait(5)
            return "ok"
        roles.loop.run, roles.new_llm = session, (lambda model=None: FakeLLM())
        try:
            with tempfile.TemporaryDirectory() as tmp:
                engineer = lead(tmp, roles.Helpers(Path(tmp), Path(tmp), "engineer", {}, "## Product conventions\nX\n\n"))
                number = engineer.helpers.start("review area 1", history=[{"role": "user", "content": "lead task"}])
                engineer.helpers.send(number, "also check the dialog")
                self.assertIn("also check the dialog", engineer.refresh()[1])
                release.set()
                engineer.helpers.result(number)
                engineer.helpers.close()
            text, (task, facts) = seen[0]
            self.assertTrue(text.startswith(roles.FORKED))
            self.assertTrue(task.startswith("## Product conventions"))  # the notes first: a prefix all subagents share
            self.assertIn("review area 1", task)
            self.assertNotIn("conversation so far", task)
        finally:
            roles.loop.run, roles.new_llm = original, original_llm


class ResumeTest(unittest.TestCase):
    def test_resume_without_a_checkpoint_archives_and_a_resumed_session_gets_the_note(self):
        from checkpoint import Transcript, commit
        from tools import shell
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell("git init -q && git config user.email t@t && git config user.name t", root, 30)
            (root / ".gitignore").write_text(".agent/\n")
            commit(root, "init")
            Transcript(root, "p").message({"role": "user", "content": "old attempt"})
            loop.run(ScriptedLLM(), "sys", "task", Tools(root), transcript=Transcript(root, "p"), resume="last",
                     note="resumed", max_steps=10)
            self.assertEqual(len(list((root / ".agent").glob("p.replaced-*.jsonl"))), 1)
            messages = Transcript(root, "p").load()[0]
            self.assertEqual([m["content"] for m in messages if m["role"] == "user"], ["task"])
            llm = ScriptedLLM()
            llm.calls = 1
            loop.run(llm, "sys", "task", Tools(root), transcript=Transcript(root, "p"), resume=1, note="resumed",
                     max_steps=10)
            messages = Transcript(root, "p").load()[0]
            self.assertEqual([m["content"] for m in messages if m["role"] == "user"], ["task", "resumed"])

    def test_engineer_tells_a_resumed_lead_its_subagents_are_gone(self):
        import roles
        captured = {}
        original = roles.loop.run
        roles.loop.run = lambda *args, **kwargs: captured.update(kwargs) or "ok"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                lead(tmp, roles.Helpers(Path(tmp), Path(tmp), "engineer", {})).run("task", resume="last")
        finally:
            roles.loop.run = original
        self.assertEqual(captured["note"], roles.RESUMED)
        self.assertIn("gone", roles.RESUMED)


class ModelLimitsTest(unittest.TestCase):
    def test_window_and_output_limit_follow_the_effective_model(self):
        import os
        import subprocess
        code = ("import compaction, llm; print(llm.DEFAULT_MODEL, llm.SLOW_START, llm.MAX_TOKENS, "
                "compaction.TRIGGER_TOKENS)")

        def limits(model: str) -> list[str]:
            env = {k: v for k, v in os.environ.items() if not k.startswith(("MODEL", "AGENT_"))}
            env.update({"MODEL": model} if model else {})
            return subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent, env=env,
                                  capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(limits(""), ["glm-5.3-flash", "True", "65536", "150000"])  # trigger + output < 256K
        self.assertEqual(limits("kimi-k2"), ["kimi-k2", "False", "65536", "150000"])
        self.assertEqual(limits("deepseek-v4-flash"), ["deepseek-v4-flash", "False", "131072", "400000"])


class CheckToolTest(unittest.TestCase):
    def test_all_runs_the_whole_suite(self):
        seen, original = [], checks.check
        checks.check = lambda root, pattern="": seen.append(pattern) or (True, "e2e 2/2 passed")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                engineer = lead(tmp)
                self.assertTrue(engineer.check({"pattern": " all "}).startswith("CHECK PASSED"))
                self.assertTrue(engineer.settled)
                engineer.check({"pattern": "ALL"}, lead=False)
        finally:
            checks.check = original
        self.assertEqual(seen, ["", ""])

    def test_app_server_gets_no_secrets(self):
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
                "ARCBENCH_COOKIE": "c", "ARCBENCH_PASSWORD": "p", "OPENAI_API_KEY": "k"}), \
                mock.patch.object(checks.subprocess, "Popen") as popen:
            checks.Server(Path(tmp))
        env = popen.call_args.kwargs["env"]
        for name in ("ARCBENCH_COOKIE", "ARCBENCH_PASSWORD", "OPENAI_API_KEY"):
            self.assertNotIn(name, env)
        self.assertIn("PORT", env)


if __name__ == "__main__":
    unittest.main()

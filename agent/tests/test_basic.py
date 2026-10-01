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
        self.assertIn("small verified slices", main.SYSTEM)


class SpecTest(unittest.TestCase):
    def test_groups_and_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "requirements.yaml").write_text(YAML)
            root = spec.load(Path(tmp))
        groups = spec.groups(root)
        self.assertEqual([g.id for g in groups], ["REQ-1"])
        card = spec.group_card(groups[0])
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
    def test_apply_writes_good_changes_and_reports_failed_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools, root = Tools(Path(tmp)), Path(tmp)
            (root / "a.js").write_text("one\ntwo\n")
            bad = tools.run("apply", json.dumps({"changes": [
                {"path": "new.js", "content": "x"}, {"path": "a.js", "old_text": "missing", "new_text": "y"}]}))
            self.assertIn("1 of 2 changes failed", bad)
            self.assertIn("change 2 (a.js)", bad)
            self.assertEqual((root / "new.js").read_text(), "x")
            self.assertEqual((root / "a.js").read_text(), "one\ntwo\n")
            half = tools.run("apply", json.dumps({"changes": [
                {"path": "a.js", "old_text": "one", "new_text": "1"}, {"path": "a.js", "old_text": "nope", "new_text": "y"}]}))
            self.assertIn("left unchanged", half)
            self.assertEqual((root / "a.js").read_text(), "one\ntwo\n")  # never half edited
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
        messages = [{"role": "user", "content": "task"}]
        for i in range(215):  # between the milestone threshold and the regular trigger
            messages += [{"role": "assistant", "content": "x" * 6000}, {"role": "user", "content": f"r{i}"}]
        size = compaction.estimate(messages)
        self.assertTrue(compaction.MILESTONE_TOKENS < size < compaction.TRIGGER_TOKENS)
        state = {}
        self.assertIs(compaction.compact(FakeLLM(), "s", [], messages, state), messages)  # no milestone: wait
        new = compaction.compact(FakeLLM(), "s", [], messages, state, milestone=True)
        self.assertLess(compaction.estimate(new), compaction.MILESTONE_KEEP_TOKENS + 10000)
        self.assertEqual(new[-1], messages[-1])


class TrimTest(unittest.TestCase):
    def history(self, turns):
        messages = [{"role": "user", "content": "task"}]
        for i in range(turns):
            path = "once.ts" if i == 0 else "app.ts"  # app.ts is rewritten every turn, once.ts never again
            args = json.dumps({"path": path, "content": "x" * 5000})
            messages += [{"role": "assistant", "content": "", "reasoning_content": "r" * 8000,
                          "tool_calls": [{"id": f"c{i}", "type": "function",
                                          "function": {"name": "write", "arguments": args}}]},
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
        self.assertEqual(rewritten["path"], "app.ts")
        self.assertIn("trimmed", rewritten["content"])  # a later write superseded it
        self.assertIn("trimmed", trimmed[2]["content"])
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


if __name__ == "__main__":
    unittest.main()

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
        self.assertIn("Hidden acceptance tests for this requirement: 2", card)


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
    def test_native_popups_flagged_unless_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "frontend", "src")
            src.mkdir(parents=True)
            (src / "A.tsx").write_text('<select id="a">\n<select id="b"> {/* required by REQ-6-1 */}\nconfirm("x")\n')
            found = checks.static(Path(tmp))
        self.assertEqual(len(found), 2)


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def chat(self, system, messages, tools):
        self.prompts.append(messages[0]["content"])
        return type("R", (), {"text": f"summary {len(self.prompts)}"})()


class CompactionTest(unittest.TestCase):
    def history(self, turns):
        messages = [{"role": "user", "content": "task"}]
        for i in range(turns):
            args = json.dumps({"path": f"f{i}.js", "content": "x" * 3000})
            messages.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": str(i), "type": "function", "function": {"name": "write", "arguments": args}}]})
            messages.append({"role": "tool", "tool_call_id": str(i), "content": "y" * 3000})
        return messages

    def test_summary_replaces_old_turns_and_keeps_pairs(self):
        llm, state = FakeLLM(), {}
        old = self.history(80)
        new = compaction.compact(llm, old, state)
        self.assertEqual(new[0]["content"], "task")
        self.assertTrue(new[1]["content"].startswith(compaction.SUMMARY_TAG))
        self.assertIn("f0.js", new[1]["content"])
        self.assertEqual(new[2]["role"], "assistant")
        self.assertEqual(new[-1], old[-1])
        self.assertLess(compaction.estimate(new), compaction.TRIGGER_TOKENS)
        # a second compaction merges the previous summary instead of re-summarizing it
        again = compaction.compact(llm, new + self.history(80)[1:], state)
        self.assertIn("summary 1", llm.prompts[1])
        self.assertTrue(again[1]["content"].startswith(compaction.SUMMARY_TAG + "\nsummary 2"))

    def test_small_history_untouched(self):
        small = self.history(3)
        self.assertIs(compaction.compact(FakeLLM(), small, {}), small)


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


if __name__ == "__main__":
    unittest.main()

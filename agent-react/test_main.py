import contextlib
import copy
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from agent_validation import ProjectValidator, ValidationResult


def completion(calls=None):
    message = Mock(tool_calls=calls or [])
    message.model_dump.return_value = {"role": "assistant", "content": "done"}
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


class DeliveryTests(unittest.TestCase):
    def test_passing_self_tests_start_a_fresh_requirement_audit(self):
        requests = []
        responses = iter([completion(), completion()])

        def create(**kwargs):
            requests.append(copy.deepcopy(kwargs))
            return next(responses)

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        validator = Mock()
        validator.validate.return_value = ValidationResult(ok=True, suite_kind="self-authored")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"AGENT_MAX_STEPS": "4", "OPENAI_WIRE_API": "chat"}), \
                contextlib.redirect_stdout(io.StringIO()):
            result = main.react_loop(client, "deepseek-v4-flash", "source instructions", Path(tmp), validator)
        self.assertTrue(result.ok)
        self.assertEqual(len(requests), 2, "self-authored green tests must not end delivery immediately")
        self.assertEqual(len(requests[1]["messages"]), 2, "audit must not inherit implementation reasoning")
        self.assertIn(".arc/requirements", requests[1]["messages"][1]["content"])
        self.assertEqual(validator.validate.call_count, 2)
        validator.begin_source_audit.assert_called_once()

    def test_audit_can_correct_wrong_self_test_then_freezes_new_expectation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "backend/agent-smoke-tests"
            folder.mkdir(parents=True)
            spec = folder / "organization.spec.js"
            spec.write_text("expect(heading).toHaveText(displayName)")
            validator = ProjectValidator(root, folder)
            self.assertEqual(validator._check_baseline(), [])
            first_id = validator.run_id
            validator.begin_source_audit()
            spec.write_text("expect(heading).toHaveText(identifier)")
            self.assertEqual(validator._check_baseline(), [])
            self.assertNotEqual(first_id, validator.run_id)
            spec.write_text("expect(heading).toBeVisible()")
            self.assertTrue(validator._check_baseline(), "audit must not permit later weakening")

    def test_prepared_runner_application_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output = root / "source", root / "output"
            for folder in (source, output):
                for part in ("frontend", "backend"):
                    (folder / part).mkdir(parents=True)
                    (folder / part / "package.json").write_text("{}")
            (source / "frontend/app.js").write_text("blank starter")
            (output / "frontend/app.js").write_text("evolved application")
            main.copy_template(source, output)
            self.assertEqual((output / "frontend/app.js").read_text(), "evolved application")


if __name__ == "__main__":
    unittest.main()

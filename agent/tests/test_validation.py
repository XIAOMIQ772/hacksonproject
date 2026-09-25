import unittest
import tempfile
import contextlib
import io
import os
import json
from pathlib import Path
from unittest.mock import patch
import support
from agent_validation import ProjectValidator


class ValidationTests(unittest.TestCase):
    def test_snapshot_survives_restart_and_rejects_modified_passing_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'backend/agent-smoke-tests'
            folder.mkdir(parents=True)
            spec = folder / 'flow.spec.js'
            spec.write_text('expect(actual).toEqual(required)')
            first = ProjectValidator(root, folder)
            self.assertEqual(first._check_baseline(), [])
            persisted = json.loads(json.dumps(first.snapshot()))
            resumed = ProjectValidator(root, folder)
            resumed.restore(persisted)
            self.assertEqual(resumed._check_baseline(), [])
            spec.write_text('expect(true).toBe(true)')
            self.assertTrue(any('Frozen validation file modified' in error for error in resumed._check_baseline()))
            self.assertEqual(resumed.run_id, first.run_id)

    def test_actual_build_command_does_not_receive_model_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            for folder in ('frontend', 'backend'):
                (root / folder / 'node_modules').mkdir(parents=True)
                (root / folder / 'package.json').write_text('{}')
            (root / 'frontend/package.json').write_text(json.dumps({'scripts': {'build': 'node check.cjs'}}))
            (root / 'frontend/check.cjs').write_text("""
const fs = require('fs');
fs.writeFileSync('received.json', JSON.stringify({
  key: process.env.OPENAI_API_KEY ?? null,
  token: process.env.ARCBENCH_TOKEN ?? null,
  sentinel: process.env.AGENT_TEST_SENTINEL
}));
""")
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'never-share', 'ARCBENCH_TOKEN': 'never-share',
                                         'AGENT_TEST_SENTINEL': 'present'}):
                result = ProjectValidator(root, None).validate()
            self.assertFalse(result.ok)  # This fixture only exercises the build boundary.
            self.assertEqual(json.loads((root / 'frontend/received.json').read_text()),
                             {'key': None, 'token': None, 'sentinel': 'present'})

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

    def test_failed_verification_does_not_freeze_unproven_test_expectations(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            folder = root / "backend/agent-smoke-tests"
            folder.mkdir(parents=True)
            spec = folder / "organization.spec.js"
            spec.write_text("expect(heading).toHaveText(displayName)")
            validator = ProjectValidator(root, folder)

            def run_suite(result, evidence):
                result.tests.append({"title": "organization heading", "passed": "identifier" in spec.read_text(),
                                     "error": "heading differs from expected identifier"})

            with patch.object(validator, "_validate", side_effect=run_suite) as run:
                self.assertFalse(validator.validate().ok)
                spec.write_text("expect(heading).toHaveText(identifier)")
                self.assertTrue(validator.validate().ok, "failed checks must remain correctable from the source")
                spec.write_text("expect(heading).toBeVisible()")
                rejected = validator.validate()
                self.assertFalse(rejected.ok, "passing coverage must remain frozen")
                self.assertTrue(any("Frozen validation file modified" in error for error in rejected.errors))
                self.assertEqual(run.call_count, 2, "reject weakened checks before executing them")

            validator.begin_source_audit()
            def rewrite_during_execution(result, evidence):
                spec.write_text("test.skip('organization heading')")
                result.tests.append({"title": "organization heading", "passed": True})
            with patch.object(validator, "_validate", side_effect=rewrite_during_execution):
                rejected = validator.validate()
                self.assertFalse(rejected.ok, "execution must not rewrite an unfrozen test either")
                self.assertTrue(any("Frozen validation file modified" in error for error in rejected.errors))

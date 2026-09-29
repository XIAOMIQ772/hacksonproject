import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from support import FakeModel, Validator, completion, call
import main


class EntrypointTests(unittest.TestCase):
    def test_full_entrypoint_preserves_app_and_resumes_same_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'requirements', Path(tmp) / 'app'
            source.mkdir()
            (source / 'requirements.yaml').write_text('id: REQ-1\nname: Sample\ntype: ATOMIC\ndescription: Implement sample.\n')
            for part in ['frontend', 'backend']:
                (output / part).mkdir(parents=True)
                (output / part / 'package.json').write_text('{}')
            (output / 'frontend/preserve.txt').write_text('existing application')
            runtime = Mock()
            first = FakeModel([completion([call('write', '{"path":"app.txt","content":"implemented"}')]),
                               completion(), completion()])
            second = FakeModel([])
            args = [str(source), '--output-dir', str(output)]
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key', 'MODEL': 'test-model', 'OPENAI_WIRE_API': 'chat'}), \
                    patch.object(main.AgentRuntime, 'from_env', return_value=runtime), \
                    patch.object(main, 'ProjectValidator', side_effect=[Validator(), Validator()]), \
                    patch.object(main, 'Model', side_effect=[first, second]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main.main(args), 0)
                path = next((output / '.arc/session').glob('*.jsonl'))
                before = path.read_bytes()
                self.assertEqual(main.main(args), 0)
            self.assertTrue(path.read_bytes().startswith(before))
            self.assertEqual(len(list((output / '.arc/session').glob('*.jsonl'))), 1)
            self.assertEqual(second.requests, [])
            self.assertEqual((output / 'frontend/preserve.txt').read_text(), 'existing application')
            self.assertEqual((output / 'app.txt').read_text(), 'implemented')
            self.assertNotIn('test-key', path.read_text())
            self.assertTrue((output / '.arc/requirements/index.md').is_file())

    def test_copy_template_does_not_overwrite_partially_prepared_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / 'frontend').mkdir()
            (output / 'frontend/app.js').write_text('user code without package file yet')
            main.copy_template(output)
            self.assertEqual((output / 'frontend/app.js').read_text(), 'user code without package file yet')
            self.assertFalse((output / 'frontend/package.json').exists())
            self.assertTrue((output / 'backend/package.json').exists())

import os
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch

from support import session


class ToolTests(unittest.TestCase):
    def test_real_shell_outputs_are_bounded_and_credentials_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, tools = session(tmp)
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'secret-test-key', 'ARCBENCH_PASSWORD': 'secret-password'}):
                output = tools.run('bash', {'command': "python3 -c 'import os; print(os.getenv(\"OPENAI_API_KEY\")); print(os.getenv(\"ARCBENCH_PASSWORD\")); print(\"x\"*20000)'"})
            self.assertIn('None\nNone', output)
            self.assertNotIn('secret-test', output)
            self.assertLess(len(output), 13000)
            files = list(tools.artifacts.glob('*-command.log'))
            self.assertGreater(files[0].stat().st_size, 20000)
            log.close()

    def test_paths_symlinks_and_unique_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, tools = session(tmp)
            outside = Path(tmp) / 'outside'
            outside.write_text('keep')
            (tools.root / 'link').symlink_to(outside)
            for path in ['../outside', 'link', str(log.path), '.env']:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    tools.run('write', {'path': path, 'content': 'overwrite'})
            self.assertEqual(outside.read_text(), 'keep')
            tools.run('write', {'path': 'app', 'content': 'one one'})
            with self.assertRaisesRegex(ValueError, '2 times'):
                tools.run('edit', {'path': 'app', 'old': 'one', 'new': 'two'})
            tools.run('edit', {'path': 'app', 'old': 'one one', 'new': 'two'})
            self.assertIn('two', tools.run('read', {'path': 'app'}))
            log.close()

    def test_shell_timeout_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, tools = session(tmp)
            result = tools.run('bash', {'command': 'sleep 20', 'timeout': 1})
            self.assertIn('exit code 124', result)
            self.assertIn('timed out', result)
            log.close()

    def test_private_task_tests_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, tools = session(tmp)
            private = tools.requirements / 'tests/private.spec.js'
            private.parent.mkdir()
            private.write_text('never used')
            with self.assertRaisesRegex(ValueError, 'Evaluation test'):
                tools.run('read', {'path': str(private)})
            log.close()

    def test_shell_exit_kills_descendants_that_ignore_sigterm(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, tools = session(tmp)
            script = tools.root / 'child.py'
            script.write_text('import signal, time\nfrom pathlib import Path\n'
                              'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                              'Path("ready").touch()\ntime.sleep(0.6)\nPath("leaked").touch()\n')
            result = tools.run('bash', {'command': 'python3 child.py & while [ ! -f ready ]; do sleep 0.01; done'})
            self.assertIn('exit code 0', result)
            time.sleep(0.8)
            self.assertFalse((tools.root / 'leaked').exists())
            log.close()

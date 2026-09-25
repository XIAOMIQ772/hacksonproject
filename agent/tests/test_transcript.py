import json
import tempfile
import unittest
from pathlib import Path

from support import Transcript, session, call, completion


class TranscriptTests(unittest.TestCase):
    def test_projection_and_repeated_compaction_preserve_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, _ = session(tmp)
            a = log.append('message', role='assistant', items=[{'role': 'assistant', 'content': 'first'}])
            b = log.append('message', role='user', items=[{'role': 'user', 'content': 'second'}])
            original = log.path.read_bytes()
            log.append('compaction', through_id=a['id'], summary='summary one')
            self.assertEqual(log.projection()[-1]['content'], 'second')
            self.assertTrue(log.path.read_bytes().startswith(original))
            log.append('message', role='assistant', items=[{'role': 'assistant', 'content': 'third'}])
            log.append('compaction', through_id=b['id'], summary='summary two')
            self.assertEqual([x['content'] for x in log.projection()],
                             ['Implement the app', 'Earlier work summary (original transcript retained):\nsummary two', 'third'])
            log.close()
            with Transcript(Path(tmp) / 'session/transcript.jsonl') as resumed:
                self.assertEqual(resumed.projection()[-1]['content'], 'third')
                self.assertTrue(resumed.path.read_bytes().startswith(original))

    def test_tool_calls_and_results_cannot_be_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, _ = session(tmp)
            log.append('message', role='user', items=[{'role': 'user', 'content': 'older' * 100}])
            c = call('read', '{"path":"app.js"}')
            log.append('message', role='assistant', items=completion([c]).items, calls=[c])
            with self.assertRaisesRegex(ValueError, 'unfinished'):
                log.compactable(1)
            log.append('message', role='tool', call_id=c['id'], items=[{'role': 'tool', 'tool_call_id': c['id'], 'content': 'code'}])
            old, _ = log.compactable(1)
            self.assertEqual(len(old), 1)
            self.assertEqual(old[0]['role'], 'user')
            log.close()

    def test_torn_tail_is_quarantined_but_committed_history_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, _ = session(tmp)
            path, original = log.path, log.path.read_bytes()
            log.close()
            with path.open('ab') as stream:
                stream.write(b'{"incomplete":')
            with Transcript(path) as resumed:
                self.assertEqual(resumed.events[-1]['type'], 'tail_recovered')
                self.assertTrue(path.read_bytes().startswith(original))
                self.assertEqual(Path(resumed.events[-1]['artifact']).read_bytes(), b'{"incomplete":')
            with Transcript(path) as reopened:
                self.assertEqual(sum(e['type'] == 'tail_recovered' for e in reopened.events), 1)

    def test_committed_corruption_fails_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, _ = session(tmp)
            path = log.path
            log.close()
            with path.open('ab') as stream:
                stream.write(b'{invalid}\n')
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'Corrupt'):
                Transcript(path)
            self.assertEqual(path.read_bytes(), before)

    def test_single_writer_and_payload_detachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, _ = session(tmp)
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                Transcript(log.path)
            items = [{'role': 'user', 'content': 'immutable'}]
            event = log.append('message', role='user', items=items)
            items[0]['content'] = 'changed'
            event['items'][0]['content'] = 'also changed'
            self.assertEqual(log.projection()[-1]['content'], 'immutable')
            log.close()

    def test_phase_reset_is_an_appended_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, _ = session(tmp)
            log.append('message', role='assistant', items=[{'role': 'assistant', 'content': 'biased implementation reasoning'}])
            original = log.path.read_bytes()
            log.append('phase', name='source_audit', prompt='Independently reread source')
            self.assertEqual(log.projection(), [{'role': 'user', 'content': 'Independently reread source'}])
            self.assertTrue(log.path.read_bytes().startswith(original))
            log.close()

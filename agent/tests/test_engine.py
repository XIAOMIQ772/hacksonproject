import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from openai import BadRequestError

from support import session, engine, completion, call, FakeModel, Validator, Transcript
from coding_tools import TOOLS
from engine import AUDIT_PROMPT
from transcript import encoded


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log, self.tools = session(self.tmp.name)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.log.close()
        self.output.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_actual_write_then_verify_and_fresh_source_audit(self):
        model = FakeModel([completion([call('write', '{"path":"app.py","content":"print(1)"}')]),
                           completion([call('verify')]), completion([call('verify')])])
        validator = Validator()
        result = engine(self.log, self.tools, model, validator).run()
        self.assertTrue(result.ok)
        self.assertEqual((self.tools.root / 'app.py').read_text(), 'print(1)')
        self.assertEqual(validator.audits, 1)
        self.assertEqual(model.requests[-1]['messages'], [{'role': 'user', 'content': AUDIT_PROMPT}])
        self.assertEqual(model.requests[1]['messages'][:len(model.requests[0]['messages'])], model.requests[0]['messages'])
        self.assertEqual(self.log.token_usage(), 60)

    def test_resume_does_not_repeat_completed_tool_and_executes_unstarted_tool(self):
        calls = [call('write', '{"path":"one","content":"first"}', 'a'),
                 call('write', '{"path":"two","content":"second"}', 'b')]
        assistant = self.log.append('message', role='assistant', items=completion(calls).items, calls=calls)
        (self.tools.root / 'one').write_text('user subsequently changed this')
        self.log.append('message', role='tool', assistant_id=assistant['id'], call_id='a',
                        items=FakeModel().tool_result(calls[0], 'written'), status='completed')
        result = engine(self.log, self.tools, FakeModel([completion(), completion()])).run()
        self.assertTrue(result.ok)
        self.assertEqual((self.tools.root / 'one').read_text(), 'user subsequently changed this')
        self.assertEqual((self.tools.root / 'two').read_text(), 'second')

    def test_unknown_tool_outcome_is_not_reexecuted_or_followed_by_more_writes(self):
        calls = [call('bash', '{"command":"echo duplicate >> count"}', 'a'),
                 call('write', '{"path":"bad","content":"unsafe"}', 'b')]
        assistant = self.log.append('message', role='assistant', items=completion(calls).items, calls=calls)
        self.log.append('tool_started', assistant_id=assistant['id'], call_id='a', name='bash')
        (self.tools.root / 'count').write_text('first\n')
        model = FakeModel([completion(), completion()])
        engine(self.log, self.tools, model).run()
        self.assertEqual((self.tools.root / 'count').read_text(), 'first\n')
        self.assertFalse((self.tools.root / 'bad').exists())
        results = [e for e in self.log.events if e.get('assistant_id') == assistant['id'] and e['type'] == 'message']
        self.assertEqual([r['status'] for r in results], ['interrupted', 'interrupted'])
        self.assertIn('inspect', json.dumps(model.requests[0]['messages']).lower())

    def test_response_saved_before_crash_is_consumed_without_duplicate_request(self):
        response = completion([call('write', '{"path":"recovered","content":"yes"}')])
        body = {'system': self.log.header['system'], 'messages': self.log.projection(), 'tools': TOOLS, 'purpose': 'agent'}
        self.log.append('model_response', input_sha256=hashlib.sha256(encoded(body)).hexdigest(),
                        completion=asdict(response), usage=response.usage)
        model = FakeModel([completion(), completion()])
        engine(self.log, self.tools, model, max_steps=3).run()
        self.assertEqual(len(model.requests), 2)
        self.assertEqual((self.tools.root / 'recovered').read_text(), 'yes')

    def test_a_write_after_verify_requires_another_verification(self):
        model = FakeModel([completion([call('verify', id='a'), call('write', '{"path":"app","content":"later"}', 'b')]),
                           completion(), completion()])
        validator = Validator()
        engine(self.log, self.tools, model, validator).run()
        self.assertEqual(validator.count, 3)
        self.assertEqual(validator.audits, 1)

    def test_failed_verification_and_step_exhaustion_never_deliver(self):
        validator = Validator([False, False])
        with self.assertRaisesRegex(RuntimeError, 'step budget'):
            engine(self.log, self.tools, FakeModel([completion(), completion()]), validator, max_steps=2).run()
        self.assertFalse(any(e['type'] == 'delivery' for e in self.log.events))
        self.assertEqual(validator.audits, 0)

    def test_completion_revalidates_current_files_instead_of_using_stale_success(self):
        engine(self.log, self.tools, FakeModel([completion(), completion()])).run()
        validator = Validator([False, False])
        with self.assertRaisesRegex(RuntimeError, 'step budget'):
            engine(self.log, self.tools, FakeModel([completion()]), validator, max_steps=3).run()
        self.assertEqual(validator.count, 2)
        self.assertEqual(sum(e['type'] == 'delivery' for e in self.log.events), 1)

    def test_truncated_tool_calls_never_execute(self):
        model = FakeModel([completion([call('write', '{"path":"bad","content":"no"}')], complete=False),
                           completion(), completion()])
        engine(self.log, self.tools, model).run()
        self.assertFalse((self.tools.root / 'bad').exists())
        self.assertEqual(sum(e['type'] == 'response_rejected' for e in self.log.events), 1)

    def test_crash_after_successful_verify_rechecks_files_before_delivery(self):
        self.log.append('phase', name='source_audit', prompt=AUDIT_PROMPT)
        calls = [call('verify')]
        assistant = self.log.append('message', role='assistant', items=completion(calls).items, calls=calls)
        saved = Validator().validate()
        self.log.append('message', role='tool', assistant_id=assistant['id'], call_id=calls[0]['id'],
                        items=FakeModel().tool_result(calls[0], saved.feedback()), status='completed',
                        validation=asdict(saved), validator_state={'verified_round': 1})
        validator = Validator([False, False])
        model = FakeModel([completion()])
        with self.assertRaisesRegex(RuntimeError, 'step budget'):
            engine(self.log, self.tools, model, validator, max_steps=2).run()
        self.assertEqual(validator.count, 2)
        self.assertFalse(any(e['type'] == 'delivery' for e in self.log.events))
        self.assertIn('saved verification is stale', str(model.requests[0]['messages']))

    def test_proxy_reset_is_retried_but_invalid_request_is_not(self):
        reset = BadRequestError('read: connection reset by peer', response=Mock(status_code=400, headers={}),
                                body={'code': 'proxy_error'})
        model = FakeModel([reset, completion(), completion()])
        with patch('engine.time.sleep') as sleep:
            engine(self.log, self.tools, model).run()
        sleep.assert_called_once_with(1)
        self.assertEqual(len(model.requests), 3)
        self.log.append('phase', name='implementation', prompt='New work')
        wrong = BadRequestError('invalid parameter', response=Mock(status_code=400, headers={}),
                                body={'code': 'invalid_request_error'})
        with self.assertRaises(BadRequestError):
            engine(self.log, self.tools, FakeModel([wrong]), Validator([False])).run()

    def test_compaction_is_append_only_and_retains_complete_recent_batches(self):
        for i in range(8):
            c = call('read', '{"path":"source"}', str(i))
            a = self.log.append('message', role='assistant', calls=[c], items=completion([c]).items)
            self.log.append('message', role='tool', assistant_id=a['id'], call_id=str(i),
                            items=FakeModel().tool_result(c, ('source-%d ' % i) * 500))
        before = self.log.path.read_bytes()
        model = FakeModel()
        runner = engine(self.log, self.tools, model, context_tokens=12000, keep_recent_tokens=2000)
        runner.compact(force=True)
        self.assertTrue(self.log.path.read_bytes().startswith(before))
        projected = self.log.projection()
        self.assertEqual(projected[2]['role'], 'assistant')
        self.assertEqual(projected[3]['role'], 'tool')
        self.assertIn('source-7', projected[-1]['content'])
        self.assertEqual(self.log.token_usage(), 20)

    def test_failed_compaction_retains_previous_context(self):
        for _ in range(4):
            self.log.append('message', role='user', items=[{'role': 'user', 'content': 'source ' * 500}])
        original = self.log.projection()
        model = FakeModel()
        model.summary = ''
        with self.assertRaisesRegex(RuntimeError, 'Compaction could not fit'):
            engine(self.log, self.tools, model, context_tokens=12000, keep_recent_tokens=1000).compact(force=True)
        self.assertEqual(self.log.projection(), original)

    def test_token_budget_prevents_request(self):
        model = FakeModel([completion()])
        with self.assertRaisesRegex(RuntimeError, 'token budget'):
            engine(self.log, self.tools, model, total_tokens=1).run()
        self.assertEqual(model.requests, [])

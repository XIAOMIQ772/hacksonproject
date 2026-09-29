import copy
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from support import Model
from coding_tools import TOOLS


class ProviderTests(unittest.TestCase):
    def test_real_sdk_chat_and_responses_replay_provider_state(self):
        for wire in ['chat', 'responses']:
            with self.subTest(wire=wire):
                requests = []
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *_):
                        pass

                    def do_POST(self):
                        requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                        if wire == 'chat':
                            message = {'role': 'assistant', 'content': None, 'reasoning_content': 'preserve provider reasoning',
                                       'tool_calls': [{'type': 'function', 'id': 'call-1',
                                           'function': {'name': 'read', 'arguments': '{"path":"file"}'}}]}
                            body = {'id': 'chat-1', 'object': 'chat.completion', 'created': 1, 'model': 'deepseek-test',
                                    'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls'}],
                                    'usage': {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}}
                        else:
                            body = {'id': 'resp-1', 'object': 'response', 'created_at': 1, 'status': 'completed',
                                    'model': 'test', 'parallel_tool_calls': False, 'tools': [], 'tool_choice': 'auto',
                                    'output': [{'type': 'reasoning', 'id': 'reason-1', 'summary': [], 'encrypted_content': 'opaque-state'},
                                               {'type': 'function_call', 'id': 'item-1', 'call_id': 'call-1',
                                                'name': 'read', 'arguments': '{"path":"file"}', 'status': 'completed'}],
                                    'usage': {'input_tokens': 12, 'output_tokens': 8, 'total_tokens': 20}}
                        data = json.dumps(body).encode()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                model = Model('deepseek-test', api_key='test-only-key', wire=wire,
                              base_url=f'http://127.0.0.1:{server.server_port}/v1')
                try:
                    first = model.complete('system', [{'role': 'user', 'content': 'task'}], TOOLS)
                    original = copy.deepcopy(first.items)
                    context = [{'role': 'user', 'content': 'task'}, *first.items,
                               *model.tool_result(first.calls[0], 'source')]
                    second = model.complete('system', context, TOOLS)
                    self.assertTrue(second.complete)
                    self.assertEqual(first.items, original)
                    self.assertEqual(second.usage['total_tokens'], 20)
                    payload = requests[1]['messages' if wire == 'chat' else 'input']
                    if wire == 'chat':
                        self.assertEqual(payload[-2]['reasoning_content'], 'preserve provider reasoning')
                        self.assertEqual(payload[-1]['tool_call_id'], 'call-1')
                    else:
                        self.assertEqual(payload[-3]['encrypted_content'], 'opaque-state')
                        self.assertEqual(payload[-1]['call_id'], 'call-1')
                        self.assertEqual(payload[-1]['type'], 'function_call_output')
                finally:
                    model.client.close()
                    server.shutdown()
                    server.server_close()
                    thread.join()

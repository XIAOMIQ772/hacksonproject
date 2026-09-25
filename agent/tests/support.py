import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_validation import ValidationResult
from coding_tools import CodingTools
from engine import Engine, Limits
from model import Completion, Model
from transcript import Transcript


def completion(calls=None, text='done', complete=True):
    calls = calls or []
    item = {'role': 'assistant', 'content': text}
    if calls:
        item['tool_calls'] = [{'id': c['id'], 'type': 'function',
                               'function': {'name': c['name'], 'arguments': c['arguments']}} for c in calls]
    return Completion([item], calls, text, {'total_tokens': 20}, complete)


class FakeModel:
    wire = 'chat'
    max_output_tokens = 128
    tool_result = Model.tool_result

    def __init__(self, responses=()):
        self.responses = list(responses)
        self.requests = []
        self.summary = 'Goal and constraints retained. Implemented edits; pending original requirement audit. See source files.'

    def complete(self, system, messages, tools, summary=False):
        self.requests.append(copy.deepcopy({'system': system, 'messages': messages, 'tools': tools, 'summary': summary}))
        if summary:
            return completion(text=self.summary)
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class Validator:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.count, self.audits, self.restored = 0, 0, None

    def validate(self):
        self.count += 1
        ok = self.results.pop(0) if self.results else True
        return ValidationResult(ok=ok, suite_kind='self-authored',
                                tests=[{'title': 'REQ-1 flow', 'req_ids': ['REQ-1'], 'passed': ok, 'error': ''}])

    def begin_source_audit(self):
        self.audits += 1

    def snapshot(self):
        return {'verified_round': self.count}

    def restore(self, state):
        self.restored = state


def session(tmp):
    root = Path(tmp) / 'project'
    root.mkdir(exist_ok=True)
    source = Path(tmp) / 'requirements'
    source.mkdir(exist_ok=True)
    log = Transcript(Path(tmp) / 'session/transcript.jsonl', {'system': 'Original source controls behavior', 'prompt': 'Implement the app'})
    return log, CodingTools(root, source, log)


def call(name, args='{}', id='call-1'):
    return {'id': id, 'name': name, 'arguments': args}


def engine(log, tools, model, validator=None, **limits):
    return Engine(log, model, tools, validator or Validator(), Limits(**limits))

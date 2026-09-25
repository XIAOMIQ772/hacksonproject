"""Execute delivery checks independently of the model's completion claims."""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def is_test_file(path: Path) -> bool:
    return bool(re.search(r'\.(spec|test)\.[cm]?[jt]sx?$', path.name))


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    output: str


def stop_process(process: subprocess.Popen) -> None:
    # Commands and their npm/browser children get their own process group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        pass


def run_command(command: list[str], cwd: Path, log: Path, *,
                env: dict[str, str] | None = None, timeout: float = 300) -> CommandResult:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w', encoding='utf-8') as stream:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as error:
            stream.write(str(error))
            return CommandResult(command, 127, str(error))
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_process(process)
            stream.write(f'\nCommand timed out after {timeout}s\n')
            code = 124
    return CommandResult(command, code, log.read_text(encoding='utf-8', errors='replace'))


def discover_tests(output: Path, requirements: Path | None = None) -> Path | None:
    """Find only tests authored inside the generated project.

    The requirements directory is intentionally ignored. Platform evaluation
    tests must never become generation context or local completion evidence.
    The optional parameter remains for compatibility with older callers.
    """
    del requirements
    for candidate in [output / 'backend/agent-smoke-tests']:
        if candidate.is_dir() and any(
            is_test_file(p)
            for p in candidate.rglob('*') if p.is_file()
        ):
            return candidate.resolve()
    return None


@dataclass
class ValidationResult:
    ok: bool = False
    checks: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    evidence_dir: str = ''
    suite_kind: str = 'unknown'

    def feedback(self) -> str:
        # Keep individual failures instead of truncating to the first timeout.
        failures = [t for t in self.tests if not t['passed']]
        return json.dumps({
            'ok': self.ok, 'suite_kind': self.suite_kind,
            'checks': self.checks, 'errors': self.errors,
            'failed_tests': failures, 'test_count': len(self.tests),
            'evidence_dir': self.evidence_dir,
        }, ensure_ascii=False, indent=2)


# Keep IDs verbatim: dot and hyphen separators identify different requirements.
REQUIREMENT_ID_PATTERN = r'REQ-\d+(?:[.-]\d+)*'
REQUIREMENT_ID_IN_TITLE = re.compile(r'(?<![\w-])' + REQUIREMENT_ID_PATTERN + r'(?![\w-]|\.\d)')
UI_ASSERT_ACTIONS = {'assert', 'assertText', 'assertAbsent', 'assertDisabled', 'assertEnabled', 'assertAttribute'}
UI_ACTIONS = UI_ASSERT_ACTIONS | {'click', 'fill', 'check', 'uncheck', 'press', 'select', 'dblclick', 'contextmenu', 'reload'}


def parse_playwright_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def walk(suite: dict[str, Any], parents: list[str]) -> None:
        titles = parents + [suite.get('title', '')]
        for spec in suite.get('specs', []):
            title = ' > '.join(filter(None, titles + [spec.get('title', '')]))
            req_ids = sorted(set(REQUIREMENT_ID_IN_TITLE.findall(title)))
            for test in spec.get('tests', []):
                results = test.get('results') or []
                last = results[-1] if results else {}
                # An expected failure, skip, or flaky retry is not a passing feature.
                passed = (test.get('status') == 'expected' and
                          test.get('expectedStatus', 'passed') == 'passed' and
                          bool(results) and all(r.get('status') == 'passed' for r in results))
                errors = last.get('errors') or ([last['error']] if last.get('error') else [])
                records.append({
                    'title': title, 'file': spec.get('file', suite.get('file', '')),
                    'req_ids': req_ids, 'passed': passed,
                    'status': last.get('status', test.get('status', 'not-run')),
                    'error': '\n'.join(str(e.get('message', e)) for e in errors)[:3500],
                })
        for child in suite.get('suites', []):
            walk(child, titles)

    for suite in report.get('suites', []):
        walk(suite, [])
    return records


def requirement_outcomes(tests: list[dict[str, Any]]) -> dict[str, bool]:
    values: dict[str, list[bool]] = {}
    for test in tests:
        for req_id in test['req_ids']:
            values.setdefault(req_id, []).append(test['passed'])
    return {req_id: all(results) for req_id, results in values.items()}


def load_ui_contract(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError('Missing .arc/ui-contract.json; write requirement-based exact role/name checks before verification.')
    data = json.loads(path.read_text())
    cases = data.get('cases') if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError('UI contract requires a nonempty cases array.')
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not isinstance(case.get('name'), str) or not case['name']:
            raise ValueError('Each UI case needs a name.')
        location = f'UI case {index + 1} ({case["name"]!r})'
        if not isinstance(case.get('req_ids'), list) or not case['req_ids']:
            raise ValueError(f'{location}: req_ids must be a nonempty list of original requirement IDs.')
        invalid = [value for value in case['req_ids']
                   if not isinstance(value, str) or not re.fullmatch(REQUIREMENT_ID_PATTERN, value)]
        if invalid:
            raise ValueError(f'{location}: invalid req_ids {invalid!r}. Expected IDs such as '
                             'REQ-1, REQ-1.1.1 or REQ-1-1-1; preserve the source spelling and separators.')
        if not isinstance(case.get('path'), str) or not case['path'].startswith('/') or case['path'].startswith('//'):
            raise ValueError('UI case path must be a local absolute path.')
        steps = case.get('steps')
        if not isinstance(steps, list) or not steps:
            raise ValueError('UI case needs steps.')
        if not any(isinstance(s, dict) and s.get('action') in UI_ASSERT_ACTIONS for s in steps):
            raise ValueError('UI case must assert a visible result.')
        for step in steps:
            if not isinstance(step, dict) or step.get('action') not in UI_ACTIONS:
                raise ValueError('Unsupported UI contract action.')
            if step['action'] == 'reload':
                continue
            if not isinstance(step.get('name'), str) or not step['name']:
                raise ValueError('UI step needs an exact name.')
            if step.get('by') not in {None, 'label'}:
                raise ValueError('Only by=label is supported as an alternative to roles.')
            if step['action'] != 'assertText' and step.get('by') != 'label' and (not isinstance(step.get('roles'), list) or not step['roles'] or not all(
                isinstance(role, str) and role for role in step['roles']
            )):
                raise ValueError('UI step needs allowed roles from the requirement.')
            if step['action'] in {'fill', 'select', 'assertAttribute'} and not isinstance(step.get('value'), str):
                raise ValueError(f'UI {step["action"]} step needs a string value.')
            for action, field in [('press', 'key'), ('assertAttribute', 'attribute')]:
                if step['action'] == action and (not isinstance(step.get(field), str) or not step[field]):
                    raise ValueError(f'UI {action} step needs {field}.')
            if 'scope' in step and (not isinstance(step['scope'], dict) or not all(
                isinstance(step['scope'].get(k), str) and step['scope'][k] for k in ['role', 'name']
            )):
                raise ValueError('UI scope needs role and name.')
    return data


def derive_ui_candidates(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract explicit names; retain ambiguous/dynamic clauses for human/model review.

    This is a limited grammar, not a complete natural-language specification.
    Never turn templates or negative permissions into unconditional presence checks.
    """
    role = (r"(?:button|link|heading|form|dialog|checkbox|text\s*box|region|searchbox|"
            r"combo\s*box|listbox|option|menu\s*item|gridcell|grid|tab|rowheader|columnheader|"
            r"row|menu|status|alert|password input|native select)")
    quote = r'(?P<quote>[`"“‘\'])(?P<name>[^`"“”‘’\']+)[`"”’\']'
    patterns = [re.compile(
        rf"\b(?:role\s+)?[`\"'“‘]?(?P<roles>{role}(?:\s+or\s+{role})?)[`\"'”’]?"
        rf"\s+(?:(?P<label>label(?:l)?ed)|named(?:\s+exactly)?|"
        rf"with\s+(?:the\s+)?(?:exact\s+)?(?:accessible\s+)?name(?:\s+of)?|"
        rf"role,\s+has\s+(?:the\s+)?accessible\s+name)?\s*{quote}", re.I),
        re.compile(rf"{quote}\s+(?P<roles>{role})(?![\w-])", re.I)]
    plural_role = r'(?:buttons|links|checkboxes|textboxes|tabs|menu items)'
    quoted = r'''[`"“‘']([^`"“”‘’']+)[`"”’']'''
    plural = re.compile(rf'(?P<roles>{plural_role})\s+(?:named|with\s+(?:the\s+)?(?:accessible\s+)?names)\s+'
                        rf'(?P<names>{quoted}(?:\s*(?:,\s*(?:and\s+)?|and\s+){quoted})*)', re.I)
    candidates = []
    seen = set()
    for req in requirements:
        details = req.get('details', req)
        passages = [details.get('description', req.get('description', ''))]
        for scenario in details.get('scenarios') or []:
            if isinstance(scenario, dict):
                passages.extend(step.get('content', '') for step in scenario.get('steps') or []
                                if isinstance(step, dict))
        for passage_index, passage in enumerate(passages):
            if not isinstance(passage, str):
                continue
            for pattern_index, pattern in enumerate(patterns):
                for match in pattern.finditer(passage):
                    roles = sorted(set(re.sub(r'\s+', '', r.lower())
                                       for r in re.split(r'\s+or\s+', match.group('roles'), flags=re.I)))
                    # 'the test status' is a domain value, not an ARIA status.
                    if pattern_index == 1 and any(r in {'status', 'alert', 'row'} for r in roles):
                        continue
                    label = bool(match.groupdict().get('label'))
                    if 'passwordinput' in roles or 'nativeselect' in roles:
                        if not label:
                            continue
                        roles = [r for r in roles if r not in {'passwordinput', 'nativeselect'}]
                    name = match.group('name')
                    # An atom may state absent/disabled controls for a different
                    # session. Save these passages without inventing its scope.
                    before = re.split(r'[.;!?\n]', passage[:match.start()])[-1]
                    after = re.split(r'[.;!?\n]', passage[match.end():])[0]
                    reason = ''
                    if re.search(r'<[^>]+>|\{[^}]+\}', name):
                        reason = 'dynamic name: instantiate from the source object; do not use template literally'
                    elif re.search(r"\b(?:no|not|without|hidden|absent|optional|may|mustn't|shouldn't)\b", before, re.I):
                        reason = 'conditional/negative clause: review session, scope and expected state'
                    elif re.match(r"\s+(?:(?:must|should)\s+)?(?:not|never|may)\b|\s+(?:is|are)\s+(?:absent|hidden)", after, re.I):
                        reason = 'conditional/negative clause: review session, scope and expected state'
                    if 'option' in roles:
                        reason = 'option: review native selection versus custom listbox interaction'
                    if pattern_index == 1 and roles == ['menu']:
                        reason = 'menu reference may name its trigger rather than the menu; review accessible name'
                    if passage_index and any(c['req_id'] == req['id'] and c['name'] == name
                                             and c.get('source_kind') == 'description'
                                             and c['roles'] != roles for c in candidates):
                        reason = 'scenario role conflicts with explicit description; review source precedence'
                    key = (req['id'], name, tuple(roles), label, reason)
                    if key in seen:
                        continue
                    seen.add(key)
                    item = {'req_id': req['id'], 'name': name, 'roles': roles, 'source': passage,
                            'source_kind': 'description' if passage_index == 0 else 'scenario'}
                    if label:
                        item['by'] = 'label'
                    if reason:
                        item['review_reason'] = reason
                    candidates.append(item)
            for match in plural.finditer(passage):
                raw_role = match.group('roles').lower()
                roles = [{'checkboxes': 'checkbox', 'menu items': 'menuitem'}.get(raw_role, raw_role[:-1])]
                before = re.split(r'[.;!?\n]', passage[:match.start()])[-1]
                after = re.split(r'[.;!?\n]', passage[match.end():])[0]
                for name in re.findall(quoted, match.group('names')):
                    reason = ''
                    if re.search(r'<[^>]+>|\{[^}]+\}', name):
                        reason = 'dynamic name: instantiate from the source object'
                    elif re.search(r'\b(?:no|not|without|hidden|absent|optional|may)\b', before, re.I):
                        reason = 'conditional/negative clause: review session, scope and expected state'
                    elif re.match(r'\s+(?:(?:must|should)\s+)?(?:not|never|may)\b|\s+(?:is|are)\s+(?:absent|hidden|not)', after, re.I):
                        reason = 'conditional/negative clause: review session, scope and expected state'
                    if passage_index and any(c['req_id'] == req['id'] and c['name'] == name
                                             and c.get('source_kind') == 'description'
                                             and c['roles'] != roles for c in candidates):
                        reason = 'scenario role conflicts with explicit description; review source precedence'
                    key = (req['id'], name, tuple(roles), False, reason)
                    if key in seen:
                        continue
                    seen.add(key)
                    item = {'req_id': req['id'], 'name': name, 'roles': roles, 'source': passage,
                            'source_kind': 'description' if passage_index == 0 else 'scenario'}
                    if reason:
                        item['review_reason'] = reason
                    candidates.append(item)
    return candidates


def derive_ui_obligations(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in derive_ui_candidates(requirements) if not item.get('review_reason')]


def check_ui_contract_obligations(contract: dict[str, Any], requirements: list[dict[str, Any]]) -> list[str]:
    errors = []
    for obligation in derive_ui_obligations(requirements):
        candidates = []
        for case in contract.get('cases', []):
            if obligation['req_id'] not in case.get('req_ids', []):
                continue
            for step in case.get('steps', []):
                # Absence cannot satisfy a positive presence obligation.
                if step.get('action') not in {'assertText', 'assertAbsent', 'reload'}:
                    candidates.append(step)
                if step.get('scope'):
                    candidates.append({'name': step['scope']['name'], 'roles': [step['scope']['role']]})
        allowed = set(obligation['roles'])
        def matches(candidate: dict[str, Any]) -> bool:
            if candidate.get('name') != obligation['name']:
                return False
            if obligation.get('by') == 'label' and candidate.get('by') == 'label':
                return True
            return (candidate.get('by') != 'label' and bool(candidate.get('roles'))
                    and set(candidate['roles']) <= allowed)
        if not any(matches(candidate) for candidate in candidates):
            target = 'label' if obligation.get('by') == 'label' else ' or '.join(obligation['roles'])
            errors.append(f"{obligation['req_id']}: UI contract must check exact "
                          f"{target} named {obligation['name']!r}. Source: {obligation['source']}")
    return errors


class ProjectValidator:
    def __init__(self, output: Path, test_dir: Path | None,
                 required_ids: list[str] | None = None,
                 requirements: list[dict[str, Any]] | None = None):
        self.output = output.resolve()
        self.required_ids = required_ids or []
        self.round = 0
        self.run_id = uuid.uuid4().hex[:12]
        self.test_dir = test_dir.resolve() if test_dir else None
        self.requirements = requirements or []
        # The model can write evidence files. Keep the authoritative baseline in
        # this validator's memory, never reload it from the generated project.
        self._baseline: dict[str, bytes] = {}

    def begin_source_audit(self) -> None:
        """Start a new evidence set after the harness requests an independent source check.

        Self-authored checks may contain wrong expectations. The audit can correct
        those before its first successful verification, which freezes them again.
        """
        self.run_id = uuid.uuid4().hex[:12]
        self.round = 0
        self._baseline.clear()

    def _check_baseline(self, *, freeze: bool = True) -> list[str]:
        """Check frozen files and optionally capture assertion/fixture helpers.

        New files are allowed; existing files must be restored byte for byte.
        Newly captured files are tentative until the whole verification passes.
        This guards one validator session, not an OS security boundary.
        """
        errors: list[str] = []
        candidates: dict[str, bytes] = {}
        test_dir = self.test_dir or self.output / 'backend/agent-smoke-tests'
        if not test_dir.is_relative_to(self.output):
            return ['Self-authored tests must be inside the generated project.']
        if test_dir.is_symlink():
            errors.append(f'Test baseline does not allow a symlink: {test_dir}')
        elif test_dir.is_dir():
            for path in sorted(test_dir.rglob('*')):
                # Runtime outputs are not source; keep helpers/data/configs frozen.
                if any(part in {'node_modules', '__pycache__', 'test-results', 'playwright-report'}
                       for part in path.relative_to(test_dir).parts):
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(self.output):
                    errors.append(f'Test baseline does not allow a symlink: {path}')
                elif path.is_file():
                    candidates[path.relative_to(self.output).as_posix()] = path.read_bytes()

        contract_key = '.arc/ui-contract.json'
        contract_path = self.output / contract_key
        if contract_path.is_symlink() or not contract_path.resolve().is_relative_to(self.output):
            errors.append('UI contract must be a regular file inside the generated project.')
        elif contract_path.is_file():
            if contract_key in self._baseline:
                candidates[contract_key] = contract_path.read_bytes()
            else:
                try:
                    contract = load_ui_contract(contract_path)
                    contract_errors = check_ui_contract_obligations(contract, self.requirements)
                    errors.extend(contract_errors)
                    if not contract_errors:
                        candidates[contract_key] = contract_path.read_bytes()
                except (ValueError, OSError) as error:
                    errors.append(f'UI contract not frozen: {error}')

        baseline_dir = self.output / '.arc/validation' / self.run_id
        snapshots = baseline_dir / 'baseline-files'
        for name, original in self._baseline.items():
            if name not in candidates:
                errors.append(f'Frozen validation file deleted or unavailable: {name}. '
                              f'Restore the original from {snapshots / name}.')
            elif candidates[name] != original:
                errors.append(f'Frozen validation file modified: {name}. '
                              f'Restore the original from {snapshots / name}; fix application code instead. '
                              'New test files may be added; a change log does not authorize rewriting frozen checks.')
        if freeze:
            for name, content in candidates.items():
                if name not in self._baseline:
                    self._baseline[name] = content
        # Recreate the audit copies from memory so editing/deleting the manifest
        # or recovery files cannot rebaseline a running generation session.
        baseline_dir.mkdir(parents=True, exist_ok=True)
        manifest = {'version': 1, 'run_id': self.run_id, 'scope': 'validator-session', 'files': {}}
        for name, content in sorted(self._baseline.items()):
            snapshot = snapshots / name
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(content)
            manifest['files'][name] = {'sha256': hashlib.sha256(content).hexdigest(),
                                       'bytes': len(content), 'snapshot': str(snapshot)}
        (baseline_dir / 'test-baseline.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        return errors

    def validate(self) -> ValidationResult:
        self.round += 1
        evidence = self.output / '.arc/validation' / self.run_id / f'round-{self.round:03d}'
        evidence.mkdir(parents=True, exist_ok=True)
        result = ValidationResult(evidence_dir=str(evidence), suite_kind='self-authored')
        verified_baseline = dict(self._baseline)
        try:
            result.errors.extend(self._check_baseline())
            if not result.errors:
                self._validate(result, evidence)
                # Build hooks or tests must not rewrite checks during execution.
                result.errors.extend(self._check_baseline())
        except Exception as error:
            result.errors.append(f'Validation error: {type(error).__name__}: {error}')
        result.ok = (not result.errors and bool(result.tests)
                     and all(check['returncode'] == 0 for check in result.checks)
                     and all(test['passed'] for test in result.tests))
        if not result.ok:
            # Capture during execution to detect tampering, but do not permanently
            # freeze checks whose assumptions have never passed a real run.
            self._baseline = verified_baseline
            self._check_baseline(freeze=False)
        (evidence / 'summary.json').write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        print(f'[validation] suite={result.suite_kind} ok={result.ok} '
              f'passed={sum(t["passed"] for t in result.tests)} total={len(result.tests)} '
              f'evidence={evidence}', flush=True)
        for error in result.errors:
            print('[validation] error: ' + error, flush=True)
        for test in result.tests:
            if not test['passed']:
                print(f'[validation] FAIL {test["title"]}: {test["error"]}', flush=True)
        return result

    def _validate(self, result: ValidationResult, evidence: Path) -> None:
        backend = self.output / 'backend'
        frontend = self.output / 'frontend'
        env = dict(os.environ)
        # Keep local validation mutations away from the delivered runtime database.
        env['ARC_DB_FILE'] = str(evidence / 'seed-check.sqlite')
        env['DATABASE_FILE'] = env['ARC_DB_FILE']

        def check(name: str, command: list[str], cwd: Path, timeout: float = 300) -> bool:
            outcome = run_command(command, cwd, evidence / f'{name}.log', env=env, timeout=timeout)
            result.checks.append({'name': name, 'returncode': outcome.returncode,
                                  'log': str(evidence / f'{name}.log')})
            if outcome.returncode:
                result.errors.append(f'{name} failed:\n{outcome.output[-9000:]}')
            return outcome.returncode == 0

        for name, folder in [('frontend', frontend), ('backend', backend)]:
            if not (folder / 'package.json').is_file():
                result.errors.append(f'Missing {folder}/package.json')
                return
            if not (folder / 'node_modules').is_dir():
                if not check(f'install-{name}', ['npm', 'install', '--no-audit', '--no-fund'], folder):
                    return
        if not check('build', ['npm', 'run', 'build'], frontend):
            return
        if not (frontend / 'dist/index.html').is_file():
            result.errors.append('Build did not create frontend/dist/index.html')
            return
        if not check('seed', ['npm', 'run', 'db:prepare:e2e'], backend):
            return

        test_dir = self.test_dir or backend / 'agent-smoke-tests'
        if not test_dir.is_dir() or not any(is_test_file(p) for p in test_dir.rglob('*') if p.is_file()):
            result.errors.append('No E2E specs. Create backend/agent-smoke-tests/*.spec.js '
                                 'with REQ IDs in test titles and assertions for every atomic requirement.')
            return
        cli = backend / 'node_modules/@playwright/test/cli.js'
        if not cli.is_file():
            result.errors.append('Missing @playwright/test; install backend devDependencies.')
            return
        contract = load_ui_contract(self.output / '.arc/ui-contract.json')
        (evidence / 'requirement-ui-obligations.json').write_text(json.dumps(
            derive_ui_obligations(self.requirements), ensure_ascii=False, indent=2))
        contract_errors = check_ui_contract_obligations(contract, self.requirements)
        if contract_errors:
            result.errors.extend(contract_errors)
            return
        contract_path = evidence / 'ui-contract.json'
        contract_path.write_text(json.dumps(contract, ensure_ascii=False))
        contract_dir = evidence / 'contract-tests'
        contract_dir.mkdir()
        (contract_dir / 'ui-contract.spec.cjs').write_text(
            Path(__file__).with_name('ui_contract.cjs').read_text())
        env['ARC_UI_CONTRACT'] = str(contract_path)
        env['ARC_PLAYWRIGHT_MODULE'] = str(backend / 'node_modules/@playwright/test')
        for suite, directory in [('ui-contract', contract_dir), ('self-authored', test_dir)]:
            suite_evidence = evidence / suite
            suite_evidence.mkdir()
            self._run_browser_suite(suite, directory, suite_evidence, env, result)
        # A UI contract can mention every ID while checking only a heading.
        # Behavioral coverage must come from executed self-authored tests alone.
        covered = requirement_outcomes([t for t in result.tests if t.get('suite_kind') == 'self-authored'])
        missing = sorted(set(self.required_ids) - covered.keys())
        if missing:
            result.errors.append('Atomic requirements missing self-authored E2E coverage: ' + ', '.join(missing))

    def _run_browser_suite(self, suite: str, test_dir: Path, evidence: Path,
                           base_env: dict[str, str], result: ValidationResult) -> None:
        backend = self.output / 'backend'
        env = dict(base_env)
        # Each suite starts its own server and absent database. Contract actions
        # must not mutate the starting state of behavioral tests (or vice versa).
        env['ARC_DB_FILE'] = str(evidence / 'runtime.sqlite')
        env['DATABASE_FILE'] = env['ARC_DB_FILE']
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base_url = f'http://127.0.0.1:{port}'
        env.update({'PORT': str(port), 'PLAYWRIGHT_BASE_URL': base_url, 'ARC_WEB_BASE_URL': base_url})
        report_path = evidence / 'playwright.json'
        config = backend / 'playwright.agent-validation.cjs'
        config.write_text("module.exports = " + json.dumps({
            'testMatch': '**/*.{spec,test}.{js,jsx,ts,tsx,mjs,cjs,mts,cts}',
            'projects': [{'name': suite, 'testDir': str(test_dir)}],
            'timeout': 30000, 'expect': {'timeout': 3000}, 'workers': 1, 'retries': 0,
            'forbidOnly': True, 'use': {'baseURL': base_url, 'headless': True, 'channel': 'chromium',
                                      'trace': 'retain-on-failure', 'screenshot': 'only-on-failure'},
            'reporter': [['json', {'outputFile': str(report_path)}]],
            'outputDir': str(evidence / 'test-results'),
        }) + ';\n')
        with (evidence / 'server.log').open('w') as server_log:
            server = subprocess.Popen(['npm', 'run', 'start'], cwd=backend, env=env,
                                      stdout=server_log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                deadline = time.monotonic() + 30
                ready = False
                while time.monotonic() < deadline and server.poll() is None:
                    try:
                        with opener.open(base_url + '/api/health', timeout=1) as response:
                            ready = response.status == 200
                        if ready:
                            with opener.open(base_url + '/', timeout=1) as response:
                                ready = response.status == 200
                        if ready:
                            break
                    except (OSError, urllib.error.URLError):
                        pass
                    time.sleep(0.2)
                if not ready:
                    result.errors.append(f'{suite}: Backend not ready; inspect {evidence / "server.log"}')
                    return
                cli = backend / 'node_modules/@playwright/test/cli.js'
                command = ['node', str(cli), 'test', '--config', str(config)]
                outcome = run_command(command, backend, evidence / 'playwright.log', env=env,
                                      timeout=max(900, len(self.required_ids) * 15 + 60))
                result.checks.append({'name': f'playwright-{suite}', 'returncode': outcome.returncode,
                                      'log': str(evidence / 'playwright.log')})
                if outcome.returncode:
                    result.errors.append(f'playwright-{suite} failed:\n{outcome.output[-9000:]}')
                if not report_path.is_file():
                    result.errors.append(f'{suite}: Playwright did not produce a JSON report.')
                    return
                report = json.loads(report_path.read_text())
                tests = parse_playwright_report(report)
                for test in tests:
                    test['suite_kind'] = suite
                result.tests.extend(tests)
                result.errors.extend(str(e.get('message', e))[:4000] for e in report.get('errors', []))
                if not tests:
                    result.errors.append(f'{suite}: Playwright executed zero tests.')
            finally:
                stop_process(server)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Validate a generated project without calling a model.')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--requirements-dir', type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    required_ids = []
    requirements = []
    if args.requirements_dir:
        from main import load_requirements
        requirements = load_requirements(args.requirements_dir)
        required_ids = [req['id'] for req in requirements
                        if str(req.get('type', '')).upper() == 'ATOMIC'
                        or (not req.get('children_ids') and req.get('scenarios'))]
    validator = ProjectValidator(output, discover_tests(output), required_ids, requirements)
    result = validator.validate()
    print(result.feedback())
    raise SystemExit(0 if result.ok else 1)

"""Single ARC-Bench entry point for the transcript-based coding agent."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import sys
import uuid
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE / 'arcbench-agent-runtime/src'))

from arcbench_agent_runtime import AgentRuntime
from agent_validation import ProjectValidator, discover_tests, derive_ui_obligations, derive_ui_candidates
from coding_tools import CodingTools, atomic_write
from engine import Engine, Limits, error_info
from model import Model
from prompts import SYSTEM, TASK
from requirement_context import build_requirement_context
from requirements_io import load_requirements, build_fixture_inventory, extract_fixture_manifest
from transcript import Transcript


def copy_template(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for source in (PACKAGE / 'template').iterdir():
        destination = output / source.name
        if destination.exists():
            continue
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


def prepare_requirements(requirements: list[dict], output: Path) -> None:
    build_requirement_context(requirements, output)
    arc = output / '.arc'
    (arc / 'fixture-inventory.md').write_text(build_fixture_inventory(requirements))
    for name, data in [('fixture-manifest.json', extract_fixture_manifest(requirements)),
                       ('requirement-ui-obligations.json', derive_ui_obligations(requirements)),
                       ('ui-review.json', [r for r in derive_ui_candidates(requirements) if r.get('review_reason')])]:
        (arc / name).write_text(json.dumps(data, ensure_ascii=False, indent=2))
    shutil.copy2(PACKAGE / 'validation-guide.md', arc / 'validation-guide.md')


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('requirement_path', nargs='?', default=os.environ.get('ARCBENCH_TASK_DIR', 'requirements'))
    p.add_argument('--output-dir', default=os.environ.get('ARCBENCH_OUTPUT_DIR', '.'))
    p.add_argument('--type', default=os.environ.get('ARCBENCH_TASK_TYPE', 'web'), choices=['web'])
    p.add_argument('--session', type=Path, help='Resume this JSONL transcript; workspace and requirement identity must match')
    p.add_argument('--new-session', action='store_true', help='Start new history while preserving the current application')
    p.add_argument('--inspect', type=Path, help='Print transcript status and exit without model requests')
    p.add_argument('--max-steps', type=int, default=int(os.environ.get('AGENT_MAX_STEPS', '600')))
    p.add_argument('--context-tokens', type=int, default=int(os.environ.get('AGENT_CONTEXT_TOKENS', '65536')))
    p.add_argument('--keep-recent-tokens', type=int, default=int(os.environ.get('AGENT_KEEP_RECENT_TOKENS', '16384')))
    p.add_argument('--token-budget', type=int, default=int(os.environ.get('AGENT_TOKEN_BUDGET', '0')))
    p.add_argument('--max-output-tokens', type=int, default=int(os.environ.get('AGENT_MAX_OUTPUT_TOKENS', '8192')))
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.inspect:
        # Inspect does not repair files, acquire a writer, or need credentials.
        events = [json.loads(line) for line in args.inspect.read_text().splitlines() if line.strip()]
        print(json.dumps({'events': len(events), 'session': events[0]['id'],
                          'last_event': events[-1]['type'],
                          'phase': next((e['name'] for e in reversed(events) if e['type'] == 'phase'), 'implementation'),
                          'deliveries': sum(e['type'] == 'delivery' for e in events)}, indent=2))
        return 0
    if args.session and args.new_session:
        raise ValueError('--session and --new-session are mutually exclusive')
    requirements_dir, output = Path(args.requirement_path).resolve(), Path(args.output_dir).resolve()
    requirements = load_requirements(requirements_dir)
    if not requirements:
        raise ValueError('No requirements were found in the public task input')
    identity = hashlib.sha256(json.dumps(requirements, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    model_name, wire = os.environ.get('MODEL', 'deepseek-v4-pro'), os.environ.get('OPENAI_WIRE_API', 'chat')
    system = SYSTEM.format(output=output, source=requirements_dir)
    store = output / '.arc/session'
    pointer = store / 'active.json'
    if args.session:
        session = args.session.resolve()
        if not session.is_file():
            raise ValueError('Requested transcript does not exist')
    elif pointer.exists() and not args.new_session:
        filename = json.loads(pointer.read_text())['file']
        if Path(filename).name != filename:
            raise ValueError('Invalid active session pointer')
        session = store / filename
        if not session.is_file():
            raise ValueError('Active transcript is missing; recover it or explicitly start --new-session')
    else:
        session = store / f'{uuid.uuid4().hex}.jsonl'
    metadata = {'workspace': str(output), 'requirements_sha256': identity, 'model': model_name,
                'wire': wire, 'system': system, 'prompt': TASK}
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        raise ValueError('OPENAI_API_KEY is required')
    model = Model(model_name, api_key=api_key, base_url=os.environ.get('OPENAI_BASE_URL') or None,
                  wire=wire, max_output_tokens=args.max_output_tokens,
                  reasoning=os.environ.get('OPENAI_REASONING_EFFORT', 'low'))
    os.environ['ARCBENCH_OUTPUT_DIR'] = str(output)
    runtime = AgentRuntime.from_env()
    with Transcript(session, metadata) as transcript:
        for key in ('workspace', 'requirements_sha256', 'model', 'wire', 'system'):
            if transcript.header[key] != metadata[key]:
                raise ValueError(f'Session {key} differs from this invocation; use --new-session for a new context')
        if session.parent == store:
            atomic_write(pointer, json.dumps({'file': session.name}).encode())
        copy_template(output)
        prepare_requirements(requirements, output)
        runtime.events.mark_run_started('implementation session started')
        runtime.traceability.init_db()
        runtime.git.ensure_repo(create_initial_commit=True)
        for req in requirements:
            runtime.traceability.upsert_requirement(req_id=req['id'], name=req['name'], description=req['description'],
                    scenarios=req.get('scenarios'), parent_id=req.get('parent_id'),
                    children_ids=req.get('children_ids'), dependencies=req.get('dependencies'))
            runtime.events.mark_implementation_started(req['id'])
        atomic = [r['id'] for r in requirements if str(r.get('type', '')).upper() == 'ATOMIC'
                  or not r.get('children_ids') and r.get('scenarios')]
        validator = ProjectValidator(output, discover_tests(output), atomic, requirements)
        tools = CodingTools(output, requirements_dir, transcript)
        limits = Limits(args.max_steps, args.context_tokens, args.keep_recent_tokens, args.token_budget)
        try:
            result = Engine(transcript, model, tools, validator, limits).run()
            for req in requirements:
                runtime.events.mark_implementation_done(req['id'], 'implementation and source audit verified; see evidence')
            runtime.git.commit('Implement requirements and record validation evidence')
            runtime.events.mark_run_completed('implementation verified; official scoring is performed by the platform')
            print(json.dumps({'status': 'verified', 'transcript': str(session),
                              'evidence_dir': result.evidence_dir, 'model_tokens': transcript.token_usage()}))
            return 0
        except BaseException as error:
            info = error_info(error)
            transcript.append('run_interrupted' if isinstance(error, KeyboardInterrupt) else 'run_failed', error=info)
            runtime.events.mark_run_failed(info['message'])
            print(json.dumps({'status': 'interrupted' if isinstance(error, KeyboardInterrupt) else 'failed',
                              'transcript': str(session), 'error': info}), file=sys.stderr)
            return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == '__main__':
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt('Process signal received; recover from the saved transcript')
    signal.signal(signal.SIGTERM, interrupt)
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(json.dumps(error_info(error)), file=sys.stderr)
        raise SystemExit(1)

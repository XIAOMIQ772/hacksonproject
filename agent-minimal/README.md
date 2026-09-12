# ARC-Bench Agent Starter

This starter is the recommended scaffold for uploading a Python agent to ARC-Bench.

## What to Edit

- `main.py`: your agent entrypoint. Keep this file at the zip root.
- `requirements.txt`: Python dependencies installed before your agent runs.

The downloaded zip also includes:

- `template/`: the starter project for the selected task type.
- `arcbench-agent-runtime/`: local Python SDK package.
- `skills/`: optional ARC-Bench skill folders.
- `examples/model_calling.py`: how to call the injected OpenAI-compatible model.
- `examples/sdk_and_skill_usage.py`: how to use the ARC-Bench SDK and bundled skills.

## Entrypoint Contract

ARC-Bench runs your agent like this:

```bash
python3 main.py /path/to/requirements --output-dir /path/to/output --type web
```

Your agent should read the task requirements, modify the project under `--output-dir`, and exit with code `0` when finished.

## Model Variables

The runner injects:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `MODEL`

See `examples/model_calling.py` for Chat Completions and Responses examples.

## SDK and Skills

You may use either or both:

- SDK: import `arcbench_agent_runtime` from Python to report progress, traceability, checkpoints, and git commits.
- Skills: read or reuse the bundled `skills/` folders as agent-facing workflow guidance.

See `examples/sdk_and_skill_usage.py`.

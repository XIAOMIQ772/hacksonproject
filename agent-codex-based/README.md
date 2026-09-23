# ARC-Bench Agent Starter

This reference agent initializes a starter application, then asks Codex to implement one direct
child subtree of `ROOT` at a time.

## Quick Start

Requires Python 3.10 or later.

```bash
python3 --version  # must be 3.10+
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

export OPENAI_API_KEY="your-api-key"
python main.py /path/to/requirements --output-dir /path/to/output --type web
```

`requirements.yaml` must contain a `ROOT` mapping with at least one direct child. The agent keeps
one Codex thread open and implements those child subtrees in order, so later modules retain the
context from earlier work.

When using this repository's shared ARC-Bench gateway configuration, create the ignored root
`.env` from `.env.example` and run the entrypoint through `./run-with-gateway`.

## What to Edit

- `main.py`: the Codex agent entrypoint.
- `template/`: the starter application. Its contents are copied directly into the output directory.

## Entrypoint Contract

ARC-Bench runs your agent like this:

```bash
python3 main.py /path/to/requirements --output-dir /path/to/output --type web
```

The input directory must contain `requirements.yaml` with `id: ROOT`. ARC-Bench prepares the
authoritative task application in `--output-dir` before invoking the agent (including the selected
evolution baseline). When running standalone, the agent can also copy a local `template/` directory
if one is present. It then sends each direct ROOT-child subtree to Codex in sequence. Codex modifies
the same output directory for every module.

The bundled `skills/` directory is copied to `.codex/skills/` in the output project. Codex is told
where to find the skills and can use their scripts for runtime progress, traceability, and git
checkpoints when those actions are useful.

## Model Variables

The runner injects:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `MODEL`

See `examples/model_calling.py` for Chat Completions and Responses examples.

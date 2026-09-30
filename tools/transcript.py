#!/usr/bin/env python3
"""Inspect agent run transcripts in OUTPUT_DIR/.agent.

    python3 tools/transcript.py OUTPUT_DIR                 phases, checkpoints and tool calls per step
    python3 tools/transcript.py OUTPUT_DIR PHASE STEP      full messages of one step

Resume with:  python3 agent/main.py REQ_DIR --output-dir OUTPUT_DIR --from PHASE:STEP
Transcripts are JSONL; edit a record (e.g. a tool result or the task text) before resuming to test a change.
"""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]) / ".agent"
run = json.loads((root / "run.json").read_text()) if (root / "run.json").exists() else {}
if len(sys.argv) == 2:
    print("finished:", ", ".join(run.get("done", {})) or "-", "| last good commit:", str(run.get("good", "-"))[:8])
    for path in sorted(root.glob("*.jsonl")):
        if ".after-" in path.name or ".replaced-" in path.name:
            continue
        print(f"\n== {path.stem}")
        calls = []
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if record["type"] == "message" and record["message"]["role"] == "assistant":
                calls = [c["function"]["name"] for c in record["message"].get("tool_calls") or []]
            elif record["type"] == "compaction":
                print("   [compaction]")
            elif record["type"] == "checkpoint":
                print(f"  step {record['step']:>3}  {record['commit'][:8]}  {' '.join(calls)}")
    sys.exit()

phase, step = sys.argv[2], int(sys.argv[3])
current, printing = 0, step == 0
for line in (root / f"{phase}.jsonl").read_text().splitlines():
    record = json.loads(line)
    if record["type"] == "checkpoint":
        current = record["step"]
        printing = current + 1 == step
        continue
    if printing and record["type"] == "message":
        m = record["message"]
        body = m.get("content") or ""
        if m.get("tool_calls"):
            body += "\n" + "\n".join(f"-> {c['function']['name']} {c['function']['arguments']}" for c in m["tool_calls"])
        print(f"--- {m['role']}\n{body if isinstance(body, str) else json.dumps(body)[:2000]}\n")

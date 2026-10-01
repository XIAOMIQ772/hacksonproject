"""Dashboard for a local agent run.

    python3 tools/watch/server.py OUTPUT_DIR --log RUN_LOG --req REQUIREMENTS_DIR [--port 8765]

Reads only what the run writes (its stdout log, .agent/engineer.jsonl and usage.jsonl, PLAN.md, the e2e
specs and the git history) and serves it as JSON to index.html next to this file.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "agent"))
import spec  # noqa: E402

PRICE = 0.30  # yuan per million tokens, from the official sheet run (43.22 yuan for 144.9M tokens)
STEP_LINE = re.compile(r"^\[([^\]]+)\] (\d+) (\w+) (.*?) -> (.*)$")
SCORE = re.compile(r"e2e (\d+)/(\d+)")


def unquote(text: str) -> str:
    text = text.strip()
    if text[:1] in "'\"":
        text = text[1:-1] if len(text) > 1 and text[-1] == text[0] else text[1:]
    return text.replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"')


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(errors="replace").splitlines() if path.exists() else []:
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass  # the line being written
    return rows


def collect(root: Path, log: Path, tree) -> dict:
    lines = log.read_text(errors="replace").splitlines() if log.exists() else []
    usage = read_jsonl(root / ".agent" / "usage.jsonl")
    records = read_jsonl(root / ".agent" / "engineer.jsonl")

    roles: dict[str, dict] = {}
    for row in usage:
        label = row.get("label", "")
        role = "subagent" if ":helper" in label else "vision" if label == "visual" else "engineer"
        bucket = roles.setdefault(role, {"calls": 0, "prompt": 0, "cached": 0, "completion": 0})
        bucket["calls"] += 1
        for key in ("prompt", "cached", "completion"):
            bucket[key] += row.get(key, 0)
    tokens = sum(r["prompt"] + r["completion"] for r in roles.values())

    checks, calls, step = [], {}, 0
    for record in records:
        if record.get("type") == "checkpoint":
            step = record["step"]
        message = record.get("message") or {}
        for call in message.get("tool_calls") or []:
            calls[call["id"]] = call["function"]
        fn = calls.get(message.get("tool_call_id"), {})
        if message.get("role") == "tool" and fn.get("name") == "check":
            report = message.get("content", "")
            score = SCORE.search(report)
            failed = []
            if "FAILED TESTS:\n" in report:
                block = report.split("FAILED TESTS:\n", 1)[1].split("\nE2E FAILURES:", 1)[0]
                failed = [line[2:] for line in block.splitlines() if line.startswith("- ")]
            checks.append({"step": step + 1, "pattern": json.loads(fn.get("arguments") or "{}").get("pattern") or "",
                           "ok": report.startswith("CHECK PASSED"), "passed": int(score[1]) if score else 0,
                           "total": int(score[2]) if score else 0, "failed": failed})
    whole = [c for c in checks if not c["pattern"] and c["total"]]

    titles = []
    tests = root / "backend" / "test-e2e"
    for path in sorted(tests.glob("*.spec.*")) if tests.is_dir() else []:
        titles += [f"{path.name} :: {m[2]}" for m in re.finditer(r"\btest\(\s*(['\"`])(.+?)\1", path.read_text(errors="replace"))]
    plan = (root / "PLAN.md").read_text(errors="replace") if (root / "PLAN.md").exists() else ""
    status: dict[str, str] = {}  # each test's result in the latest check that ran its file
    for check in checks:
        failed = set(check["failed"])
        for title in titles:
            if not check["pattern"] or re.search(check["pattern"], title.split(" :: ")[0]):
                status[title] = "fail" if title in failed else "pass"
    reqs = []
    for atomic in tree.atomics:
        pattern = re.compile(re.escape(atomic.id) + r"(?!-?\d)")
        mine = [t for t in titles if pattern.search(t)]
        reqs.append({"id": atomic.id, "name": atomic.name,
                     "state": "fail" if any(status.get(t) == "fail" for t in mine)
                     else "pass" if mine and all(status.get(t) == "pass" for t in mine)
                     else "planned" if mine or pattern.search(plan) else "todo"})

    helpers: dict[int, dict] = {}
    for line in lines:
        m = re.match(r"^\[[^\]]*:helper(\d+)\] (.*)$", line)
        if not m:
            continue
        h = helpers.setdefault(int(m[1]), {"n": int(m[1]), "task": "", "state": "running", "steps": 0, "answer": ""})
        if m[2].startswith("started"):
            h["task"] = m[2].split(": ", 1)[-1]
        elif m[2].startswith("done in"):
            h["state"] = "done"
        elif re.match(r"\d+ ", m[2]):
            h["steps"] = max(h["steps"], int(m[2].split(" ", 1)[0]))
    for record in records:
        m = re.match(r"Subagent (\d+) finished.*?Final answer:\n(.*)", (record.get("message") or {}).get("content") or "", re.S)
        if m and int(m[1]) in helpers:
            helpers[int(m[1])]["answer"] = m[2][:3000]

    feed = []
    for line in lines[-500:]:
        m = STEP_LINE.match(line)
        if m:
            feed.append({"who": m[1], "step": int(m[2]), "tool": m[3], "args": unquote(m[4]), "result": unquote(m[5])})
        elif line.startswith(("[compact]", "[llm]", "[agent]")) or re.match(r"^\[[^\]]+\] (done in|started)", line):
            feed.append({"who": line[1:line.index("]")], "event": line[line.index("]") + 2:][:500]})

    git = subprocess.run(["git", "log", "--format=%ct %s", "--grep=^engineer step"], cwd=root,
                         capture_output=True, text=True).stdout
    steps = sorted([int(s.split()[2]), int(t)] for t, _, s in (l.partition(" ") for l in git.splitlines())
                   if re.match(r"engineer step \d+", s))
    finished = next((l for l in lines if l.startswith("[agent] finished in")), "")
    return {
        "name": root.name, "now": time.time(), "finished": finished,
        "error": next((l for l in lines if "model unavailable" in l), ""),
        "started": usage[0]["time"] if usage else None,
        "updated": log.stat().st_mtime if log.exists() else None,
        "step": steps[-1][0] if steps else 0, "steps": steps[-800:],
        "usage": {"roles": roles, "tokens": tokens, "cost": round(tokens / 1e6 * PRICE, 2)},
        "checks": checks[-200:], "whole": whole[-1] if whole else None,
        "requirements": reqs, "tests": len(titles), "plan": plan,
        "subagents": sorted(helpers.values(), key=lambda h: h["n"]),
        "compactions": sum(1 for l in lines if l.startswith("[compact]")),
        "feed": feed[-200:][::-1],
    }


def llm_state(root: Path) -> dict:
    """Requests in flight (from .agent/llm-live.json) and TTFT / TPS / concurrency of recent calls."""
    now = time.time()
    path = root / ".agent" / "llm-live.json"
    try:
        live = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        live = {}
    requests = []
    for r in live.get("requests", []):
        first = r["sent"] + r["ttft"] if r.get("ttft") is not None else None
        tokens = r.get("chars", 0) / 3.5  # streamed text, about 3.5 characters per token
        requests.append({"label": r.get("label", ""), "phase": r.get("phase", ""), "effort": r.get("effort", ""),
                         "elapsed": round(now - r.get("started", now), 1), "attempt": r.get("attempt", 0),
                         "ttft": r.get("ttft"), "tokens": round(tokens),
                         "tps": round(tokens / (now - first), 1) if first and now - first > 1 else None,
                         "error": r.get("error"), "retry_in": round(r["retry_at"] - now) if r.get("retry_at") else None,
                         "reasoning": r.get("reasoning", ""), "answer": r.get("answer", "")})
    rows = read_jsonl(root / ".agent" / "usage.jsonl")
    recent = [r for r in rows if r.get("ttft") is not None][-40:]

    def pct(values, q):
        values = sorted(v for v in values if v is not None)
        return values[min(len(values) - 1, int(q * len(values)))] if values else None
    spans = [(r["time"], r["time"] + r.get("seconds", 0)) for r in rows]
    peak = max((sum(1 for a, b in spans if a <= start < b) for start, _ in spans), default=0)
    return {"requests": requests, "concurrency": len(requests), "peak": peak,
            "ttft": {"p50": pct([r["ttft"] for r in recent], .5), "p90": pct([r["ttft"] for r in recent], .9)},
            "tps": {"p50": pct([r.get("tps") for r in recent], .5), "p10": pct([r.get("tps") for r in recent], .1)},
            "calls": [{"label": r.get("label", ""), "ttft": r.get("ttft"), "tps": r.get("tps"), "seconds": r.get("seconds"),
                       "completion": r.get("completion"), "reasoning": r.get("reasoning"), "retries": r.get("retries", 0)}
                      for r in rows[-12:]][::-1],
            "measured": len(recent)}


def transcript(root: Path, start: int) -> dict:
    """Transcript records from index `start` on: messages and compaction markers, for the chat view."""
    records = read_jsonl(root / ".agent" / "engineer.jsonl")
    out = []
    for index, record in enumerate(records[start:], start):
        if record.get("type") == "message":
            message = dict(record["message"])
            if isinstance(message.get("content"), str) and len(message["content"]) > 30000:
                message["content"] = message["content"][:30000] + "\n… (clipped in the viewer)"
            out.append({"i": index, "kind": "message", "message": message})
        elif record.get("type") == "compaction":
            out.append({"i": index, "kind": "compaction", "summary": (record.get("state") or {}).get("summary", "")})
    return {"next": len(records), "items": out}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir")
    parser.add_argument("--log", required=True)
    parser.add_argument("--req", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root, log = Path(args.output_dir).expanduser().resolve(), Path(args.log).expanduser().resolve()
    tree = spec.load(Path(args.req).expanduser().resolve())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/state"):
                body, kind = json.dumps(collect(root, log, tree), ensure_ascii=False).encode(), "application/json"
            elif self.path.startswith("/api/stream"):
                self.stream()
                return
            elif self.path.startswith("/api/llm"):
                body, kind = json.dumps(llm_state(root), ensure_ascii=False).encode(), "application/json"
            elif self.path.startswith("/api/transcript"):
                start = int(self.path.partition("from=")[2] or 0)
                body, kind = json.dumps(transcript(root, start), ensure_ascii=False).encode(), "application/json"
            else:
                body, kind = (HERE / "index.html").read_bytes(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def stream(self):
            """Server-sent events: the LLM state whenever the live file changes, and at least every 2 seconds."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            live, seen, sent = root / ".agent" / "llm-live.json", None, 0.0
            try:
                while True:
                    stamp = live.stat().st_mtime if live.exists() else None
                    if stamp != seen or time.time() - sent > 2:
                        seen, sent = stamp, time.time()
                        data = json.dumps(llm_state(root), ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                    time.sleep(0.15)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the page was closed

        def log_message(self, *_args):
            pass

    print(f"watching {root} at http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

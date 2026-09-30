"""One agent session: the model calls tools until it calls `done` or runs out of steps."""
from __future__ import annotations

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dataclasses import dataclass
from typing import Callable

import checkpoint
import compaction
from checkpoint import Transcript
from llm import EFFORTS, LLM
from tools import Tools, is_read_only

DONE = {"name": "done", "description": "Finish this task. Call only after the check tool passes, or when "
        "no further progress is possible; summarize what was built and what is still missing.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp"}
DESCRIBE = ("Describe this UI screenshot for a developer who must rebuild it: overall layout, every visible "
            "control with its exact label text, headings, lists and table structure, and visible states.")
_visual: dict[str, LLM] = {}
_visual_lock = threading.Lock()


def read_image(llm: LLM, tools: Tools, arguments: str) -> tuple[str, dict | None] | None:
    """For image paths: attach the image for a vision model, otherwise describe it with the visual model."""
    path = json.loads(arguments or "{}").get("path", "")
    mime = IMAGE_TYPES.get(Path(path).suffix.lower())
    if not mime:
        return None
    data = base64.b64encode(tools._path(path, write=False).read_bytes()).decode()
    image = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}
    if llm.vision:
        return (f"Image {path} is attached in the next message.",
                {"role": "user", "content": [{"type": "text", "text": f"Image {path}:"}, image]})
    with _visual_lock:
        if "llm" not in _visual:
            _visual["llm"] = LLM.visual()
            _visual["llm"].label = "visual"
    visual = _visual["llm"]
    reply = visual.chat("You describe images accurately.",
                        [{"role": "user", "content": [{"type": "text", "text": DESCRIBE}, image]}], [])
    return f"Description of image {path} (from a vision model):\n{reply.text}", None


def read_call(llm: LLM, tools: Tools, arguments: str) -> tuple[str, dict | None]:
    """Result of a read tool call and an optional image attachment."""
    try:
        image = read_image(llm, tools, arguments)
    except Exception as error:
        image = (f"ERROR: {type(error).__name__}: {error}", None)
    return image or (tools.run("read", arguments), None)


def set_reasoning(llm: LLM, arguments: str) -> str:
    try:
        level = json.loads(arguments or "{}").get("level", "")
    except ValueError:
        level = ""
    if level not in EFFORTS:
        return f"ERROR: level must be one of {', '.join(EFFORTS)}"
    llm.effort = level
    return f"reasoning set to {level}"


def read_only(call: dict) -> bool:
    if call["name"] == "read":
        return True
    if call["name"] != "bash":
        return False
    try:
        return is_read_only(json.loads(call["arguments"] or "{}").get("command", ""))
    except ValueError:
        return False


def prefetch_reads(llm: LLM, tools: Tools, calls: list[dict]) -> dict[str, tuple[str, dict | None]]:
    """Run the read-only calls (file reads, read-only shell commands) that precede the first other call of a
    reply concurrently; they cannot observe that call's effects, so the result equals sequential execution."""
    leading = []
    for call in calls:
        if not read_only(call):
            break
        leading.append(call)
    if len(leading) < 2:
        return {}

    def execute(call: dict) -> tuple[str, dict | None]:
        if call["name"] == "read":
            return read_call(llm, tools, call["arguments"])
        return tools.run(call["name"], call["arguments"]), None
    with ThreadPoolExecutor(max_workers=min(8, len(leading))) as pool:
        return {call["id"]: result for call, result in zip(leading, pool.map(execute, leading))}


@dataclass
class Extra:
    schema: dict
    run: Callable[[dict], str]


HARD_LIMIT_FACTOR = 4  # guard against a session that never converges
REASONING = {"name": "set_reasoning", "description": "Set how much the model reasons before each following "
             "reply: low for routine reading and edits, medium for design, high for a failure you do not "
             "understand. It stays until changed.",
             "parameters": {"type": "object", "properties": {"level": {"type": "string", "enum": list(EFFORTS)}},
                            "required": ["level"]}}


def run(llm: LLM, system: str, task: str, tools: Tools, *, extras: dict[str, Extra] | None = None,
        max_steps: int = 60, on_done: Callable[[str], str] | None = None, label: str = "",
        transcript: Transcript | None = None, resume: int | str | None = None, note: str | None = None,
        on_step: Callable[[int], str | None] | None = None,
        refresh: Callable[[], tuple[str | None, str]] | None = None) -> str:
    """Returns the model's final summary. `on_done` may return an error text to refuse finishing.

    With a transcript every message is recorded and each step ends with a workspace commit. `resume`
    ("last" or a step number) continues from that checkpoint: files are reset to its commit and later
    transcript records are archived.
    """
    extras = extras or {}
    schemas = [{"type": "function", "function": s}
               for s in [*tools.schemas, *(e.schema for e in extras.values()), REASONING, DONE]]
    llm.label = label
    messages: list[dict] = []
    summary_state: dict = {}
    first = 1
    if transcript and resume is None:
        transcript.archive()  # a fresh session never appends to an earlier attempt's records
    loaded = transcript.load(None if resume == "last" else resume) if transcript and resume is not None else None
    if loaded:
        messages, summary_state, step, sha = loaded
        checkpoint.reset(tools.root, sha)
        transcript.truncate(step)
        first = step + 1
        print(f"[{label}] resumed at step {step} ({len(messages)} messages, commit {sha[:8]})", flush=True)
        for message in messages:  # the reasoning level chosen before the checkpoint
            for call in message.get("tool_calls") or []:
                if call["function"]["name"] == "set_reasoning":
                    set_reasoning(llm, call["function"]["arguments"])

    def add(message: dict) -> None:
        messages.append(message)
        if transcript:
            transcript.message(message)

    if not messages:
        add({"role": "user", "content": task})
    if note:
        add({"role": "user", "content": note})
    started = time.time()
    review_at, hard_limit = max_steps, max_steps * HARD_LIMIT_FACTOR
    while review_at < first:
        review_at += max(10, max_steps // 2)
    for step in range(first, hard_limit + 1):
        compacted = compaction.compact(llm, system, schemas, messages, summary_state, refresh)
        if compacted is not messages:
            messages = compacted
            if transcript:
                transcript.compaction(messages, summary_state)
        if step == review_at:  # a budget review, not a stop: the agent decides whether to continue
            review_at += max(10, max_steps // 2)
            add({"role": "user", "content": f"You have used {step - 1} steps; the planned budget was {max_steps}. "
                 "Decide now. If recent checks show progress and the remaining failures look fixable, keep working "
                 f"(you will be asked again after step {review_at}). If you are stuck or the rest is out of reach, "
                 "make sure the app builds and starts, then call done with an honest summary of what passes and "
                 "what does not."})
        if step == hard_limit - 3:
            add({"role": "user", "content": "Only 3 steps remain: make the app build and start, "
                 "run check, then call done with an honest summary."})
        reply = llm.chat(system, messages, schemas)
        add(reply.message)
        if not reply.tool_calls:
            add({"role": "user", "content": "Continue with tool calls, or call done if finished."})
        attachments = []
        prefetched = prefetch_reads(llm, tools, reply.tool_calls)
        for call in reply.tool_calls:
            name = call["name"]
            if name == "done":
                try:
                    args = json.loads(call["arguments"] or "{}")
                except ValueError:
                    args = {"summary": call["arguments"]}
                refusal = on_done(args.get("summary", "")) if on_done else ""
                if not refusal:
                    add({"role": "tool", "tool_call_id": call["id"], "content": "finished"})
                    if transcript:
                        transcript.checkpoint(step, len(messages), label)
                    print(f"[{label}] done in {step} steps, {time.time() - started:.0f}s: "
                          f"{args.get('summary', '')[:300]}", flush=True)
                    return args.get("summary", "")
                result = refusal
            elif name in extras:
                try:
                    result = extras[name].run(json.loads(call["arguments"] or "{}"))
                except Exception as error:
                    result = f"ERROR: {type(error).__name__}: {error}"
            elif name == "set_reasoning":
                result = set_reasoning(llm, call["arguments"])
            elif call["id"] in prefetched:
                result, attachment = prefetched.pop(call["id"])
                if attachment:
                    attachments.append(attachment)
            elif name == "read":
                result, attachment = read_call(llm, tools, call["arguments"])
                if attachment:
                    attachments.append(attachment)
            else:
                result = tools.run(name, call["arguments"])
            print(f"[{label}] {step} {name} {call['arguments'][:120]!r} -> {result[:160]!r}", flush=True)
            add({"role": "tool", "tool_call_id": call["id"], "content": result})
        for attachment in attachments:  # user messages may only follow the complete batch of tool results
            add(attachment)
        if getattr(reply, "finish", "") == "length":
            add({"role": "user", "content": "Your reply reached the output token limit and was cut off, so its "
                 "last tool call is incomplete. Write large files in several smaller parts (write, then edit to "
                 "append) and keep reasoning brief."})
        advice = on_step(step) if on_step else None
        if advice:
            add({"role": "user", "content": advice})
        if transcript:
            transcript.checkpoint(step, len(messages), label)
    print(f"[{label}] step limit reached after {time.time() - started:.0f}s", flush=True)
    return "step limit reached"

"""One agent session: the model calls tools until it calls `done` or runs out of steps."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Callable

import compaction
from llm import LLM
from tools import SCHEMAS, Tools

DONE = {"name": "done", "description": "Finish this task. Call only after the check tool passes, or when "
        "no further progress is possible; summarize what was built and what is still missing.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp"}
DESCRIBE = ("Describe this UI screenshot for a developer who must rebuild it: overall layout, every visible "
            "control with its exact label text, headings, lists and table structure, and visible states.")
_visual: dict[str, LLM] = {}


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
    if "llm" not in _visual:
        _visual["llm"] = LLM.visual()
    visual = _visual["llm"]
    reply = visual.chat("You describe images accurately.",
                        [{"role": "user", "content": [{"type": "text", "text": DESCRIBE}, image]}], [])
    return f"Description of image {path} (from a vision model):\n{reply.text}", None


@dataclass
class Extra:
    schema: dict
    run: Callable[[dict], str]


def run(llm: LLM, system: str, task: str, tools: Tools, *, extras: dict[str, Extra] | None = None,
        max_steps: int = 60, on_done: Callable[[str], str] | None = None, label: str = "") -> str:
    """Returns the model's final summary. `on_done` may return an error text to refuse finishing."""
    extras = extras or {}
    schemas = [{"type": "function", "function": s} for s in [*SCHEMAS, *(e.schema for e in extras.values()), DONE]]
    messages: list[dict] = [{"role": "user", "content": task}]
    summary_state: dict = {}
    started = time.time()
    for step in range(1, max_steps + 1):
        messages = compaction.compact(llm, messages, summary_state)
        if step == max_steps - 3:
            messages.append({"role": "user", "content": "Only 3 steps remain: make the app build and start, "
                             "run check, then call done with an honest summary."})
        reply = llm.chat(system, messages, schemas)
        messages.append(reply.message)
        if not reply.tool_calls:
            messages.append({"role": "user", "content": "Continue with tool calls, or call done if finished."})
            continue
        attachments = []
        for call in reply.tool_calls:
            name = call["name"]
            if name == "done":
                args = json.loads(call["arguments"] or "{}")
                refusal = on_done(args.get("summary", "")) if on_done else ""
                if not refusal:
                    print(f"[{label}] done in {step} steps, {time.time() - started:.0f}s: "
                          f"{args.get('summary', '')[:300]}", flush=True)
                    return args.get("summary", "")
                result = refusal
            elif name in extras:
                try:
                    result = extras[name].run(json.loads(call["arguments"] or "{}"))
                except Exception as error:
                    result = f"ERROR: {type(error).__name__}: {error}"
            else:
                image = None
                if name == "read":
                    try:
                        image = read_image(llm, tools, call["arguments"])
                    except Exception as error:
                        image = (f"ERROR: {type(error).__name__}: {error}", None)
                if image:
                    result, attachment = image
                    if attachment:
                        attachments.append(attachment)
                else:
                    result = tools.run(name, call["arguments"])
            print(f"[{label}] {step} {name} {call['arguments'][:120]!r} -> {result[:160]!r}", flush=True)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        messages.extend(attachments)  # user messages may only follow the complete batch of tool results
    print(f"[{label}] step limit reached after {time.time() - started:.0f}s", flush=True)
    return "step limit reached"

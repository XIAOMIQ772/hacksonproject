"""Context compaction modelled on pi: summarize the old part of a session, keep recent turns verbatim.

History stays append-only between compactions so the provider's prompt cache keeps hitting; a
compaction rewrites the prefix once: [task, summary, recent turns...].
"""
from __future__ import annotations

import json
import os

from llm import LLM

TRIGGER_TOKENS = int(os.environ.get("AGENT_CONTEXT_TOKENS", "60000"))
KEEP_RECENT_TOKENS = int(os.environ.get("AGENT_KEEP_RECENT_TOKENS", "16000"))
TOOL_RESULT_CHARS = 2000
SUMMARY_TAG = "[Summary of earlier work in this task]"

SUMMARY_SYSTEM = """You write a handover summary of a coding session so another engineer can continue it \
without the original transcript. Be specific: file paths, function and component names, commands, \
error messages, exact UI strings. Use these sections:

## Goal
## Constraints & Preferences
## Progress
### Done
### In Progress
### Blocked
## Key Decisions
## Next Steps
## Critical Context

If a previous summary is given, merge it: keep what is still true, update progress, drop what is obsolete."""


IMAGE_TOKENS = 1500  # providers bill a screenshot at a few hundred to ~1.5k tokens, not its base64 size


def estimate(messages: list[dict]) -> int:
    """Conservative token estimate (code and JSON average about 3.5 characters per token)."""
    total = 0
    for m in messages:
        if isinstance(m.get("content"), list):
            images = sum(1 for p in m["content"] if p.get("type") == "image_url")
            text = [p for p in m["content"] if p.get("type") != "image_url"]
            total += images * IMAGE_TOKENS + len(json.dumps({**m, "content": text}, ensure_ascii=False)) * 10 // 35
        else:
            total += len(json.dumps(m, ensure_ascii=False)) * 10 // 35
    return total


def cut_index(messages: list[dict], keep_tokens: int) -> int:
    """Index of the first kept message: an assistant turn, so tool results stay with their call."""
    total, cut = 0, len(messages)
    for i in range(len(messages) - 1, 0, -1):
        total += estimate([messages[i]])
        if messages[i]["role"] == "assistant":
            cut = i
            if total >= keep_tokens:
                break
    return cut


def serialize(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        if m["role"] == "user":
            content = m["content"]
            if isinstance(content, list):  # text + image parts
                content = " ".join(p.get("text", "[image]") for p in content)
            parts.append(f"[User]: {content}")
        elif m["role"] == "assistant":
            if m.get("reasoning_content"):
                parts.append(f"[Assistant thinking]: {m['reasoning_content'][:1500]}")
            if m.get("content"):
                parts.append(f"[Assistant]: {m['content']}")
            for call in m.get("tool_calls") or []:
                parts.append(f"[Assistant tool call]: {call['function']['name']} {call['function']['arguments'][:1500]}")
        elif m["role"] == "tool":
            text = m["content"]
            if len(text) > TOOL_RESULT_CHARS:
                text = text[:TOOL_RESULT_CHARS] + f"\n[... {len(text) - TOOL_RESULT_CHARS} chars truncated]"
            parts.append(f"[Tool result]: {text}")
    return "\n\n".join(parts)


def file_ops(messages: list[dict]) -> tuple[set[str], set[str]]:
    read, modified = set(), set()
    for m in messages:
        for call in m.get("tool_calls") or []:
            try:
                path = json.loads(call["function"]["arguments"]).get("path")
            except (ValueError, AttributeError):
                continue
            name = call["function"]["name"]
            if path and name == "read":
                read.add(path)
            elif path and name in ("write", "edit"):
                modified.add(path)
    return read, modified


def compact(llm: LLM, messages: list[dict], state: dict) -> list[dict]:
    """Returns the new message list; `state` carries the previous summary and file lists across compactions."""
    if estimate(messages) <= TRIGGER_TOKENS:
        return messages
    second = messages[1]["content"] if len(messages) > 1 else ""
    start = 2 if isinstance(second, str) and second.startswith(SUMMARY_TAG) else 1
    cut = cut_index(messages, KEEP_RECENT_TOKENS)
    if cut <= start:
        return messages
    old = messages[start:cut]
    read, modified = file_ops(old)
    state["read"] = (state.get("read", set()) | read) - modified
    state["modified"] = state.get("modified", set()) | modified
    previous = state.get("summary", "")
    prompt = (f"Task given to the engineer:\n{messages[0]['content'][:6000]}\n\n"
              + (f"Previous summary:\n{previous}\n\n" if previous else "")
              + f"Conversation to summarize:\n{serialize(old)}")
    reply = llm.chat(SUMMARY_SYSTEM, [{"role": "user", "content": prompt}], [])
    summary = reply.text.strip() or previous
    state["summary"] = summary
    files = (f"\n<read-files>\n{chr(10).join(sorted(state['read']))}\n</read-files>"
             f"\n<modified-files>\n{chr(10).join(sorted(state['modified']))}\n</modified-files>")
    before = estimate(messages)
    new = [messages[0], {"role": "user", "content": f"{SUMMARY_TAG}\n{summary}{files}"}, *messages[cut:]]
    print(f"[compact] {before} -> {estimate(new)} tokens (summarized {len(old)} messages)", flush=True)
    return new

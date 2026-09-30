"""Context compaction modelled on Codex: the session writes its own handover summary, then its history is
replaced by [fresh task, summary, recent turns].

The summary request is the current conversation plus one instruction, so the provider's prompt cache
covers almost all of it and nothing is truncated. Between compactions history stays append-only.
"""
from __future__ import annotations

import json
import os
from typing import Callable

from llm import LLM, FatalModelError

TRIGGER_TOKENS = int(os.environ.get("AGENT_CONTEXT_TOKENS", "600000"))
KEEP_RECENT_TOKENS = int(os.environ.get("AGENT_KEEP_RECENT_TOKENS", "40000"))
SUMMARY_TAG = "[Handover summary: an earlier part of this session was compacted]"

SUMMARY_REQUEST = """CONTEXT CHECKPOINT. Your earlier messages will be removed from the conversation and \
replaced by the summary you write now; another instance of you continues from it. Do not call tools; \
answer with the summary only. The continuation also receives the task again with a fresh code map and the \
current content of the files the task owns, the latest check report and any unaddressed reviewer \
feedback, so do not copy those. Write:

## Requirement checklist
Each requirement or scenario of the task: done and passing / implemented but failing (why) / not started.
## Decisions
Design choices made and the reasons, including approaches tried and abandoned.
## Current problem
What is being worked on right now, the evidence (failing test, error text) and the current hypothesis.
## Next steps
Concrete, in order.
## Critical details
Exact UI strings, file paths, function names, commands and facts learned that are not visible in the code."""

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


def summarize(llm: LLM, system: str, tools: list[dict], messages: list[dict]) -> str:
    """The session's own summary of `messages`. If the request itself is too long for the model, the oldest
    turns after the task are dropped first, which keeps the cached prefix as long as possible."""
    history = list(messages)
    for _ in range(4):
        try:
            reply = llm.chat(system, [*history, {"role": "user", "content": SUMMARY_REQUEST}], tools,
                             tool_choice="none")
            return reply.text.strip()
        except FatalModelError as error:
            if not any(word in str(error).lower() for word in ("context", "length", "too long", "maximum")):
                raise
            cut = cut_index(history, estimate(history) // 2)
            history = [history[0], *history[max(cut, 2):]]
    return ""


def compact(llm: LLM, system: str, tools: list[dict], messages: list[dict], state: dict,
            refresh: Callable[[], tuple[str | None, str]] | None = None) -> list[dict]:
    """New message list when the history exceeds the trigger, else `messages` unchanged.

    `refresh` returns (fresh task text or None to keep the original, harness facts to attach verbatim)."""
    if estimate(messages) <= TRIGGER_TOKENS:
        return messages
    cut = cut_index(messages, KEEP_RECENT_TOKENS)
    if cut <= 1:
        return messages
    summary = summarize(llm, system, tools, messages) or state.get("summary", "")
    task, facts = refresh() if refresh else (None, "")
    state["summary"] = summary
    state["count"] = state.get("count", 0) + 1
    first = {"role": "user", "content": task} if task else messages[0]
    note = f"{SUMMARY_TAG}\n{summary}" + (f"\n\n{facts}" if facts else "")
    new = [first, {"role": "user", "content": note}, *messages[cut:]]
    print(f"[compact] {estimate(messages)} -> {estimate(new)} tokens (replaced {cut - 1} messages)", flush=True)
    return new

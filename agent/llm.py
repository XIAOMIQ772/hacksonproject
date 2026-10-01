"""OpenAI-compatible chat client with DeepSeek thinking support, retries and usage accounting."""
from __future__ import annotations

import itertools
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import APIStatusError, OpenAI


class FatalModelError(RuntimeError):
    """Credentials, quota or a request the provider will never accept."""


USAGE_LOG: Path | None = None  # one JSON line per model call when set (see usage_report)
_log_lock = threading.Lock()

# Requests in flight, rewritten to LIVE_FILE when one changes phase (connecting, waiting for the first token,
# reasoning, answering, retrying) and at most every LIVE_INTERVAL while tokens stream, for the run viewer. The
# record carries the tail of the text streamed so far.
LIVE_FILE: Path | None = None
_live: dict[int, dict] = {}
_live_lock = threading.Lock()
_live_ids = itertools.count(1)
_live_written = 0.0
LIVE_INTERVAL = 0.3
LIVE_TAIL = 6000  # characters of streamed reasoning and answer kept in the live record


def _live_update(key: int, force: bool = False, remove: bool = False, **fields) -> None:
    global _live_written
    with _live_lock:
        if remove:
            _live.pop(key, None)
        else:
            _live.setdefault(key, {}).update(fields)
        now = time.time()
        if not LIVE_FILE or (not force and now - _live_written < LIVE_INTERVAL):
            return
        _live_written = now
        tmp = LIVE_FILE.with_name(LIVE_FILE.name + ".tmp")
        tmp.write_text(json.dumps({"time": now, "requests": list(_live.values())}, ensure_ascii=False))
        tmp.replace(LIVE_FILE)


@dataclass
class Usage:
    calls: int = 0
    prompt: int = 0
    cached: int = 0
    completion: int = 0
    reasoning: int = 0

    def add(self, usage) -> dict:
        if not usage:
            return {}
        details = getattr(usage, "prompt_tokens_details", None)
        out_details = getattr(usage, "completion_tokens_details", None)
        record = {"prompt": usage.prompt_tokens or 0, "completion": usage.completion_tokens or 0,
                  "cached": (getattr(details, "cached_tokens", 0) or 0) if details else 0,
                  "reasoning": (getattr(out_details, "reasoning_tokens", 0) or 0) if out_details else 0}
        self.calls += 1
        self.prompt += record["prompt"]
        self.cached += record["cached"]
        self.completion += record["completion"]
        self.reasoning += record["reasoning"]
        return record

    def __str__(self) -> str:
        return (f"calls={self.calls} prompt={self.prompt} cached={self.cached} completion={self.completion} "
                f"reasoning={self.reasoning}")


def usage_report(path: Path) -> str:
    """Totals per model and per session role from a usage log."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    if not rows:
        return "no model calls recorded"

    def role(label: str) -> str:
        if ":helper" in label:
            return "helper"
        return "visual" if label == "visual" else "engineer"

    lines = []
    for title, key in (("model", lambda r: r["model"]), ("role", lambda r: role(r["label"]))):
        groups: dict[str, list[dict]] = {}
        for row in rows:
            groups.setdefault(key(row), []).append(row)
        for name, items in sorted(groups.items()):
            prompt, cached = sum(r["prompt"] for r in items), sum(r["cached"] for r in items)
            lines.append(f"{title}={name}: calls={len(items)} prompt={prompt} cached={cached} "
                         f"({100 * cached // max(prompt, 1)}%) completion={sum(r['completion'] for r in items)} "
                         f"reasoning={sum(r['reasoning'] for r in items)} seconds={sum(r['seconds'] for r in items):.0f}")
    return "\n".join(lines)


@dataclass
class Reply:
    message: dict              # assistant message, replayable verbatim (keeps reasoning_content)
    tool_calls: list[dict] = field(default_factory=list)
    text: str = ""
    finish: str = ""


# Models known to accept image input; MODEL_VISION=1/0 overrides for anything else.
VISION_MODELS = ("glm-5.3-flash", "glm-5.3", "deepseek-v4-flash-vision-exp")


def supports_vision(model: str) -> bool:
    override = os.environ.get("MODEL_VISION")
    if override in ("0", "1"):
        return override == "1"
    return model in VISION_MODELS or "vision" in model


REASONING_EFFORT = os.environ.get("AGENT_REASONING_EFFORT", "high")  # a subagent may be given another level
EFFORTS = ("low", "high", "max")  # DeepSeek maps medium to high
# Transient failures (connection errors, timeouts, 5xx, rate limits) are retried for this long before the run
# gives up and delivers its current state; credential and quota errors stop immediately.
RETRY_SECONDS = int(os.environ.get("AGENT_RETRY_SECONDS", "900"))
# Replies are streamed; a connection that delivers nothing for this long is dropped and the request retried.
IDLE_SECONDS = int(os.environ.get("AGENT_IDLE_SECONDS", "90"))


class LLM:
    def __init__(self, model: str | None = None, *, api_key: str | None = None, base_url: str | None = None,
                 max_tokens: int | None = int(os.environ.get("AGENT_MAX_TOKENS", "131072"))):
        self.model = model or os.environ.get("MODEL") or "glm-5.3-flash"
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"),
                             base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
                             timeout=IDLE_SECONDS, max_retries=0)
        self.max_tokens = max_tokens
        self.vision = supports_vision(self.model)
        self.usage = Usage()
        self.effort = REASONING_EFFORT  # one of EFFORTS, or "" for the endpoint default
        self.label = ""  # session name recorded in the usage log

    @classmethod
    def visual(cls) -> "LLM":
        """The platform's separate vision model, used when the main model cannot read images."""
        visual = cls(os.environ.get("VISUAL_MODEL") or "deepseek-v4-flash-vision-exp",
                     api_key=os.environ.get("VISUAL_API_KEY"), base_url=os.environ.get("VISUAL_BASE_URL"),
                     max_tokens=None)
        visual.effort = "low"  # describing an image needs no long reasoning
        return visual

    def chat(self, system: str, messages: list[dict], tools: list[dict], tool_choice: str | None = None) -> Reply:
        request = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages]}
        if self.max_tokens:  # None: the endpoint's own limit
            request["max_tokens"] = self.max_tokens
        if tools:
            request["tools"] = tools
            if tool_choice:
                request["tool_choice"] = tool_choice
        if self.model.startswith(("deepseek", "glm")):
            request["extra_body"] = {"thinking": {"type": "enabled"}}
            if self.effort:  # ignored by endpoints without the control
                request["extra_body"]["reasoning_effort"] = self.effort
        request.update(stream=True, stream_options={"include_usage": True})
        started = time.time()
        attempt = 0
        key = next(_live_ids)
        timing: dict = {}

        def progress(kind: str, text: str) -> None:
            if "first" not in timing:
                timing["first"] = time.time()
                _live_update(key, force=True, phase=kind, ttft=round(timing["first"] - timing["sent"], 2))
            timing["chars"] = timing.get("chars", 0) + len(text)
            timing[kind] = (timing.get(kind, "") + text)[-LIVE_TAIL:]
            phase = _live.get(key, {}).get("phase")
            _live_update(key, force=phase != kind, phase=kind, chars=timing["chars"],
                         reasoning=timing.get("reasoning", ""), answer=timing.get("answering", ""))

        while True:
            timing.update(sent=time.time(), chars=0, reasoning="", answering="")
            timing.pop("first", None)
            _live_update(key, force=True, label=self.label, model=self.model, effort=self.effort, started=started,
                         sent=timing["sent"], phase="connecting", attempt=attempt, chars=0, ttft=None,
                         reasoning="", answer="")
            try:
                stream = self.client.chat.completions.create(**request)
                _live_update(key, force=True, phase="waiting")
                message, finish, usage = self._receive(stream, progress)
                break
            except APIStatusError as error:
                body = str(error.body or error.message).lower()
                if error.status_code in (401, 402, 403) or (error.status_code == 429 and "quota" in body):
                    raise FatalModelError(str(error)) from error
                # The gateway reports proxy connection resets as 400; everything else 4xx is ours.
                if error.status_code < 500 and error.status_code != 429 and "proxy" not in body:
                    raise FatalModelError(str(error)) from error
                retry = error
            except (AttributeError, KeyError, NameError, TypeError):  # a bug here, not a network problem
                raise
            except Exception as error:  # connection reset, idle timeout or a broken stream: send the request again
                retry = error
            if time.time() - started > RETRY_SECONDS:  # an outage, not a network hiccup
                raise FatalModelError(f"model unavailable for {RETRY_SECONDS}s: {retry}")
            wait = min(60, 5 * 2 ** attempt)
            attempt += 1
            print(f"[llm] {type(retry).__name__}: {str(retry)[:200]}; retry in {wait}s", flush=True)
            _live_update(key, force=True, phase="retrying", error=f"{type(retry).__name__}: {str(retry)[:160]}",
                         retry_at=time.time() + wait)
            time.sleep(wait)
        ended = time.time()
        _live_update(key, force=True, remove=True)
        record = self.usage.add(usage)
        if USAGE_LOG and record:
            first = timing.get("first")
            record.update(time=round(started, 1), seconds=round(ended - started, 1), model=self.model,
                          label=self.label, effort=self.effort, retries=attempt, finish=finish,
                          ttft=round(first - timing["sent"], 2) if first else None,
                          tps=round(record["completion"] / (ended - first), 1) if first and ended > first else None)
            with _log_lock, USAGE_LOG.open("a") as log:
                log.write(json.dumps(record) + "\n")
        calls = [{"id": c["id"], "name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                 for c in message.get("tool_calls") or []]
        return Reply(message, calls, message.get("content") or "", finish)

    @staticmethod
    def _receive(stream, progress=None) -> tuple[dict, str, object]:
        """Assemble a streamed reply into (assistant message, finish reason, usage). `progress(kind, text)` is
        told about every streamed piece: kind "reasoning" or "answering"."""
        content, reasoning, calls, finish, usage = [], [], {}, "", None
        for chunk in stream:
            usage = getattr(chunk, "usage", None) or usage
            for choice in chunk.choices or []:
                delta = choice.delta
                finish = choice.finish_reason or finish
                if delta.content:
                    content.append(delta.content)
                    if progress:
                        progress("answering", delta.content)
                thought = getattr(delta, "reasoning_content", None) or (delta.model_extra or {}).get("reasoning_content")
                if thought:
                    reasoning.append(thought)
                    if progress:
                        progress("reasoning", thought)
                for part in delta.tool_calls or []:
                    if progress and part.function:
                        name = f"\n[{part.function.name}] " if part.function.name else ""
                        progress("answering", name + (part.function.arguments or ""))
                    call = calls.setdefault(part.index, {"id": "", "type": "function",
                                                         "function": {"name": "", "arguments": ""}})
                    call["id"] = part.id or call["id"]
                    if part.function:
                        call["function"]["name"] += part.function.name or ""
                        call["function"]["arguments"] += part.function.arguments or ""
        message: dict = {"role": "assistant", "content": "".join(content)}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        return message, finish, usage

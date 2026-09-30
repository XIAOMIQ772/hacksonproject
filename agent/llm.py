"""OpenAI-compatible chat client with DeepSeek thinking support, retries and usage accounting."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


class FatalModelError(RuntimeError):
    """Credentials, quota or a request the provider will never accept."""


USAGE_LOG: Path | None = None  # one JSON line per model call when set (see usage_report)
_log_lock = threading.Lock()


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
        if label.endswith(":advisor"):
            return "advisor"
        return next((name for name in ("plan", "foundation", "final", "visual", "merge") if label.startswith(name)),
                    "node")

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


REASONING_EFFORT = os.environ.get("AGENT_REASONING_EFFORT", "low")  # starting level; the agent may change it
EFFORTS = ("low", "medium", "high")


class LLM:
    def __init__(self, model: str | None = None, *, api_key: str | None = None, base_url: str | None = None,
                 max_tokens: int = int(os.environ.get("AGENT_MAX_TOKENS", "16384"))):
        self.model = model or os.environ.get("MODEL") or "glm-5.3-flash"
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"),
                             base_url=base_url or os.environ.get("OPENAI_BASE_URL"), timeout=600, max_retries=0)
        self.max_tokens = max_tokens
        self.vision = supports_vision(self.model)
        self.usage = Usage()
        self.effort = REASONING_EFFORT  # low | medium | high | "" (endpoint default)
        self.label = ""  # session name recorded in the usage log

    @classmethod
    def visual(cls) -> "LLM":
        """The platform's separate vision model, used when the main model cannot read images."""
        return cls(os.environ.get("VISUAL_MODEL") or "deepseek-v4-flash-vision-exp",
                   api_key=os.environ.get("VISUAL_API_KEY"), base_url=os.environ.get("VISUAL_BASE_URL"),
                   max_tokens=2048)

    def chat(self, system: str, messages: list[dict], tools: list[dict], tool_choice: str | None = None) -> Reply:
        request = {"model": self.model, "max_tokens": self.max_tokens,
                   "messages": [{"role": "system", "content": system}, *messages]}
        if tools:
            request["tools"] = tools
            if tool_choice:
                request["tool_choice"] = tool_choice
        if self.model.startswith(("deepseek", "glm")):
            request["extra_body"] = {"thinking": {"type": "enabled"}}
            if self.effort:  # ignored by endpoints without the control
                request["extra_body"]["reasoning_effort"] = self.effort
        started = time.time()
        for attempt in range(6):
            try:
                response = self.client.chat.completions.create(**request)
                break
            except APIStatusError as error:
                body = str(error.body or error.message).lower()
                if error.status_code in (401, 402, 403) or (error.status_code == 429 and "quota" in body):
                    raise FatalModelError(str(error)) from error
                # The gateway reports proxy connection resets as 400; everything else 4xx is ours.
                if error.status_code < 500 and error.status_code != 429 and "proxy" not in body:
                    raise FatalModelError(str(error)) from error
                retry = error
            except (APIConnectionError, APITimeoutError) as error:
                retry = error
            wait = min(60, 5 * 2 ** attempt)
            print(f"[llm] {type(retry).__name__}: {str(retry)[:200]}; retry in {wait}s", flush=True)
            time.sleep(wait)
        else:
            raise FatalModelError(f"model unavailable after retries: {retry}")
        record = self.usage.add(response.usage)
        if USAGE_LOG and record:
            record.update(time=round(started, 1), seconds=round(time.time() - started, 1), model=self.model,
                          label=self.label, effort=self.effort, retries=attempt,
                          finish=response.choices[0].finish_reason or "")
            with _log_lock, USAGE_LOG.open("a") as log:
                log.write(json.dumps(record) + "\n")
        choice = response.choices[0]
        message = choice.message.model_dump(exclude_none=True)
        calls = [{"id": c["id"], "name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                 for c in message.get("tool_calls") or []]
        return Reply(message, calls, message.get("content") or "", choice.finish_reason or "")

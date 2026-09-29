"""OpenAI-compatible chat client with DeepSeek thinking support, retries and usage accounting."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


class FatalModelError(RuntimeError):
    """Credentials, quota or a request the provider will never accept."""


@dataclass
class Usage:
    calls: int = 0
    prompt: int = 0
    cached: int = 0
    completion: int = 0

    def add(self, usage) -> None:
        if not usage:
            return
        self.calls += 1
        self.prompt += usage.prompt_tokens or 0
        self.completion += usage.completion_tokens or 0
        details = getattr(usage, "prompt_tokens_details", None)
        self.cached += (getattr(details, "cached_tokens", 0) or 0) if details else 0

    def __str__(self) -> str:
        return f"calls={self.calls} prompt={self.prompt} cached={self.cached} completion={self.completion}"


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


class LLM:
    def __init__(self, model: str | None = None, *, api_key: str | None = None, base_url: str | None = None,
                 max_tokens: int = 8192):
        self.model = model or os.environ.get("MODEL") or "glm-5.3-flash"
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"),
                             base_url=base_url or os.environ.get("OPENAI_BASE_URL"), timeout=600, max_retries=0)
        self.max_tokens = max_tokens
        self.vision = supports_vision(self.model)
        self.usage = Usage()

    @classmethod
    def visual(cls) -> "LLM":
        """The platform's separate vision model, used when the main model cannot read images."""
        return cls(os.environ.get("VISUAL_MODEL") or "deepseek-v4-flash-vision-exp",
                   api_key=os.environ.get("VISUAL_API_KEY"), base_url=os.environ.get("VISUAL_BASE_URL"),
                   max_tokens=2048)

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:
        request = {"model": self.model, "max_tokens": self.max_tokens,
                   "messages": [{"role": "system", "content": system}, *messages]}
        if tools:
            request["tools"] = tools
        if self.model.startswith(("deepseek", "glm")):
            request["extra_body"] = {"thinking": {"type": "enabled"}}
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
        self.usage.add(response.usage)
        choice = response.choices[0]
        message = choice.message.model_dump(exclude_none=True)
        calls = [{"id": c["id"], "name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                 for c in message.get("tool_calls") or []]
        return Reply(message, calls, message.get("content") or "", choice.finish_reason or "")

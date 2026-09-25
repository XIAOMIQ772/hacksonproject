"""Explicit Chat Completions / Responses adapters; persisted payloads are replayed intact."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass
class Completion:
    items: list[dict]
    calls: list[dict]
    text: str
    usage: dict
    complete: bool


class Model:
    def __init__(self, name: str, *, api_key: str, base_url: str | None = None,
                 wire: str = "chat", max_output_tokens: int = 8192, reasoning: str = "low"):
        if wire not in {"chat", "responses"}:
            raise ValueError("OPENAI_WIRE_API must be chat or responses")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self.name, self.wire = name, wire
        self.max_output_tokens, self.reasoning = max_output_tokens, reasoning
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=300, max_retries=0)

    def tool_result(self, call: dict, content: str) -> list[dict]:
        if self.wire == "responses":
            return [{"type": "function_call_output", "call_id": call["id"], "output": content}]
        return [{"role": "tool", "tool_call_id": call["id"], "content": content}]

    def complete(self, system: str, messages: list[dict], tools: list[dict], *, summary: bool = False) -> Completion:
        maximum = min(4096, self.max_output_tokens) if summary else self.max_output_tokens
        if self.wire == "chat":
            request: dict[str, Any] = {"model": self.name, "messages": [{"role": "system", "content": system}, *messages],
                                       "max_tokens": maximum}
            if tools:
                request["tools"] = tools
            if self.name.rsplit("/", 1)[-1].startswith("deepseek-"):
                request["extra_body"] = {"thinking": {"type": "enabled"}}
            if self.reasoning:
                request["reasoning_effort"] = self.reasoning
            response = self.client.chat.completions.create(**request)
            choice = response.choices[0]
            message = choice.message
            calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
                     for c in message.tool_calls or [] if c.type == "function"]
            return Completion([message.model_dump(exclude_none=True)], calls, message.content or "",
                              response.usage.model_dump() if response.usage else {},
                              choice.finish_reason in {"stop", "tool_calls"})
        converted = [{"type": "function", **t["function"], "strict": False} for t in tools]
        request = {"model": self.name, "instructions": system, "input": messages, "store": False,
                   "include": ["reasoning.encrypted_content"], "max_output_tokens": maximum}
        if converted:
            request["tools"] = converted
        if self.reasoning:
            request["reasoning"] = {"effort": self.reasoning}
        response = self.client.responses.create(**request)
        items = [item.model_dump(exclude_none=True) for item in response.output]
        calls = [{"id": item["call_id"], "name": item["name"], "arguments": item["arguments"]}
                 for item in items if item["type"] == "function_call"]
        return Completion(items, calls, response.output_text or "",
                          response.usage.model_dump() if response.usage else {}, response.status == "completed")

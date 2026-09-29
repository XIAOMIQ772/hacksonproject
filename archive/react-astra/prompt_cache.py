"""Prompt-cache request policy and model usage accounting.

The provider owns the cache.  This module only makes the stable prefix
addressable and records the usage fields returned by the provider; it never
stores prompts, completions, or tool results as a cache.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _first_number(values: list[Any]) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return None


class PromptCachePolicy:
    """Resolve whether OpenAI prompt-cache routing fields should be sent."""

    def __init__(self, enabled: bool, key: str | None = None,
                 retention: str | None = None, mode: str = "off") -> None:
        self.enabled = enabled
        self.key = key
        self.retention = retention
        self.mode = mode

    @classmethod
    def from_env(cls, client: Any, model: str, wire_api: str,
                 prefix: list[dict[str, Any]], tools: list[dict[str, Any]]) -> "PromptCachePolicy":
        raw_mode = os.environ.get("AGENT_PROMPT_CACHE", "auto").strip().lower()
        if raw_mode in {"", "auto", "default"}:
            mode = "auto"
        elif raw_mode in {"off", "disabled", "false", "0", "none"}:
            return cls(False, mode="off")
        elif raw_mode in {"openai", "on", "enabled", "true", "1"}:
            mode = "openai"
        else:
            raise ValueError("AGENT_PROMPT_CACHE must be auto, openai, or off")

        base_url = str(getattr(client, "base_url", "") or "")
        host = (urlparse(base_url).hostname or "").lower()
        # An OpenAI-compatible gateway may reject OpenAI-only routing fields.
        # Explicit `openai` is an opt-in for a gateway known to support them.
        if mode == "auto" and host != "api.openai.com":
            return cls(False, mode="provider-auto")

        override = os.environ.get("AGENT_PROMPT_CACHE_KEY", "").strip()
        if override:
            key = override
        else:
            payload = {"version": 1, "model": model, "wire_api": wire_api,
                       "prefix": prefix, "tools": tools}
            digest = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:32]
            key = f"arc-agent-v1-{digest}"
        if len(key) > 64:
            raise ValueError("AGENT_PROMPT_CACHE_KEY must be at most 64 characters")

        raw_retention = os.environ.get("AGENT_PROMPT_CACHE_RETENTION", "").strip().lower()
        retention = None
        if raw_retention:
            if raw_retention in {"in_memory", "in-memory", "memory"}:
                retention = "in-memory"
            elif raw_retention == "24h":
                retention = "24h"
            else:
                raise ValueError("AGENT_PROMPT_CACHE_RETENTION must be in-memory or 24h")
        return cls(True, key=key, retention=retention, mode=mode)

    def request_fields(self) -> dict[str, str]:
        if not self.enabled:
            return {}
        fields: dict[str, str] = {"prompt_cache_key": self.key or "arc-agent-v1"}
        if self.retention:
            fields["prompt_cache_retention"] = self.retention
        return fields


class UsageRecorder:
    """Persist provider usage without inventing missing cache counters."""

    def __init__(self, output_dir: Path, model: str, wire_api: str) -> None:
        self.output_dir = output_dir
        self.model = model
        self.wire_api = wire_api
        self.run_id = uuid.uuid4().hex
        self.rows: list[dict[str, Any]] = []

    def record(self, response: Any, step: int, cache_mode: str,
               estimated_input_tokens: int | None = None) -> dict[str, Any]:
        usage = _value(response, "usage", {}) or {}
        input_details = (_value(usage, "input_tokens_details") or
                         _value(usage, "prompt_tokens_details") or {})
        output_details = _value(usage, "output_tokens_details") or {}
        input_tokens = _first_number([
            _value(usage, "input_tokens"), _value(usage, "prompt_tokens"),
        ])
        output_tokens = _first_number([
            _value(usage, "output_tokens"), _value(usage, "completion_tokens"),
        ])
        total_tokens = _first_number([_value(usage, "total_tokens")])
        cached_tokens = _first_number([
            _value(input_details, "cached_tokens"),
            _value(_value(usage, "prompt_cache_hit_tokens"), "value"),
            _value(usage, "prompt_cache_hit_tokens"),
            _value(usage, "cache_read_input_tokens"),
        ])
        uncached_tokens = _first_number([
            _value(usage, "prompt_cache_miss_tokens"),
            _value(usage, "cache_write_input_tokens"),
        ])
        if uncached_tokens is None and input_tokens is not None and cached_tokens is not None:
            uncached_tokens = max(0, input_tokens - cached_tokens)
        reasoning_tokens = _first_number([
            _value(output_details, "reasoning_tokens"),
            _value(usage, "reasoning_tokens"),
        ])
        row = {
            "run_id": self.run_id, "step": step, "model": self.model,
            "wire_api": self.wire_api, "cache_mode": cache_mode,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cached_input_tokens": cached_tokens,
            "uncached_input_tokens": uncached_tokens,
            "reasoning_tokens": reasoning_tokens,
            "estimated_input_tokens": estimated_input_tokens,
        }
        self.rows.append(row)
        arc = self.output_dir / ".arc"
        arc.mkdir(parents=True, exist_ok=True)
        with (arc / "model-usage.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._write_summary()
        return row

    def _write_summary(self) -> None:
        def total(name: str) -> int:
            return sum(row[name] for row in self.rows if isinstance(row.get(name), int))
        def total_or_none(name: str) -> int | None:
            return total(name) if any(isinstance(row.get(name), int) for row in self.rows) else None
        known_input = total("input_tokens")
        known_cached = total("cached_input_tokens")
        has_cached_counter = any(isinstance(row.get("cached_input_tokens"), int)
                                 for row in self.rows)
        summary = {
            "run_id": self.run_id, "model": self.model, "wire_api": self.wire_api,
            "requests": len(self.rows),
            "input_tokens": total_or_none("input_tokens"),
            "output_tokens": total_or_none("output_tokens"),
            "total_tokens": total_or_none("total_tokens"),
            "cached_input_tokens": total_or_none("cached_input_tokens"),
            "uncached_input_tokens": total_or_none("uncached_input_tokens"),
            "reasoning_tokens": total_or_none("reasoning_tokens"),
            "known_cache_ratio": (known_cached / known_input)
            if known_input and has_cached_counter else None,
            "cache_ratio_note": "Ratio is reported only when provider returned input and cached token counts.",
        }
        (self.output_dir / ".arc" / "model-usage.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

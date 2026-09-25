"""Durable session events; model context is a projection of committed events."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def estimate_tokens(value: Any) -> int:
    # UTF-8 bytes/3 is deliberately conservative for source code and CJK text.
    return (len(encoded(value)) + 2) // 3


class Transcript:
    def __init__(self, path: Path, metadata: dict | None = None):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = open(self.path.parent / ".writer.lock", "a+b")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError(f"Session is already running: {self.path}") from None
        self.events: list[dict] = []
        try:
            torn = self._load()
            self.stream = self.path.open("ab")
            if not self.events:
                if metadata is None:
                    raise ValueError("A new session needs metadata")
                self.append("session", version=1, **metadata)
            elif self.events[0].get("type") != "session" or self.events[0].get("version") != 1:
                raise ValueError("Unsupported transcript format")
            if torn:
                self.append("tail_recovered", **torn)
                print(f"[session] quarantined an incomplete tail in {torn['artifact']}", file=sys.stderr)
        except BaseException:
            if hasattr(self, "stream"):
                self.stream.close()
            self.lock.close()
            raise

    def _load(self) -> dict | None:
        if not self.path.exists():
            return None
        data = self.path.read_bytes()
        offset = 0
        for line in data.splitlines(keepends=True):
            if not line.endswith(b"\n"):
                # An unfinished write is not a committed event. Preserve it for
                # diagnosis; complete records retain their original bytes.
                digest = hashlib.sha256(line).hexdigest()
                artifact = self.path.with_name(f"{self.path.name}.torn-{digest[:16]}")
                with artifact.open("wb") as backup:
                    backup.write(line)
                    backup.flush()
                    os.fsync(backup.fileno())
                with self.path.open("r+b") as stream:
                    stream.truncate(offset)
                    stream.flush()
                    os.fsync(stream.fileno())
                return {"artifact": str(artifact), "bytes": len(line), "sha256": digest}
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError) as error:
                raise ValueError(f"Corrupt committed transcript record at byte {offset}") from error
            expected_parent = self.events[-1]["id"] if self.events else None
            if (not isinstance(event, dict) or not isinstance(event.get("id"), str)
                    or event.get("seq") != len(self.events) or event.get("parent_id") != expected_parent
                    or any(e["id"] == event["id"] for e in self.events)):
                raise ValueError(f"Invalid transcript sequence at byte {offset}")
            self.events.append(event)
            offset += len(line)
        return None

    def append(self, event_type: str, **payload: Any) -> dict:
        reserved = {"id", "seq", "parent_id", "timestamp", "type"}
        if reserved.intersection(payload):
            raise ValueError("Event payload contains reserved envelope fields")
        event = {"id": uuid.uuid4().hex, "seq": len(self.events),
                 "parent_id": self.events[-1]["id"] if self.events else None,
                 "timestamp": datetime.now(timezone.utc).isoformat(), "type": event_type, **payload}
        data = encoded(event)
        self.stream.write(data + b"\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.events.append(json.loads(data))
        return json.loads(data)

    @property
    def header(self) -> dict:
        return self.events[0]

    @property
    def phase(self) -> dict:
        return next((e for e in reversed(self.events) if e["type"] == "phase"),
                    {"seq": 0, "name": "implementation", "prompt": self.header["prompt"]})

    def context(self) -> tuple[list[dict], list[dict], str]:
        """Return the pinned task, complete message events, and current summary."""
        boundary = self.phase["seq"]
        summary = ""
        for event in self.events[boundary + 1:]:
            if event["type"] == "compaction":
                kept_from = next((e["seq"] for e in self.events if e["id"] == event["through_id"]), None)
                if kept_from is None or not boundary < kept_from < event["seq"]:
                    raise ValueError("Invalid compaction boundary")
                boundary = kept_from
                summary = event["summary"]
        messages = [e for e in self.events[boundary + 1:] if e["type"] == "message"]
        prefix = [{"role": "user", "content": self.phase["prompt"]}]
        if summary:
            prefix.append({"role": "user", "content": "Earlier work summary (original transcript retained):\n" + summary})
        return prefix, messages, summary

    def projection(self) -> list[dict]:
        prefix, messages, _ = self.context()
        return prefix + [item for event in messages for item in event["items"]]

    def compactable(self, keep_tokens: int) -> tuple[list[dict], str | None]:
        """Cut only between complete assistant/tool batches, never inside one."""
        _, messages, _ = self.context()
        groups: list[list[dict]] = []
        pending: set[str] = set()
        for event in messages:
            role = event["role"]
            if role != "tool":
                if pending:
                    raise ValueError("Cannot compact an unfinished tool batch")
                groups.append([])
                pending = {c["id"] for c in event.get("calls", [])}
            elif event.get("call_id") not in pending:
                raise ValueError("Orphan tool result in transcript")
            else:
                pending.remove(event["call_id"])
            if not groups:
                raise ValueError("Context starts with a tool result")
            groups[-1].append(event)
        if pending:
            raise ValueError("Cannot compact an unfinished tool batch")
        keep, tokens = len(groups), 0
        while keep > 0 and (tokens < keep_tokens or keep == len(groups)):
            keep -= 1
            tokens += estimate_tokens([e["items"] for e in groups[keep]])
        old = [e for group in groups[:keep] for e in group]
        return old, old[-1]["id"] if old else None

    def token_usage(self) -> int:
        total = 0
        for event in self.events:
            usage = event.get("usage") or {}
            total += usage.get("total_tokens") or (usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
        return total

    def close(self) -> None:
        self.stream.close()
        self.lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

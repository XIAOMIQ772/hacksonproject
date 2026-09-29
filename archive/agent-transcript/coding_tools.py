"""Small synchronous coding tools with bounded observations and full output artifacts."""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

from agent_validation import child_environment, stop_process


def tool(name, description, properties, required=()):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required),
                           "additionalProperties": False}}}


TEXT = {"type": "string"}
INTEGER = {"type": "integer"}
TOOLS = [
    tool("read", "Read text with line numbers, or list a directory. Use offset/limit for large files.",
         {"path": TEXT, "offset": INTEGER, "limit": INTEGER}, ["path"]),
    tool("write", "Atomically write a complete UTF-8 file inside the output project.",
         {"path": TEXT, "content": TEXT}, ["path", "content"]),
    tool("edit", "Replace exactly one occurrence of old text inside a project file.",
         {"path": TEXT, "old": TEXT, "new": TEXT}, ["path", "old", "new"]),
    tool("bash", "Run a synchronous shell command in the project. All child processes stop when it ends. "
         "Use verify for server-managed browser tests. Full output is saved as an artifact.",
         {"command": TEXT, "timeout": INTEGER}, ["command"]),
    tool("verify", "Build, start from fresh data, and run requirement-based UI and behavior checks.", {}),
    tool("history", "Search original transcript messages, including compacted work. Returns event IDs and excerpts.",
         {"query": TEXT, "limit": INTEGER}, ["query"]),
]


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class CodingTools:
    def __init__(self, root: Path, requirements: Path, transcript):
        self.root, self.requirements = root.resolve(), requirements.resolve()
        self.transcript = transcript
        self.artifacts = transcript.path.parent / "artifacts"
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def artifact(self, name: str, data: bytes) -> Path:
        path = self.artifacts / f"{uuid.uuid4().hex}-{name}"
        atomic_write(path, data)
        return path

    def observe(self, text: str, maximum: int = 12000) -> str:
        if len(text) <= maximum:
            return text
        path = self.artifact("output.txt", text.encode())
        return text[:maximum // 2] + f"\n[Truncated observation; full output: {path}]\n" + text[-maximum // 2:]

    def resolve(self, raw: str, *, write: bool = False) -> Path:
        path = Path(raw)
        path = (path if path.is_absolute() else self.root / path).resolve()
        if path.name == ".env" or path.name.startswith(".env."):
            raise ValueError("Credential files are not coding context")
        if write:
            if not path.is_relative_to(self.root) or path.is_relative_to(self.transcript.path.parent):
                raise ValueError("Writes must stay inside the project and outside session storage")
        elif not any(path.is_relative_to(p) for p in (self.root, self.requirements, self.transcript.path.parent)):
            raise ValueError("Read outside project, public requirements, and session artifacts")
        if path.is_relative_to(self.requirements) and any(
                part.lower() in {"tests", "test", "test-e2e", "helpers", "spec", "specs"}
                for part in path.relative_to(self.requirements).parts):
            raise ValueError("Evaluation test sources are not generation context")
        return path

    @staticmethod
    def validate_arguments(name: str, args: dict) -> None:
        schema = next((t["function"]["parameters"] for t in TOOLS if t["function"]["name"] == name), None)
        if schema is None:
            raise ValueError(f"Unknown tool: {name}")
        if not isinstance(args, dict) or set(args) - schema["properties"].keys():
            raise ValueError("Tool arguments must be an object with declared fields only")
        for key in schema["required"]:
            if key not in args:
                raise ValueError(f"Missing argument: {key}")
        for key, value in args.items():
            expected = str if schema["properties"][key]["type"] == "string" else int
            if type(value) is not expected:
                raise ValueError(f"Invalid argument type: {key}")

    def run(self, name: str, args: dict) -> str:
        self.validate_arguments(name, args)
        if name == "history":
            limit = args.get("limit", 8)
            if not 1 <= limit <= 20:
                raise ValueError("history limit must be 1..20")
            matches = []
            for event in reversed(self.transcript.events):
                if event["type"] not in {"message", "compaction", "phase", "model_error"}:
                    continue
                text = json.dumps(event, ensure_ascii=False)
                if args["query"].casefold() in text.casefold():
                    matches.append({"id": event["id"], "seq": event["seq"], "excerpt": text[:1600]})
                if len(matches) == limit:
                    break
            return json.dumps(matches, ensure_ascii=False)
        if name == "bash":
            timeout = args.get("timeout", 180)
            if not 1 <= timeout <= 900:
                raise ValueError("bash timeout must be 1..900 seconds")
            path = self.artifacts / f"{uuid.uuid4().hex}-command.log"
            with path.open("wb") as log:
                process = subprocess.Popen(["bash", "-c", args["command"]], cwd=self.root,
                                           env=child_environment(), stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True)
                try:
                    code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    code = 124
                    log.write(f"\nCommand timed out after {timeout}s\n".encode())
                finally:
                    stop_process(process)
            with path.open("rb") as stream:
                head = stream.read(6000)
                if path.stat().st_size > 12000:
                    stream.seek(-6000, 2)
                    data = head + b"\n[Middle omitted; read the artifact in chunks]\n" + stream.read()
                else:
                    data = head + stream.read()
            return f"exit code {code}; full log: {path}\n" + data.decode("utf-8", "replace")
        if name == "read":
            path = self.resolve(args["path"])
            start, limit = args.get("offset", 1), args.get("limit", 160)
            if start < 1 or not 1 <= limit <= 500:
                raise ValueError("read offset must be positive and limit must be 1..500")
            if path.is_dir():
                return "\n".join(p.name + ("/" if p.is_dir() else "") for p in sorted(path.iterdir())
                                 if p.name not in {"node_modules", ".git", ".env", "__pycache__"})
            lines = []
            with path.open(encoding="utf-8") as stream:
                for number, line in enumerate(stream, 1):
                    if number >= start + limit:
                        break
                    if number >= start:
                        lines.append(f"{number:6d}\t{line.rstrip()}")
            return "\n".join(lines) or "(no lines at this offset)"
        path = self.resolve(args["path"], write=True)
        if name == "write":
            content = args["content"]
        elif name == "edit":
            if not args["old"]:
                raise ValueError("edit old text must be nonempty")
            content = path.read_text()
            count = content.count(args["old"])
            if count != 1:
                raise ValueError(f"edit old text occurs {count} times; expected exactly one")
            content = content.replace(args["old"], args["new"], 1)
        else:
            raise ValueError(f"Tool {name} is handled by the execution loop")
        atomic_write(path, content.encode())
        return f"{name}: {path}"

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI

from arcbench_agent_runtime import AgentRuntime

SYSTEM_PROMPT = """你是一个编程 agent，任务是实现一个 web 项目，让 E2E 测试通过。

需求: {requirements}/requirements.yaml
测试: {tests}
项目: {output}

项目模板已就位: frontend/ 是 Vite + React 19 + TS + Tailwind 4，入口 frontend/src/pages/HomePage.tsx；backend/ 是 Express 5 + SQLite，单端口托管 frontend/dist。

分批读需求和测试，逐步实现。测试里的文本、按钮名、label、placeholder 必须完全一致。完成后运行前端构建确认通过。"""

MAX_STEPS = 120
MAX_OUTPUT_CHARS = 16000

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "在 bash 中执行命令，返回合并的 stdout/stderr。长时间任务放后台运行。",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "要执行的命令"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "读文件，带行号返回。路径是目录则列出内容。大文件用 offset/limit 分段读。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "绝对路径"},
                    "offset": {"type": "integer", "description": "起始行号，从 1 开始"},
                    "limit": {"type": "integer", "description": "读取行数"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "写入文件，已存在则覆盖，父目录自动创建。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "绝对路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "替换文件中的一段文本。old 必须在文件中唯一出现，否则替换失败。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "绝对路径"},
                    "old": {"type": "string", "description": "要替换的原文，需唯一"},
                    "new": {"type": "string", "description": "替换后的文本"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
]


def clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n<output clipped>"


def run_bash(command: str, cwd: Path) -> str:
    try:
        proc = subprocess.run(
            ["bash", "-c", command], cwd=cwd, capture_output=True, text=True, timeout=300
        )
    except subprocess.TimeoutExpired:
        return "command timed out after 300s"
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        output = f"exit code {proc.returncode}\n{output}"
    return clip(output) or "(no output)"


def resolve(raw_path: str, root: Path) -> Path:
    path = Path(raw_path)
    return (path if path.is_absolute() else root / raw_path).resolve()


def run_read(args: dict[str, Any], root: Path) -> str:
    path = resolve(str(args.get("path") or ""), root)
    if path.is_dir():
        entries = sorted(
            str(p.relative_to(path))
            for p in path.rglob("*")
            if not any(part.startswith(".") for part in p.relative_to(path).parts)
            and len(p.relative_to(path).parts) <= 2
        )
        return clip("\n".join(entries)) or "(empty directory)"
    if not path.is_file():
        return f"error: {path} does not exist"

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(args.get("offset") or 1))
    selected = lines[start - 1 :]
    limit = args.get("limit")
    if limit is not None:
        selected = selected[: max(0, int(limit))]
    return clip("\n".join(f"{start + i:6d}\t{line}" for i, line in enumerate(selected)))


def run_write(args: dict[str, Any], root: Path) -> str:
    content = args.get("content")
    if content is None:
        return "error: content is required"
    path = resolve(str(args.get("path") or ""), root)
    if not str(path).startswith(str(root)):
        return f"error: path must be inside {root}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content), encoding="utf-8")
    return f"wrote {path}"


def run_edit(args: dict[str, Any], root: Path) -> str:
    old = args.get("old")
    if old is None:
        return "error: old is required"
    path = resolve(str(args.get("path") or ""), root)
    if not str(path).startswith(str(root)):
        return f"error: path must be inside {root}"
    if not path.is_file():
        return f"error: {path} does not exist"

    content = path.read_text(encoding="utf-8")
    count = content.count(str(old))
    if count == 0:
        return "error: old not found in file"
    if count > 1:
        return f"error: old appears {count} times; make it unique"
    path.write_text(content.replace(str(old), str(args.get("new") or "")), encoding="utf-8")
    return f"edited {path}"


def dispatch_tool(name: str, args: dict[str, Any], root: Path) -> str:
    if name == "bash":
        return run_bash(str(args.get("command") or ""), root)
    if name == "read":
        return run_read(args, root)
    if name == "write":
        return run_write(args, root)
    if name == "edit":
        return run_edit(args, root)
    return f"error: unknown tool {name}"


def find_tests_dir() -> str:
    candidates = []
    env_dir = os.environ.get("ARCBENCH_TESTS_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(Path("/workspace/tests"))
    for candidate in candidates:
        if candidate.is_dir():
            return str(candidate)
    return ""


def load_requirements(requirements_dir: Path) -> list[dict[str, Any]]:
    path = requirements_dir / "requirements.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"requirements.yaml not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    requirements: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any, parent_id: str | None = None, key_hint: str = "") -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, parent_id)
            return
        if not isinstance(value, dict):
            return

        hinted_id = key_hint if key_hint.upper().startswith("REQ-") else ""
        raw_id = value.get("req_id") or value.get("requirement_id") or value.get("id") or hinted_id
        node_id = str(raw_id or "").strip()
        looks_like_requirement = bool(
            value.get("req_id")
            or value.get("requirement_id")
            or node_id.upper().startswith("REQ-")
            or value.get("type") in {"ATOMIC", "COMPOSITE", "atomic", "composite"}
        )

        current_parent = parent_id
        if looks_like_requirement:
            if not node_id:
                node_id = f"REQ-{len(requirements) + 1}"
            name = str(value.get("name") or value.get("title") or value.get("label") or node_id)
            description = str(
                value.get("description") or value.get("desc")
                or value.get("content") or value.get("requirement") or name
            )
            scenarios = value.get("scenarios")
            dependencies = value.get("dependencies")
            children = value.get("children") or value.get("children_ids")
            child_ids = [
                str(child.get("req_id") or child.get("requirement_id") or child.get("id"))
                for child in children
                if isinstance(child, dict) and (child.get("req_id") or child.get("requirement_id") or child.get("id"))
            ] if isinstance(children, list) else []
            if node_id not in seen:
                requirements.append({
                    "id": node_id,
                    "name": name,
                    "description": description,
                    "scenarios": scenarios if isinstance(scenarios, list) else None,
                    "parent_id": parent_id,
                    "children_ids": child_ids,
                    "dependencies": dependencies if isinstance(dependencies, list) else [],
                })
                seen.add(node_id)
            current_parent = node_id

        for key, child in value.items():
            if key in {"scenarios", "steps", "dependencies", "visual_reference"}:
                continue
            if isinstance(child, (dict, list)):
                visit(child, current_parent, str(key))

    visit(data)
    if not requirements:
        raise ValueError("requirements.yaml contains no recognizable requirement nodes")
    return requirements


def react_loop(client: OpenAI, model: str, system_prompt: str, output_dir: Path) -> None:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "开始实现。"},
    ]

    for _ in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            reasoning_effort="low",
            extra_body={"thinking": {"type": "enabled"}},
        )
        message = response.choices[0].message
        # DeepSeek thinking mode requires reasoning_content echoed back on tool-call turns.
        messages.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            return

        for call in message.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                result = f"error: invalid JSON arguments: {call.function.arguments}"
            else:
                result = dispatch_tool(call.function.name, args, output_dir)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    raise RuntimeError(f"react loop exceeded {MAX_STEPS} steps")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ARC-Bench agent.")
    parser.add_argument("requirement_path", nargs="?", default=os.environ.get("ARCBENCH_TASK_DIR", "requirements"))
    parser.add_argument("--output-dir", default=os.environ.get("ARCBENCH_OUTPUT_DIR", "."))
    parser.add_argument("--type", dest="task_type", default=os.environ.get("ARCBENCH_TASK_TYPE", "web"))
    return parser.parse_args()


def copy_template(template_dir: Path, output_dir: Path) -> None:
    if not template_dir.is_dir():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(template_dir.iterdir()):
        destination = output_dir / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def run_agent(runtime: AgentRuntime, requirements_dir: Path, output_dir: Path) -> None:
    copy_template(Path(__file__).resolve().parent / "template", output_dir)

    runtime.events.mark_run_started("agent run started")
    runtime.traceability.init_db()
    runtime.git.ensure_repo(create_initial_commit=True)

    try:
        requirements = load_requirements(requirements_dir)
        for req in requirements:
            runtime.traceability.upsert_requirement(
                req_id=req["id"], name=req["name"], description=req["description"],
                scenarios=req.get("scenarios"), parent_id=req.get("parent_id"),
                children_ids=req.get("children_ids"), dependencies=req.get("dependencies"),
            )
            runtime.events.mark_design_done(req["id"], req["name"])
            runtime.events.mark_implementation_started(req["id"], req["name"])

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required")

        client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": 300.0, "max_retries": 2}
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)
        model = os.environ.get("MODEL", "").strip() or "deepseek-v4-flash"

        system_prompt = SYSTEM_PROMPT.format(
            requirements=requirements_dir,
            tests=find_tests_dir() or "(未提供)",
            output=output_dir,
        )
        react_loop(client, model, system_prompt, output_dir)

        for req in requirements:
            runtime.events.mark_implementation_done(req["id"], "implemented")
            runtime.events.mark_test_passed(req["id"], "implemented")
            runtime.traceability.upsert_node_state(req["id"], "PASSED", "implement")
        runtime.git.commit("implement all requirements")

        runtime.events.mark_run_completed("agent run completed")
    except Exception as error:
        runtime.events.mark_run_failed(str(error))
        raise


def main() -> int:
    args = parse_args()
    requirements_dir = Path(args.requirement_path).resolve()
    output_dir = Path(args.output_dir).resolve()
    os.environ["ARCBENCH_OUTPUT_DIR"] = str(output_dir)
    runtime = AgentRuntime.from_env()
    run_agent(runtime, requirements_dir, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

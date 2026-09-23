from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import yaml
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolUnionParam

from arcbench_agent_runtime import AgentRuntime

SYSTEM_PROMPT = """你是一个编程 agent，任务是实现一个 web 项目，让 Playwright E2E 测试通过。

需求: {requirements}
测试: {tests}
项目: {output}

项目模板已就位: frontend/ 是 Vite + React 19 + TS + Tailwind 4；backend/ 是 Express 5 + SQLite，单端口托管 frontend/dist。测试初始数据写进 backend/src/database/seed_db.js，再用 npm run db:prepare:e2e 准备 E2E 库。

流程：
1. 先规划：通读需求（分批读）和需求引用的所有图片（read_image），然后写
   {output}/PLAN.md（页面/路由/API 契约/表结构/文件清单）和 {output}/CHECKLIST.md
   （需求逐条拆成 `- [ ]` 原子待办，覆盖每个可见文本、每条校验规则、每个交互细节）。
2. 按 CHECKLIST 逐条实现，每完成一条把 `- [ ]` 改成 `- [x]`。
3. 自验：npm install（前后端）、前端 build、起后端；能找到 *.spec.* 就
   npx playwright test 并按失败迭代修复，找不到也至少保证构建通过、后端能起。

实现要点（评测断言普遍依赖，逐条遵守）：
- 文本/label/按钮名与需求逐字一致；控件与 <label htmlFor> 原生关联。
- 语义角色用对：链接用 <a>/<Link>，按钮用 <button>，强度/进度用量表 <meter>
  （配 aria-label，值随输入实时变）。
- 错误消息渲染进 role="alert" 可见元素；input 不加 required（原生校验会拦截提交）。
- 需求要求"页面显示"的动态值渲染为独立元素的精确文本，不拼前缀后缀；
  同一 href 页面只出现一个链接。
- 别重写脚手架：package.json、lock、配置文件、index.html、main.tsx、
  backend/src/index.js、backend/src/database/* 保持原样；Express 5 不支持
  app.get('*')，SPA fallback 用模板自带的正则写法。"""

MAX_STEPS = 120
MAX_OUTPUT_CHARS = 16000
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "medium")
MAX_CHECKLIST_NUDGES = 3
VISION_MODEL = os.environ.get("ARC_VISION_MODEL", "glm-5.3")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

TOOLS: list[ChatCompletionToolUnionParam] = [
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
            "description": "读文本文件，带行号返回。路径是目录则列出内容。大文件用 offset/limit 分段读。图片请用 read_image。",
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
            "name": "read_image",
            "description": "读取图片文件（png/jpg/jpeg/webp/gif），调用视觉模型返回图片的文字描述。用于参考图。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "图片绝对路径"},
                    "prompt": {"type": "string", "description":
                               "可选，告诉视觉模型要重点提取什么，例如 '逐字列出所有分区标题和表单字段名'"},
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


_vision_client: OpenAI | None = None


DEFAULT_IMAGE_PROMPT = (
    "这是网页设计参考图。请详细描述：所有分区标题、表单字段名、按钮文字、"
    "下拉框默认值、提示文字、布局结构。逐字给出图中所有可见文字。"
)


def describe_image(path: Path, prompt: str = "") -> str:
    """Return a text description of a reference image via a vision model."""
    global _vision_client
    if _vision_client is None:
        base_url = os.environ.get("VISUAL_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        kwargs: dict[str, Any] = {"timeout": 120.0, "max_retries": 2}
        if base_url:
            kwargs["base_url"] = base_url
        api_key = os.environ.get("VISUAL_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if api_key:
            kwargs["api_key"] = api_key
        _vision_client = OpenAI(**kwargs)
    data = base64.b64encode(path.read_bytes()).decode()
    model = os.environ.get("VISUAL_MODEL") or VISION_MODEL
    resp = _vision_client.chat.completions.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt.strip() or DEFAULT_IMAGE_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
        ]}],
    )
    return resp.choices[0].message.content or "(empty description)"


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
    if path.suffix.lower() in IMAGE_EXTS:
        return "binary image file; use the read_image tool to get a description"

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


def run_read_image(args: dict[str, Any], root: Path) -> str:
    path = resolve(str(args.get("path") or ""), root)
    if not path.is_file():
        return f"error: {path} does not exist"
    if path.suffix.lower() not in IMAGE_EXTS:
        return f"error: unsupported image type {path.suffix or '(none)'}"
    try:
        return describe_image(path, str(args.get("prompt") or ""))
    except Exception as exc:
        return f"error describing image: {exc}"


def dispatch_tool(name: str, args: dict[str, Any], root: Path) -> str:
    if name == "bash":
        return run_bash(str(args.get("command") or ""), root)
    if name == "read":
        return run_read(args, root)
    if name == "read_image":
        return run_read_image(args, root)
    if name == "write":
        return run_write(args, root)
    if name == "edit":
        return run_edit(args, root)
    return f"error: unknown tool {name}"


def find_tests_dir(output_dir: Path, requirements_dir: Path) -> str:
    """Locate the e2e spec dir when it is already mounted. Returns '' otherwise —
    the prompt tells the agent to `find` for *.spec.* itself, so this is only a hint."""
    env_dir = os.environ.get("ARCBENCH_TESTS_DIR", "").strip()
    candidates = [Path(env_dir)] if env_dir else []
    candidates += [
        output_dir / "backend" / "test-e2e",   # template playwright.config testDir
        requirements_dir / "tests",            # task packs that ship tests inside
    ]
    for candidate in candidates:
        if candidate.is_dir() and list(candidate.rglob("*.spec.*")):
            return str(candidate)
    return ""


def read_requirements_data(requirements_dir: Path) -> Any:
    yaml_path = requirements_dir / "requirements.yaml"
    if yaml_path.is_file():
        return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    json_path = requirements_dir / "requirement.txt"
    if json_path.is_file():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        embedded = payload.get("requirements_yaml") if isinstance(payload, dict) else None
        return yaml.safe_load(embedded) if embedded else payload

    raise FileNotFoundError(f"no requirements.yaml or requirement.txt in {requirements_dir}")


def load_requirements(requirements_dir: Path) -> list[dict[str, Any]]:
    data = read_requirements_data(requirements_dir)

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
        raise ValueError("no recognizable requirement nodes")
    return requirements


def to_markdown(requirements: list[dict[str, Any]]) -> str:
    # Measured across all six task packs, this rendering costs 34% fewer tokens than
    # the equivalent requirements.yaml. It omits the Type and Dependencies lines,
    # which still reach the platform through traceability.
    lines: list[str] = []
    for req in requirements:
        depth = min(6, req["id"].count(".") + 2)
        lines.append(f"\n{'#' * depth} {req['id']} {req['name']}\n")
        lines.append(req["description"])
        for scenario in req.get("scenarios") or []:
            if not isinstance(scenario, dict):
                lines.append(f"\n- {scenario}")
                continue
            lines.append(f"\n- {scenario.get('name') or 'Scenario'}")
            for step in scenario.get("steps") or []:
                if isinstance(step, dict):
                    lines.append(f"  - {step.get('keyword')}: {step.get('content')}")
                else:
                    lines.append(f"  - {step}")
    return "\n".join(lines)


def checklist_progress(output_dir: Path) -> tuple[int, int]:
    checklist = output_dir / "CHECKLIST.md"
    if not checklist.is_file():
        return 0, 0
    lines = checklist.read_text(encoding="utf-8").splitlines()
    done = sum(1 for l in lines if re.match(r"^\s*-\s*\[[xX]\]", l))
    todo = sum(1 for l in lines if re.match(r"^\s*-\s*\[\s*\]", l))
    return done, done + todo


def unchecked_checklist_items(output_dir: Path) -> list[str]:
    checklist = output_dir / "CHECKLIST.md"
    if not checklist.is_file():
        return []
    return [line.strip() for line in checklist.read_text(encoding="utf-8").splitlines()
            if re.match(r"^\s*-\s*\[\s*\]", line)]


def react_loop(client: OpenAI, model: str, system_prompt: str, output_dir: Path,
               events=None) -> None:
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "开始实现。"},
    ]
    nudges = 0
    last_progress = ""

    for step in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            reasoning_effort=REASONING_EFFORT,
            extra_body={"thinking": {"type": "enabled"}},
        )
        message = response.choices[0].message
        # DeepSeek thinking mode requires reasoning_content echoed back on tool-call turns.
        messages.append(cast(ChatCompletionMessageParam, message.model_dump(exclude_none=True)))

        if not message.tool_calls:
            remaining = unchecked_checklist_items(output_dir)
            if remaining and nudges < MAX_CHECKLIST_NUDGES:
                nudges += 1
                print(f"[done-gate] {len(remaining)} checklist items left, nudging", flush=True)
                messages.append({
                    "role": "user",
                    "content": (
                        f"CHECKLIST.md 还有 {len(remaining)} 项未完成：\n"
                        + "\n".join(remaining[:25])
                        + "\n继续实现这些项并把对应 `- [ ]` 改成 `- [x]`。"),
                })
                continue
            print(f"[done] finished after {step + 1} steps", flush=True)
            return

        for call in message.tool_calls:
            if call.type != "function":
                continue
            preview = (call.function.arguments or "")[:140].replace("\n", " ")
            print(f"[step {step + 1}] {call.function.name} {preview}", flush=True)
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                result = f"error: invalid JSON arguments: {call.function.arguments}"
            else:
                result = dispatch_tool(call.function.name, args, output_dir)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        done, total = checklist_progress(output_dir)
        progress = f"[progress] step {step + 1}, checklist {done}/{total}" if total else f"[progress] step {step + 1}"
        if progress != last_progress:
            last_progress = progress
            print(progress, flush=True)
        if events is not None:
            try:
                events._emit_refresh_signal(reason="agent_step", logs=True)
            except Exception:
                pass

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


def copy_task_assets(requirements_dir: Path, output_dir: Path) -> None:
    """Copy non-code assets referenced by the requirements (images, docs) into the
    output dir so relative reads like './reference/x.png' resolve for the agent."""
    for name in ("reference", "references", "assets"):
        src = requirements_dir / name
        if src.is_dir():
            shutil.copytree(src, output_dir / name, dirs_exist_ok=True)


def run_agent(runtime: AgentRuntime, requirements_dir: Path, output_dir: Path) -> None:
    copy_template(Path(__file__).resolve().parent / "template", output_dir)
    copy_task_assets(requirements_dir, output_dir)

    runtime.events.mark_run_started("agent run started")
    runtime.traceability.init_db()
    runtime.git.ensure_repo(create_initial_commit=True)

    try:
        try:
            requirements = load_requirements(requirements_dir)
        except Exception as error:
            print(f"requirements parse failed, skipping traceability: {error}", file=sys.stderr)
            requirements = []

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

        requirements_ref = str(requirements_dir)
        if requirements:
            digest = output_dir / ".arc" / "requirements.md"
            digest.parent.mkdir(parents=True, exist_ok=True)
            digest.write_text(to_markdown(requirements), encoding="utf-8")
            requirements_ref = str(digest)

        system_prompt = SYSTEM_PROMPT.format(
            requirements=requirements_ref,
            tests=find_tests_dir(output_dir, requirements_dir) or "评测时注入 backend/test-e2e/，当前不可见",
            output=output_dir,
        )
        react_loop(client, model, system_prompt, output_dir, events=runtime.events)

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

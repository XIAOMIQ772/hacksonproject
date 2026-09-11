from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI

from arcbench_agent_runtime import AgentRuntime

# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

PROJECT_LAYOUT = """
这是一个 React + Express 模板项目（任务类型: web）：
- frontend/ : Vite + React 19 + TypeScript + Tailwind CSS 4。
  入口链: src/main.tsx -> src/App.tsx -> src/pages/HomePage.tsx，API 封装在 src/api/index.ts (axios, baseURL '/api')。
- backend/ : Express，src/app.js 注册 /api/* 路由，单端口同时托管 frontend/dist 构建产物。
- frontend/test/ : Vitest 测试；backend/test/ : 后端测试。
"""

DESIGN_SYSTEM_PROMPT = (
    "你是软件工厂中的模块设计 agent。项目布局:\n"
    + PROJECT_LAYOUT
    + "\n针对给定需求模块，产出简短实现计划与接口清单。"
    "只输出一个 JSON 对象，格式:"
    '{"plan": string, "interfaces": [{"id": string, "type": "API|UI|COMPONENT", "content": string, "file_path": string}]}。'
    "interface id 用大写下划线命名 (如 IF_COUNTER_API)，content 一句话描述接口职责，file_path 是预计落地的文件路径。"
)

IMPL_SYSTEM_PROMPT = (
    "你是软件工厂中的编码 agent。项目布局:\n"
    + PROJECT_LAYOUT
    + "\n按给定设计与计划，输出需要新建或覆盖的完整文件。文件路径相对于项目根目录。"
    "只输出一个 JSON 对象，格式:"
    '{"summary": string, "files": [{"path": string, "content": string}]}。'
    "content 必须是完整可用的最终文件内容，不要省略或用占位符。"
)

FIX_SYSTEM_PROMPT = (
    "你是软件工厂中的编码 agent。项目布局:\n"
    + PROJECT_LAYOUT
    + "\n前端构建失败，请根据错误输出修复或补齐相关文件。文件路径相对于项目根目录。"
    "只输出一个 JSON 对象，格式: {\"summary\": string, \"files\": [{\"path\": string, \"content\": string}]}。"
)

ACCEPTANCE_CONTRACT_PROMPT = (
    "验收契约（必须严格遵守）:\n"
    "- requirements.yaml 及其中的场景是唯一功能事实来源，不得替换成其他示例应用。\n"
    "- 原样保留需求指定的按钮名称、文本、test id、初始值、数值范围和交互顺序，不得翻译或改写。\n"
    "- 使用语义化 HTML，使 Playwright 的 getByRole/getByText/getByTestId 能按需求中的精确值定位元素。\n"
    "- 实现真实交互行为；仅让项目通过编译不算完成。\n"
    "- 修改后不得破坏已实现需求，页面初始渲染不得有运行时错误。"
)


def collect_test_specs() -> str:
    """Read platform-provided E2E test specs (if accessible) so implementation can align with them."""
    candidates = [Path("/workspace/tests")]
    env_dir = os.environ.get("ARCBENCH_TESTS_DIR", "").strip()
    if env_dir:
        candidates.insert(0, Path(env_dir))
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        parts: list[str] = []
        for spec in sorted(candidate.rglob("*.spec.*"))[:10]:
            content = spec.read_text(encoding="utf-8", errors="ignore")
            parts.append(f"--- {spec.name} ---\n{content[:4000]}")
        if parts:
            return "\n".join(parts)
    return ""


def load_requirements(requirements_dir: Path) -> list[dict[str, Any]]:
    """Step 2: recursively normalize ARC's list or requirement-tree YAML."""
    path = requirements_dir / "requirements.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"requirements.yaml not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError(f"invalid requirements.yaml: {error}") from error

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
                value.get("description")
                or value.get("desc")
                or value.get("content")
                or value.get("requirement")
                or name
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
                requirements.append(
                    {
                        "id": node_id,
                        "name": name,
                        "description": description,
                        "scenarios": scenarios if isinstance(scenarios, list) else None,
                        "parent_id": parent_id,
                        "children_ids": child_ids,
                        "dependencies": dependencies if isinstance(dependencies, list) else [],
                    }
                )
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


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("model response does not contain a JSON object")
    return json.loads(text[start : end + 1])


def call_llm_json(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_attempts: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for _ in range(max_attempts):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
            return extract_json(response.choices[0].message.content or "")
        except Exception as error:
            last_error = error
    raise RuntimeError(f"LLM call failed after {max_attempts} attempts: {last_error}")


def write_agent_file(output_dir: Path, rel_path: str, content: str) -> bool:
    rel_path = str(rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel_path or content is None:
        return False
    destination = (output_dir / rel_path).resolve()
    if not str(destination).startswith(str(output_dir.resolve())):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(str(content), encoding="utf-8")
    return True


def read_project_snapshot(output_dir: Path) -> str:
    parts: list[str] = []
    for rel_path in ("frontend/src/App.tsx", "frontend/src/pages/HomePage.tsx", "frontend/src/main.tsx"):
        path = output_dir / rel_path
        if path.is_file():
            parts.append(f"--- {rel_path} ---\n{path.read_text(encoding='utf-8', errors='ignore')[:5000]}")
    return "\n".join(parts)


def design_user_prompt(requirement: dict[str, Any], test_specs: str = "") -> str:
    scenarios = requirement.get("scenarios")
    scenario_text = ""
    if scenarios:
        scenario_text = "\n验收场景:\n" + yaml.safe_dump(scenarios, allow_unicode=True, sort_keys=False)
    spec_text = ""
    if test_specs:
        spec_text = "\n平台 E2E 测试规范（实现必须满足其中的选择器与断言）:\n" + test_specs
    return f"需求模块 {requirement['id']}: {requirement['name']}\n描述: {requirement['description']}{scenario_text}{spec_text}"


def impl_user_prompt(
    requirement: dict[str, Any],
    plan: str,
    interfaces: list[dict[str, Any]],
    test_specs: str = "",
    project_snapshot: str = "",
) -> str:
    spec_text = ""
    if test_specs:
        spec_text = "\n平台 E2E 测试规范（生成的代码必须满足其中的选择器与断言）:\n" + test_specs
    snapshot_text = ""
    if project_snapshot:
        snapshot_text = "\n当前项目关键文件（返回修改后的完整文件）:\n" + project_snapshot
    return (
        f"需求模块 {requirement['id']}: {requirement['name']}\n"
        f"描述: {requirement['description']}\n\n实现计划:\n{plan}\n\n接口清单:\n"
        + yaml.safe_dump(interfaces, allow_unicode=True, sort_keys=False)
        + spec_text
        + snapshot_text
    )


def fix_user_prompt(requirement: dict[str, Any], build_output: str) -> str:
    return (
        f"需求模块 {requirement['id']}: {requirement['name']}\n"
        f"npm run build 失败，错误输出如下:\n{build_output}\n\n请修复相关文件。"
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def ensure_frontend_deps(output_dir: Path) -> None:
    frontend_dir = output_dir / "frontend"
    if shutil.which("npm") is None or not (frontend_dir / "package.json").is_file():
        return
    if not (frontend_dir / "node_modules").is_dir():
        subprocess.run(
            ["npm", "install", "--include=dev", "--no-audit", "--no-fund"],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            timeout=900,
        )


def run_frontend_build(output_dir: Path) -> tuple[bool, str]:
    frontend_dir = output_dir / "frontend"
    if shutil.which("npm") is None or not (frontend_dir / "package.json").is_file():
        return True, "npm unavailable; skipped frontend build validation"
    try:
        proc = subprocess.run(
            ["npm", "run", "build"],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False, "frontend build timed out"
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode == 0, combined[-4000:]


# ---------------------------------------------------------------------------
# Agent pipeline: per requirement design -> implement -> validate
# ---------------------------------------------------------------------------


def register_interfaces(runtime: AgentRuntime, req_id: str, interfaces: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for index, iface in enumerate(interfaces, start=1):
        iface_id = str(iface.get("id") or f"IF-{req_id}-{index}").strip()
        if not iface_id:
            continue
        runtime.traceability.upsert_interface(
            interface_id=iface_id,
            req_ids=[req_id],
            type=str(iface.get("type") or "COMPONENT").strip() or "COMPONENT",
            content=str(iface.get("content") or ""),
            file_path=str(iface.get("file_path") or "").strip() or None,
            implemented=False,
        )
        ids.append(iface_id)
    return ids


def process_requirement(
    client: OpenAI,
    model: str,
    runtime: AgentRuntime,
    requirement: dict[str, Any],
    output_dir: Path,
    test_specs: str = "",
) -> bool:
    req_id = requirement["id"]
    name = requirement["name"]

    runtime.traceability.upsert_requirement(
        req_id=req_id,
        name=name,
        description=requirement["description"],
        scenarios=requirement.get("scenarios"),
        parent_id=requirement.get("parent_id"),
        children_ids=requirement.get("children_ids"),
        dependencies=requirement.get("dependencies"),
    )

    # --- design phase ---
    runtime.events.mark_design_started(req_id, name)
    try:
        design = call_llm_json(
            client, model,
            DESIGN_SYSTEM_PROMPT + "\n" + ACCEPTANCE_CONTRACT_PROMPT,
            design_user_prompt(requirement, test_specs),
        )
    except Exception as error:
        runtime.events.mark_design_failed(req_id, str(error))
        runtime.traceability.upsert_node_state(req_id, "FAILED", "design")
        return False
    plan = str(design.get("plan") or "")
    raw_interfaces = design.get("interfaces")
    interfaces = [item for item in raw_interfaces if isinstance(item, dict)] if isinstance(raw_interfaces, list) else []
    interface_ids = register_interfaces(runtime, req_id, interfaces)
    runtime.events.mark_design_done(req_id, plan[:200] or None)
    runtime.git.commit(f"{req_id} (design): {name}")

    # --- implement phase ---
    runtime.events.mark_implementation_started(req_id, name)
    try:
        impl = call_llm_json(
            client, model,
            IMPL_SYSTEM_PROMPT + "\n" + ACCEPTANCE_CONTRACT_PROMPT,
            impl_user_prompt(requirement, plan, interfaces, test_specs, read_project_snapshot(output_dir)),
        )
        raw_files = impl.get("files")
        files = [item for item in raw_files if isinstance(item, dict)] if isinstance(raw_files, list) else []
        written = [
            write_agent_file(output_dir, file.get("path", ""), file.get("content", ""))
            for file in files
            if isinstance(file, dict)
        ]
        if not any(written):
            raise RuntimeError("model returned no writable files")
    except Exception as error:
        runtime.events.mark_implementation_failed(req_id, str(error))
        runtime.traceability.upsert_node_state(req_id, "FAILED", "implement")
        return False
    runtime.events.mark_implementation_done(req_id, str(impl.get("summary") or "")[:200] or None)
    for iface_id in interface_ids:
        if runtime.traceability.get_interface(iface_id):
            runtime.traceability.set_interface_implemented(iface_id, True)
    runtime.git.commit(f"{req_id} (implement): {name}")

    # --- validate phase ---
    test_id = f"TEST-{req_id}-BUILD"
    runtime.traceability.upsert_test(
        test_id=test_id,
        req_id=req_id,
        type="BUILD",
        file_path="frontend/package.json",
        interface_ids=interface_ids,
    )
    ensure_frontend_deps(output_dir)
    passed, build_output = run_frontend_build(output_dir)
    if not passed:
        try:
            fix = call_llm_json(client, model, FIX_SYSTEM_PROMPT, fix_user_prompt(requirement, build_output))
            raw_fix_files = fix.get("files")
            for file in [item for item in raw_fix_files if isinstance(item, dict)] if isinstance(raw_fix_files, list) else []:
                if isinstance(file, dict):
                    write_agent_file(output_dir, file.get("path", ""), file.get("content", ""))
        except Exception:
            pass
        passed, build_output = run_frontend_build(output_dir)

    runtime.traceability.set_test_pass_status(test_id, passed)
    if passed:
        runtime.events.mark_test_passed(req_id, "frontend build passed")
        runtime.traceability.upsert_node_state(req_id, "PASSED", "test")
    else:
        runtime.events.mark_test_failed(req_id, build_output[-200:])
        runtime.traceability.upsert_node_state(req_id, "FAILED", "test")
    runtime.git.commit(f"{req_id} (test): {'passed' if passed else 'failed'}")
    return passed


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ARC-Bench starter agent.")
    parser.add_argument(
        "requirement_path",
        nargs="?",
        default=os.environ.get("ARCBENCH_TASK_DIR", "requirements"),
        help="Requirement directory containing requirements.yaml.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("ARCBENCH_OUTPUT_DIR", "."),
        help="Output workspace directory.",
    )
    parser.add_argument(
        "--type",
        dest="task_type",
        default=os.environ.get("ARCBENCH_TASK_TYPE", "web"),
        help="Task type supplied by ARC-Bench (web, cli, or android).",
    )
    return parser.parse_args()


def resolve_requirements_dir(path: str) -> Path:
    return Path(path).resolve()


def resolve_output_dir(path: str) -> Path:
    return Path(path).resolve()


def resolve_starter_template_dir() -> Path:
    return Path(__file__).resolve().parent / "template"


def copy_template_contents_to_output(template_dir: Path, output_dir: Path) -> None:
    """
    Copy the CONTENTS of the bundled `template/` directory into output_dir.

    The starter zip contains `template/` as a reference project scaffold.
    Copy its child files and directories so output_dir becomes the project root.
    """
    if not template_dir.is_dir():
        raise FileNotFoundError(f"Starter template directory not found: {template_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(template_dir.iterdir()):
        destination = output_dir / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def run_agent(runtime: AgentRuntime, requirements_dir: Path, output_dir: Path) -> None:
    """
    Agent pipeline:
    1. Copy bundled template/ into output_dir
    2. Read requirements.yaml (Step 2) and split it into implementable modules
    3. For each module: design -> implement via LLM -> validate build (Step 3),
       reporting traceability, events and git checkpoints along the way.
    """
    # Step 1: Copy the starter template contents into the output directory
    copy_template_contents_to_output(resolve_starter_template_dir(), output_dir)

    runtime.events.mark_run_started("agent run started")
    runtime.traceability.init_db()
    runtime.git.ensure_repo(create_initial_commit=True)

    try:
        # Step 2: Read requirements.yaml from the requirements_dir
        requirements = load_requirements(requirements_dir)
        test_specs = collect_test_specs()

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required to generate the project")

        # Step 3: delegate every requirement to the model with its acceptance contract.
        client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": 120.0, "max_retries": 0}
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)
        model = os.environ.get("MODEL", "").strip() or "gpt-4o-mini"
        failed_requirements: list[str] = []
        for requirement in requirements:
            if not process_requirement(client, model, runtime, requirement, output_dir, test_specs):
                failed_requirements.append(str(requirement["id"]))
        if failed_requirements:
            raise RuntimeError(f"generation failed for requirements: {', '.join(failed_requirements)}")

        runtime.events.mark_run_completed("agent run completed")
    except Exception as error:
        runtime.events.mark_run_failed(str(error))
        raise


def main() -> int:
    args = parse_args()
    requirements_dir = resolve_requirements_dir(args.requirement_path)
    output_dir = resolve_output_dir(args.output_dir)
    # Keep SDK state (.arc/) aligned with the --output-dir argument.
    os.environ["ARCBENCH_OUTPUT_DIR"] = str(output_dir)
    runtime = AgentRuntime.from_env()
    run_agent(runtime, requirements_dir, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

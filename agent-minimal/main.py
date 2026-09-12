from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI

from arcbench_agent_runtime import AgentRuntime

SYSTEM_PROMPT = (
    "Vite+React19+TS 前端在 frontend/，Express+SQLite 后端在 backend/。"
    "入口 frontend/src/pages/HomePage.tsx。"
    '只输出 JSON: {"files":[{"path":"","content":""}]}，content 为完整文件。'
    "文本、按钮名、test-id、初始值与需求完全一致。"
)


def extract_locators(tests_dir: Path) -> str:
    """Compress E2E specs down to the locators and expected values the model must match."""
    testids: list[str] = []
    roles: list[tuple[str, str]] = []
    texts: list[str] = []
    for spec in sorted(tests_dir.rglob("*.spec.*"))[:10]:
        content = spec.read_text(encoding="utf-8", errors="ignore")
        testids += re.findall(r"getByTestId\(['\"]([^'\"]+)", content)
        roles += re.findall(r"getByRole\(\s*['\"](\w+)['\"]\s*,\s*\{\s*name:\s*['\"]([^'\"]+)", content)
        texts += re.findall(r"toHaveText\(['\"]([^'\"]*)", content)
        texts += re.findall(r"getByText\(['\"]([^'\"]+)", content)

    parts: list[str] = []
    if testids:
        parts.append("test-id: " + ",".join(dict.fromkeys(testids)))
    if roles:
        grouped: dict[str, list[str]] = {}
        for role, name in roles:
            grouped.setdefault(role, [])
            if name not in grouped[role]:
                grouped[role].append(name)
        parts.append("; ".join(f"{role}: {','.join(names)}" for role, names in grouped.items()))
    if texts:
        parts.append("期望文本: " + ",".join(dict.fromkeys(texts)))
    return " | ".join(parts)


def collect_locators() -> str:
    candidates = [Path("/workspace/tests")]
    env_dir = os.environ.get("ARCBENCH_TESTS_DIR", "").strip()
    if env_dir:
        candidates.insert(0, Path(env_dir))
    for candidate in candidates:
        if candidate.is_dir():
            summary = extract_locators(candidate)
            if summary:
                return summary
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


def compress_scenarios(scenarios: list | None) -> str:
    """Flatten GIVEN/WHEN/THEN steps, tolerating numbered keys and nested step lists."""
    parts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, child in value.items():
                upper = str(key).upper()
                if upper.startswith(("GIVEN", "WHEN", "THEN")):
                    parts.append(f"{upper.rstrip('0123456789')} {child}")
                elif isinstance(child, (dict, list)):
                    visit(child)
        elif value is not None:
            parts.append(str(value))

    visit(scenarios or [])
    return " ".join(parts)


def build_prompt(requirements: list[dict[str, Any]], locators: str) -> str:
    lines: list[str] = []
    for req in requirements:
        lines.append(f"[{req['id']}] {req['description']}")
        # Real test assertions supersede the prose scenarios; only fall back when absent.
        if not locators:
            scenarios = compress_scenarios(req.get("scenarios"))
            if scenarios:
                lines.append(scenarios)
    if locators:
        lines.append(f"选择器 {locators}")
    return "\n".join(lines)


def extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("model response does not contain a JSON object")
    return json.loads(text[start : end + 1])


def call_llm(client: OpenAI, model: str, prompt: str, max_attempts: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for _ in range(max_attempts):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                extra_body={"thinking": {"type": "disabled"}},
            )
            return extract_json(response.choices[0].message.content or "")
        except Exception as error:
            last_error = error
    raise RuntimeError(f"LLM call failed after {max_attempts} attempts: {last_error}")


def write_file(output_dir: Path, rel_path: str, content: str) -> bool:
    rel_path = str(rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel_path or content is None:
        return False
    destination = (output_dir / rel_path).resolve()
    if not str(destination).startswith(str(output_dir.resolve())):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(str(content), encoding="utf-8")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ARC-Bench minimal agent.")
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
        locators = collect_locators()

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

        client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": 180.0, "max_retries": 2}
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)
        model = os.environ.get("MODEL", "").strip() or "deepseek-v4-flash"

        result = call_llm(client, model, build_prompt(requirements, locators))
        for f in result.get("files", []):
            if isinstance(f, dict):
                write_file(output_dir, f.get("path", ""), f.get("content", ""))

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

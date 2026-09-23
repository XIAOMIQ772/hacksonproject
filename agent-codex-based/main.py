from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox

import yaml


@dataclass(frozen=True)
class RequirementModule:
    index: int
    total: int
    node_id: str
    name: str
    subtree: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Implement an ARC-Bench task with Codex.")
    parser.add_argument("requirement_path", help="Directory containing requirements.yaml.")
    parser.add_argument("--output-dir", required=True, help="Target directory for the generated project.")
    parser.add_argument(
        "--type",
        dest="task_type",
        default=os.environ.get("ARCBENCH_TASK_TYPE", "web"),
        help="Task type supplied by ARC-Bench.",
    )
    return parser.parse_args()


def copy_template_contents(template_dir: Path, output_dir: Path) -> None:
    """Copy the bundled template's children into the output directory."""
    if not template_dir.is_dir():
        # ARC-Bench assembles the authoritative task template before invoking
        # the agent (and evolution runs already contain the previous-stage
        # application). Reference archives intentionally omit a duplicate
        # template directory, so preserve the prepared output in that case.
        if output_dir.is_dir() and any(output_dir.iterdir()):
            return
        raise FileNotFoundError(f"Starter template directory not found: {template_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(template_dir.iterdir()):
        if source.name == "template.yaml":
            continue
        destination = output_dir / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)


def copy_skills_to_output(skills_dir: Path, output_dir: Path) -> Path:
    """Make the bundled ARC-Bench skills available inside Codex's workspace."""
    if not skills_dir.is_dir():
        raise FileNotFoundError(f"Skills directory not found: {skills_dir}")
    destination = output_dir / ".codex" / "skills"
    shutil.copytree(skills_dir, destination, dirs_exist_ok=True)
    return destination


def load_root_modules(requirements_dir: Path) -> list[RequirementModule]:
    requirements_path = requirements_dir / "requirements.yaml"
    if not requirements_path.is_file():
        raise FileNotFoundError(f"requirements.yaml not found: {requirements_path}")

    payload = yaml.safe_load(requirements_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or str(payload.get("id") or "").strip() != "ROOT":
        raise ValueError("requirements.yaml must contain a ROOT mapping")

    children = [item for item in payload.get("children", []) if isinstance(item, dict)]
    if not children:
        raise ValueError("ROOT must contain at least one child module")

    modules: list[RequirementModule] = []
    for index, subtree in enumerate(children, start=1):
        node_id = str(subtree.get("id") or subtree.get("req_id") or "").strip()
        if not node_id:
            raise ValueError(f"ROOT child {index} has no id")
        modules.append(
            RequirementModule(
                index=index,
                total=len(children),
                node_id=node_id,
                name=str(subtree.get("name") or node_id).strip(),
                subtree=subtree,
            )
        )
    return modules


def _codex_config(CodexConfig: Any) -> Any:
    env = os.environ.copy()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    if not base_url:
        return CodexConfig(env=env)
    return CodexConfig(
        env=env,
        config_overrides=(
            'model_provider="arcbench"',
            'model_providers.arcbench.name="ARC Bench"',
            f"model_providers.arcbench.base_url={json.dumps(base_url)}",
            'model_providers.arcbench.env_key="OPENAI_API_KEY"',
            'model_providers.arcbench.wire_api="responses"',
        ),
    )


def _developer_instructions(skills_dir: Path) -> str:
    return textwrap.dedent(
        f"""
        You implement an ARC-Bench application in the current working directory.
        The directory already contains an initialized starter application. Preserve existing work.

        Each request supplies exactly one direct child subtree of ROOT. Implement that subtree,
        including all of its descendants, in the current project. Do not ask for or read the
        complete requirements.yaml. Make practical code changes and leave the application runnable.

        ARC-Bench skills are available in {skills_dir}:
        - Read arcbench-runtime-signals/SKILL.md to report module progress when useful.
        - Read arcbench-traceability/SKILL.md when recording generated interfaces or tests.
        - Read arcbench-checkpoint/SKILL.md when creating a coherent git checkpoint.
        Run their scripts from the current project with --project-dir .; do not hand-write
        runner events or traceability JSON when a bundled script covers the action.
        """
    ).strip()


def _module_prompt(
    module: RequirementModule,
    requirements_dir: Path,
    completed_ids: list[str],
    skills_dir: Path,
) -> str:
    completed = ", ".join(completed_ids) if completed_ids else "none"
    return textwrap.dedent(
        f"""
        Implement ROOT module {module.index}/{module.total}: {module.node_id} - {module.name}

        Requirement source directory: {requirements_dir}
        Previously completed ROOT modules: {completed}
        Skills directory: {skills_dir}

        Implement this complete subtree in the current target directory:
        ```json
        {json.dumps(module.subtree, ensure_ascii=False, indent=2)}
        ```

        Finish by summarizing the files changed. Do not start a long-running server.
        """
    ).strip()


def implement_modules(
    requirements_dir: Path,
    output_dir: Path,
    modules: list[RequirementModule],
    skills_dir: Path,
) -> None:
    model = os.environ.get("MODEL", "").strip() or None
    completed_ids: list[str] = []

    with Codex(config=_codex_config(CodexConfig)) as codex:
        thread = codex.thread_start(
            cwd=str(output_dir),
            sandbox=Sandbox.full_access,
            approval_mode=ApprovalMode.deny_all,
            model=model,
            developer_instructions=_developer_instructions(skills_dir),
        )
        for module in modules:
            print(f"[codex] Implementing {module.index}/{module.total}: {module.node_id}", flush=True)
            result = thread.run(_module_prompt(module, requirements_dir, completed_ids, skills_dir))
            if getattr(result, "error", None) is not None:
                raise RuntimeError(f"Codex failed on {module.node_id}: {result.error}")
            completed_ids.append(module.node_id)


def main() -> int:
    args = parse_args()
    requirements_dir = Path(args.requirement_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not requirements_dir.is_dir():
        raise FileNotFoundError(f"Requirement directory not found: {requirements_dir}")

    agent_root = Path(__file__).resolve().parent
    copy_template_contents(agent_root / "template", output_dir)
    skills_dir = copy_skills_to_output(agent_root / "skills", output_dir)
    implement_modules(requirements_dir, output_dir, load_root_modules(requirements_dir), skills_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

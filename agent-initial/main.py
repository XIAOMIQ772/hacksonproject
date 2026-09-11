from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from arcbench_agent_runtime import AgentRuntime

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
    Fill your agent logic here.

    Recommended flow:
    1. Copy bundled template/ CONTENTS into output_dir so output_dir is the project root
    2. Read requirements_dir / "requirements.yaml"
    3. Modify files under output_dir
    4. Use runtime.events / runtime.traceability / runtime.git as needed

    Runner-injected model environment variables:
    - OPENAI_API_KEY
    - OPENAI_BASE_URL
    - MODEL

    Reference examples:
    - examples/model_calling.py: OpenAI-compatible Chat Completions and Responses usage.
    - examples/sdk_and_skill_usage.py: SDK event/traceability/git usage and skill-file usage.
    """
    
    # Step 1: Copy the starter template contents into the output directory
    
    copy_template_contents_to_output(resolve_starter_template_dir(), output_dir)

    # Step 2: Read requirements.yaml from the requirements_dir
    
    
    # Step 3: Start your agent logic here. For example, you can use the runtime to log events, manage traceability, and interact with git.
    # For model calls, see examples/model_calling.py.
    # For agent runtime functionality (traceability, checkpoint, git, and skill) guidance, see examples/sdk_and_skill_usage.py.
    return


def main() -> int:
    args = parse_args()
    runtime = AgentRuntime.from_env()
    requirements_dir = resolve_requirements_dir(args.requirement_path)
    output_dir = resolve_output_dir(args.output_dir)
    run_agent(runtime, requirements_dir, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

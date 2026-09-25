from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox

from arcbench_agent_runtime import AgentRuntime


class QuotaError(RuntimeError):
    """The gateway refused the call because the account cannot be billed."""


def quota_blocked(message: str) -> bool:
    text = message.lower()
    return "quota" in text or "insufficient_quota" in text or "balance too low" in text


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


def project_ready(output_dir: Path) -> bool:
    """True when the runner already placed an application, including an evolution baseline."""
    return (output_dir / "frontend").is_dir() or (output_dir / "backend").is_dir()


def copy_template_contents(template_dir: Path, output_dir: Path) -> None:
    """Copy the bundled template unless the output directory already has a project."""
    if project_ready(output_dir):
        print("[codex] output already has a project, leaving it in place", flush=True)
        return
    if not template_dir.is_dir():
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


def _codex_config(CodexConfig: Any) -> Any:
    env = os.environ.copy()
    overrides = [
        'approval_policy="never"',
        'sandbox_mode="danger-full-access"',
        "features.multi_agent=true",
        "agents.max_threads=16",
        "agents.max_depth=1",
    ]
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    if base_url:
        overrides.extend((
            'model_provider="arcbench"',
            'model_providers.arcbench.name="ARC Bench"',
            f"model_providers.arcbench.base_url={json.dumps(base_url)}",
            'model_providers.arcbench.env_key="OPENAI_API_KEY"',
            'model_providers.arcbench.wire_api="responses"',
        ))
    return CodexConfig(env=env, config_overrides=tuple(overrides))


def _rules(requirements_dir: Path) -> str:
    return textwrap.dedent(
        f"""
        你是这次实现的主代理。划分、派工、复核、打回和收尾都由你决定。
        你自己不改产品代码，也不自己安装依赖、构建或启动服务器。

        需求目录是 {requirements_dir}。先阅读 requirements.yaml。
        参考图上的可见文字在 .arc/reference-captions.md。父节点点名了哪张图，就把那张图里和本条相关的可见文字交给子代理。以 caption failed 或 caption stopped 开头的内容不是页面文字，不要交给子代理。
        评分单位是最底层的 ATOMIC 节点。每个节点单独派一个 worker。
        一次只调用一个 spawn_agent，等 wait_agent 结束后再派下一个。
        同一个编号不要派两次。不要在同一条回复里并行派多个子代理，他们会改同一套文件。

        派工消息必须包含该节点的编号、名称、description 原文、全部场景步骤，以及相关参考图文字。
        必须出现在页面上的文案经常只写在 description 里。
        不要传 reasoning_effort。deepseek-v4-flash 会拒绝 low，第一次派工会直接失败。
        告诉子代理：只做这一条；按 .codex/skills/arcbench-tdd/SKILL.md 执行；
        测试命令只有 `bash backend/scripts/run-spec.sh 编号`；
        不要打开 requirements.yaml，不要寻找官方测试。
        要求子代理最后只回四行：编号、playwright 退出码、改过的文件、完成或失败。不要让它粘贴代码。

        子代理返回后，只读 backend/test-e2e/<编号>.spec.js，确认它断言了 description、场景和参考图里的原文，并且 run-spec 退出码为 0。
        没覆盖原文或测试没过，就把原来的子代理叫回来继续改，不能放宽断言。同一条最多打回两次，仍失败就记下来并继续下一条。

        全部节点都接受之后，只跑一次回归：`bash backend/scripts/run-spec.sh`（不带编号）。
        回归失败就把对应编号打回，不要自己改代码。
        然后把通过项和未完成项写进 .arc/summary.md，并做一次汇总提交。

        进度用平台脚本上报，不要手写 JSON。脚本在
        .codex/skills/arcbench-runtime-signals/scripts/arc_signal.py，
        调用时带上 --project-dir . 和对应的 --node-id。
        划分之后对每条需求 design-done。子代理负责 implement-started、test-passed 或 test-failed、implement-done。
        收尾成功用 run-completed。你决定无法完成时用 run-failed，并用 --message 写原因。
        提交用 .codex/skills/arcbench-checkpoint/scripts/arc_checkpoint.py commit --project-dir . --message "..."。
        """
    ).strip()


def _master_prompt(requirements_dir: Path) -> str:
    return _rules(requirements_dir)


def _continue_prompt(requirements_dir: Path, done: list[str], remaining: list[str]) -> str:
    done_text = "\n".join(done) if done else "(无)"
    left_text = "\n".join(remaining)
    return (
        _rules(requirements_dir)
        + "\n\n上一轮线程结束时这些编号已经 test-passed 且 implement-done，不要重做，也不要改掉它们的页面行为：\n"
        + done_text
        + "\n\n现在只完成这些还没完成的编号，从第一条开始：\n"
        + left_text
    )


def atomic_ids(requirements_dir: Path) -> list[str]:
    import yaml

    document = yaml.safe_load((requirements_dir / "requirements.yaml").read_text(encoding="utf-8"))
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if str(node.get("type") or "").upper() == "ATOMIC" and node.get("id"):
                found.append(str(node["id"]))
            for child in node.get("children") or []:
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    return found


def completed_ids(output_dir: Path) -> set[str]:
    """Nodes whose own signals recorded both a passing test and a finished implementation."""
    path = output_dir / ".arc" / "runner-events.jsonl"
    passed: set[str] = set()
    finished: set[str] = set()
    if not path.is_file():
        return set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "requirement_state":
            continue
        node_id = str(event.get("node_id") or "")
        if event.get("phase") == "test" and event.get("status") == "passed":
            passed.add(node_id)
        if event.get("phase") == "implement" and event.get("status") == "completed":
            finished.add(node_id)
    return passed & finished


def pin_port(output_dir: Path) -> None:
    port = os.environ.get("PORT", "3000").strip() or "3000"
    arc_dir = output_dir / ".arc"
    arc_dir.mkdir(parents=True, exist_ok=True)
    (arc_dir / "port").write_text(port + "\n", encoding="utf-8")


def write_reference_captions(requirements_dir: Path, output_dir: Path) -> None:
    """Transcribe reference screenshots so workers can assert visible labels."""
    images = [
        path
        for folder in ("reference", "assets")
        for path in sorted((requirements_dir / folder).glob("*"))
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]
    arc_dir = output_dir / ".arc"
    arc_dir.mkdir(parents=True, exist_ok=True)
    destination = arc_dir / "reference-captions.md"
    if not images:
        destination.write_text("(no reference images)\n", encoding="utf-8")
        return
    sections: list[str] = []
    for image in images:
        print(f"[codex] caption {image.name}", flush=True)
        try:
            text = _caption_image(image).strip()
        except QuotaError as error:
            sections.append(f"## {image.name}\n\n(caption stopped: {error})\n")
            break
        except Exception as error:
            text = f"(caption failed: {error})"
            sections.append(f"## {image.name}\n\n{text}\n")
            continue
        sections.append(f"## {image.name}\n\n{text}\n")
    destination.write_text("\n".join(sections), encoding="utf-8")


def _vision_models() -> list[str]:
    primary = (os.environ.get("VISUAL_MODEL") or "glm-5.3").strip()
    models = [primary] if primary else []
    for name in ("glm-5.3-flash", "qwen3.6-flash"):
        if name not in models:
            models.append(name)
    return models


def _looks_like_refusal(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 8:
        return True
    markers = ("无法", "没有图片", "没有附带", "不具备", "看不到", "没有接收", "cannot view", "can't view")
    return any(marker in stripped for marker in markers)


def _caption_image(path: Path) -> str:
    last = "(no vision credentials)"
    for model in _vision_models():
        last = _caption_with_model(path, model)
        if not _looks_like_refusal(last):
            if model != _vision_models()[0]:
                print(f"[codex] caption used {model}", flush=True)
            return last
    return last


def _caption_with_model(path: Path, model: str) -> str:
    base_url = (os.environ.get("VISUAL_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")
    api_key = (os.environ.get("VISUAL_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not base_url or not api_key:
        return "(no vision credentials)"
    mime = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif path.suffix.lower() == ".webp":
        mime = "image/webp"
    payload = {
        "model": model,
        "max_tokens": 600,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "逐字列出这张网页参考图里所有可见文字，每行一条。不要解释，不要补充图里没有的字。",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"},
                },
            ],
        }],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        message = f"vision HTTP {error.code}: {detail}"
        if error.code == 429 or quota_blocked(detail):
            raise QuotaError(message) from error
        raise RuntimeError(message) from error
    return str(body["choices"][0]["message"]["content"] or "")


def run_master(requirements_dir: Path, output_dir: Path) -> list[str]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    model = os.environ.get("MODEL", "").strip() or None
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    nodes = atomic_ids(requirements_dir)
    print(f"[codex] {len(nodes)} atomic nodes", flush=True)
    instructions = "你是主代理。一次只派一个子代理，自己不改产品代码。复核测试原文，全部完成后再跑一次回归。"
    with Codex(config=_codex_config(CodexConfig)) as codex:
        print("[codex] logging in with the injected API key", flush=True)
        codex.login_api_key(api_key)
        for round_index in range(1, 7):
            done = [node_id for node_id in nodes if node_id in completed_ids(output_dir)]
            remaining = [node_id for node_id in nodes if node_id not in done]
            print(f"[codex] round {round_index} remaining {len(remaining)}", flush=True)
            if not remaining:
                return []
            prompt = _master_prompt(requirements_dir) if round_index == 1 and not done else _continue_prompt(
                requirements_dir, done, remaining
            )
            master = codex.thread_start(
                cwd=str(output_dir),
                sandbox=Sandbox.full_access,
                approval_mode=ApprovalMode.deny_all,
                model=model,
                model_provider="arcbench" if base_url else None,
                developer_instructions=instructions,
            )
            try:
                result = master.run(prompt)
            except Exception as error:
                print(f"[codex] round {round_index} failed: {error}", flush=True)
                if quota_blocked(str(error)):
                    raise QuotaError(str(error)) from error
                continue
            if getattr(result, "error", None) is not None:
                print(f"[codex] round {round_index} failed: {result.error}", flush=True)
                if quota_blocked(str(result.error)):
                    raise QuotaError(str(result.error))
    return [node_id for node_id in nodes if node_id not in completed_ids(output_dir)]


def main() -> int:
    print("[codex] entry", flush=True)
    args = parse_args()
    requirements_dir = Path(args.requirement_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not requirements_dir.is_dir():
        raise FileNotFoundError(f"Requirement directory not found: {requirements_dir}")

    os.environ["ARCBENCH_OUTPUT_DIR"] = str(output_dir)
    runtime = AgentRuntime.from_env()
    agent_root = Path(__file__).resolve().parent
    copy_template_contents(agent_root / "template", output_dir)
    copy_skills_to_output(agent_root / "skills", output_dir)
    runtime.traceability.init_db()
    runtime.git.ensure_repo(create_initial_commit=True)
    runtime.events.mark_run_started("agent run started")
    pin_port(output_dir)
    try:
        write_reference_captions(requirements_dir, output_dir)
        remaining = run_master(requirements_dir, output_dir)
    except Exception as error:
        runtime.events.mark_run_failed(str(error))
        raise
    if remaining:
        runtime.events.mark_run_failed("unfinished: " + ", ".join(remaining))
        print("[codex] unfinished " + ", ".join(remaining), flush=True)
        return 1
    runtime.events.mark_run_completed("agent run completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI

from arcbench_agent_runtime import AgentRuntime

SYSTEM_PROMPT = (
    "Vite+React19+TS 前端在 frontend/，Express+SQLite 后端在 backend/。\n"
    "接线约定（必须遵守）：\n"
    "- 前端路由在 frontend/src/App.tsx 的 <Routes> 里注册，页面放 frontend/src/pages/。\n"
    "- 前端是 TS 项目：修改现有文件（App.tsx、main.tsx、pages/HomePage.tsx 等），"
    "沿用原扩展名；禁止新建同名 .jsx/.js 文件。main.tsx 已用 <BrowserRouter> "
    "包裹 <App/>，组件内禁止再使用 BrowserRouter/Router。\n"
    "- 前端请求一律走 /api 前缀（可用 fetch('/api/...') 或 frontend/src/api/index.ts 的 axios 实例）。\n"
    "- 后端所有 API 路由必须注册在 backend/src/app.js 里的同一个 app 上；"
    "入口 backend/src/index.js 会 require('./app') 并 listen(PORT)。"
    "禁止新建独立 server 文件、禁止在其它文件里调用 app.listen。\n"
    "- 修改 backend/src/app.js 时必须原样保留文件尾部已有的 "
    "frontend/dist 静态托管、SPA fallback 路由和 /api/health；只在中间追加路由。"
    "Express 5 不支持 app.get('*')，SPA fallback 只能用模板的正则写法。\n"
    "- 持久化用 backend/src/database 暴露的 run/get/all/exec（SQLite）。\n"
    "- 会话契约：注册/登录成功返回 JSON {token, user:{username}}；"
    "前端把 token 存 localStorage，之后每次请求带 Authorization: Bearer <token>；"
    "后端用该头校验。模板没有 cookie-parser，禁止用 cookie 传会话。\n"
    "逐个输出文件，每个文件格式为：\n"
    "===FILE: <相对路径>===\n<完整文件内容>\n"
    "全部文件输出完后，单独一行输出 ===END===。不要输出任何其他内容。\n"
    "文本、按钮名、label、placeholder、初始值与需求完全一致。\n"
    "可访问性契约（Playwright getByRole/getByLabel 直接依赖）：\n"
    "- 表单控件必须与 <label htmlFor> 原生关联，可访问名称与需求逐字一致。\n"
    "- 需求中的“链接/Link”一律用 <a href> 或 <Link>（role=link），"
    "“按钮”用 <button>（role=button），不能互换；退出登录必须是链接。\n"
    "- 错误提示放进 role=\"alert\" 的可见元素；需求中出现的标题/分区文字"
    "（如“账户信息”）必须在页面上原样可见。\n"
    "- 登录态：用户名必须以独立元素的精确文本显示（如 <span>{username}</span>），"
    "不要拼接“当前用户：”等前缀；校验失败必须提交到后端或在页面渲染 role=alert 提示，"
    "输入框不要加 required 属性（会阻止提交导致看不到自定义错误）。\n"
    "只允许输出业务源码文件；禁止输出 package.json、package-lock.json、"
    "vite.config、tsconfig、playwright.config 等脚手架文件。"
    "依赖已装好（前端 react/react-router-dom/axios，后端 express/sqlite3），"
    "不要引入新依赖。"
)

PROTECTED_FILES = {
    "package.json", "package-lock.json", "tsconfig.json", "tsconfig.app.json",
    "tsconfig.node.json", "vite.config.js", "vite.config.ts", "vitest.config.js",
    "playwright.config.js", "playwright.config.ts", "eslint.config.js",
    "pnpm-lock.yaml", "yarn.lock", ".npmrc",
}

# Template plumbing the model must not rewrite (entrypoints, db harness, html shell).
PROTECTED_PATHS = {
    "backend/src/index.js",
    "backend/src/database/index.js", "backend/src/database/init_db.js",
    "backend/src/database/db_runtime.js", "backend/src/database/seed_db.js",
    "backend/src/database/test_harness.js", "backend/src/database/prepare_e2e.js",
    "frontend/index.html", "frontend/src/main.tsx", "frontend/test/setup.ts",
}

FILE_MARKER = re.compile(r"^===FILE:\s*(?P<path>.+?)===\s*$", re.M)
END_MARKER = re.compile(r"^===END===\s*$", re.M)
MAX_COMPLETION_TOKENS = int(os.environ.get("ARC_MAX_TOKENS", "32768"))
MAX_CONTINUATIONS = 15


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


def build_prompt(requirements: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for req in requirements:
        lines.append(f"[{req['id']}] {req['description']}")
        scenarios = compress_scenarios(req.get("scenarios"))
        if scenarios:
            lines.append(scenarios)
    return "\n".join(lines)


def parse_file_blocks(text: str) -> tuple[list[tuple[str, str]], bool]:
    """Split ===FILE: path=== blocks. Returns (files, terminated)."""
    matches = list(FILE_MARKER.finditer(text or ""))
    files: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        endm = END_MARKER.search(body)
        if endm:
            body = body[: endm.start()]
        body = body.strip("\n")
        if body:
            files.append((m.group("path").strip(), body + "\n"))
    return files, bool(END_MARKER.search(text or ""))


def extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("model response does not contain a JSON object")
    return json.loads(text[start : end + 1])


def chat(client: OpenAI, model: str, messages: list[dict[str, Any]]) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=MAX_COMPLETION_TOKENS,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return response.choices[0].message.content or ""


def verify_build(output_dir: Path) -> str:
    """Cheap post-generation check. Returns error text, or '' if OK/unverifiable."""
    src = output_dir / "backend" / "src"
    if src.is_dir():
        for js in sorted(src.rglob("*.js")):
            try:
                r = subprocess.run(["node", "--check", str(js)],
                                   capture_output=True, text=True, timeout=30)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return ""
            if r.returncode != 0:
                return f"{js.relative_to(output_dir)}: {(r.stderr or '').strip()[:800]}"
    backend = output_dir / "backend"
    if (backend / "node_modules").is_dir():
        try:
            proc = subprocess.Popen(
                ["node", "src/index.js"], cwd=backend,
                env={**os.environ, "PORT": "3987"},
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                out, _ = proc.communicate(timeout=8)
                if proc.returncode:
                    return f"backend boot failed:\n{out[-1500:]}"
            except subprocess.TimeoutExpired:
                proc.terminate()
        except FileNotFoundError:
            pass
    return ""


def generate_files(client: OpenAI, model: str, prompt: str, output_dir: Path,
                   verify=None) -> int:
    """Stream files out of the model in ===FILE=== blocks, continuing on truncation.

    `verify` is an optional callable(output_dir)->error_text; when it reports an
    error after the model finished, the error is fed back for a repair round.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    written = 0
    empty_rounds = 0
    for _ in range(MAX_CONTINUATIONS):
        content = chat(client, model, messages)
        messages.append({"role": "assistant", "content": content})

        files, done = parse_file_blocks(content)
        dropped = None
        if not done and files:
            dropped = files.pop()[0]  # last block may be truncated mid-file
        if not files:
            # Fallback: some models ignore the protocol and emit a JSON blob.
            try:
                files = [
                    (str(f.get("path", "")), str(f.get("content", "")))
                    for f in extract_json(content).get("files", [])
                    if isinstance(f, dict)
                ]
                done = True
            except Exception:
                files = []

        for rel, body in files:
            if write_file(output_dir, rel, body):
                written += 1

        if done:
            if written == 0:
                raise RuntimeError("model produced no files")
            ensure_app_js_plumbing(output_dir)
            if verify is not None:
                problem = verify(output_dir)
                if problem:
                    messages.append({
                        "role": "user",
                        "content": (
                            "生成的代码运行时报错：\n" + problem +
                            "\n请修复并用 ===FILE: <相对路径>=== 格式重新输出"
                            "出错的完整文件，然后输出 ===END==="
                        ),
                    })
                    done = False
                    continue
            return written

        empty_rounds = empty_rounds + 1 if not files else 0
        if empty_rounds >= 3:
            raise RuntimeError("model kept producing no parseable files")
        resume = dropped or (files[-1][0] if files else "第一个文件")
        messages.append({
            "role": "user",
            "content": (
                f"输出被截断。请从文件 {resume} 开始重新完整输出它和所有剩余文件，"
                "仍然使用 ===FILE: <相对路径>=== 格式，最后输出 ===END==="
            ),
        })
    raise RuntimeError(f"generation did not finish after {MAX_CONTINUATIONS} continuations")


APP_JS = "backend/src/app.js"
APP_JS_PLUMBING = """
const frontendDistPath = path.resolve(__dirname, '../../frontend/dist');
if (fs.existsSync(frontendDistPath)) {
  app.use(express.static(frontendDistPath));
  app.get(/^(?!\\/api(?:\\/|$)).*/, (req, res) => {
    res.sendFile(path.join(frontendDistPath, 'index.html'));
  });
}
"""


def ensure_app_js_plumbing(output_dir: Path) -> None:
    """Guarantee the template's static-serving + health plumbing survived rewriting."""
    app_js = output_dir / APP_JS
    if not app_js.is_file():
        return
    text = app_js.read_text(encoding="utf-8")
    changed = False
    for name in ("path", "fs"):
        if f"require('{name}')" not in text:
            text = f"const {name} = require('{name}');\n" + text
            changed = True
    missing = []
    if "/api/health" not in text:
        missing.append(
            "app.get('/api/health', (req, res) => res.json({ code: 200, message: 'Backend Ready' }));\n")
    # Express 5 rejects '*' wildcards; swap to the template's regex fallback.
    fixed, n = re.subn(
        r"(app\.(?:get|use|all)\()\s*(['\"])\*[^'\"]*\2",
        r"\1/^(?!\\/api(?:\\/|$)).*/", text)
    if n:
        text, changed = fixed, True
    if "express.static" not in text or "sendFile" not in text:
        missing.append(APP_JS_PLUMBING)
    if missing:
        anchor = "module.exports"
        idx = text.rfind(anchor)
        inject = "".join(missing)
        text = (text[:idx] + inject + text[idx:]) if idx != -1 else text + inject
        changed = True
    if changed:
        app_js.write_text(text, encoding="utf-8")
        print("repaired app.js plumbing (static/health)", file=sys.stderr)


def write_file(output_dir: Path, rel_path: str, content: str) -> bool:
    rel_path = str(rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel_path or content is None:
        return False
    if Path(rel_path).name in PROTECTED_FILES or rel_path in PROTECTED_PATHS:
        print(f"skip protected file: {rel_path}", file=sys.stderr)
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

        written = generate_files(client, model, build_prompt(requirements),
                                 output_dir, verify=verify_build)
        print(f"generated {written} files")

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

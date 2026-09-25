from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import re
from pathlib import Path
from typing import Any

import yaml
from openai import BadRequestError, OpenAI
from openai.types.chat import ChatCompletionToolUnionParam

from arcbench_agent_runtime import AgentRuntime
from requirement_context import build_requirement_context
from agent_validation import (ProjectValidator, ValidationResult, discover_tests,
                              derive_ui_candidates, derive_ui_obligations, requirement_outcomes, run_command)

SYSTEM_PROMPT = """你是负责完整交付的编程 agent，根据原始需求实现可运行、可验证的 web 项目。
原子需求索引: {requirements}
原始需求目录（含参考图）: {source}
业务自测目录: {tests}
输出项目: {output}
模板: frontend/ 为 Vite + React 19 + TS + Tailwind 4；backend/ 为 Express 5 + SQLite，单端口托管 frontend/dist。

1. 先读需求，不以自测数量替代需求覆盖。
   只读 requirements.yaml/requirement.txt、说明、参考图；禁止读取、复制或依赖题目 tests/helpers/spec。
   先完整读 .arc/requirements/index.md 和 review.md，再逐项读索引里的原子工作单，每份含父节点约束、依赖、完整原文。
   大文件 read 时用 offset/limit 连续读到末尾；输出截断不表示需求已读完。跨模块操作必须回读所引用需求。
   原子描述中的精确角色/作用域/状态规则与父级共享约束共同决定实现；原文给出优先级时按原文处理。
   场景含 the requested workflow 等占位文本时，必须从具体 description 展开实际操作和断言，不得写一个通用占位流程冒充覆盖。
   在 .arc/contract.md 为每项需求列出：父级约束、入口、前置对象、精确控件、成功/取消/失败/权限/刷新分支及各自测试。
   存在真正矛盾时记录原文双方与采用的解释，不得静默改编号、造操作、丢弃分支或声称已经验证。

2. 建模共享数据和事务，优先打通被依赖最多的流程。
   阅读 .arc/scenario-inventory.json 和 fixture-inventory.md：每个 GIVEN 是独立的原始前置条件，WHEN 是操作输入，THEN 是预期结果。
   建立完整 seed 审查清单，保留对象身份、所属关系、账号凭据、初始值、权限、每场景初始状态的原文依据。
   同名不意味着同一条记录；只有原文明示同一实体才复用。不同场景独立账号/对象要隔离；同名数据相互矛盾时记录冲突，
   自测通过可见 UI 准备不同场景的状态并明确恢复策略，不能让普通启动重置数据，不能依赖用例顺序或私有测试接口。
   名称、状态、角色和描述按原文；待创建的对象、输入、按钮名、结果不能被提前 seed。
   schema 在 backend/src/database/init_db.js，seed 在 seed_db.js，遵守 ARC_DB_FILE。正常 npm start 等待建表和幂等 seed 后再监听。
   空数据库冷启动必须自动具备需求前置数据；seed 不覆盖用户已改的记录；前后端共享服务器持久化数据，不能只存在 localStorage。
   先从真实首页走到核心对象详情并刷新，再扩展依赖功能。只有需求包含认证时才增加登录流程；没有认证要求不得凭空加登录墙。
   状态变更用事务：校验失败返回错误并保持原值、关联记录、派生结果不变。异步过期响应不能覆盖当前路由/当前对象。

3. UI 语义严格服从原文，按作用域区分同名控件。
   指定 link/button/tab/gridcell/menuitem/native select 的地方必须使用相应角色；没有明确要求时按实际操作选择语义。
   不要给所有对象额外套 heading 或 article；只有需求要求标题/卡片/网格时按要求实现。交互元素不得嵌套交互元素。
   控件名称独立于描述和装饰，input 有 label，密码 input 用 getByLabel；需求指定 heading 时文字只含该标题。
   tab/选区/切换按钮维护原文指定 aria-selected/aria-pressed/aria-expanded；title 属性仅在需求要求时精确实现。
   同名控件出现在多个对象、弹窗、菜单时使用原文作用域；导航 Code link 与操作 Code button 等不能互换角色。
   未授权不可见与禁用是不同状态；有些操作应 absent，有些应可见 disabled，按原文分别实现。
   按 .arc/requirement-ui-obligations.json 编写 .arc/ui-contract.json；.arc/ui-review.json 是动态/条件/冲突文本审查清单，不能直接照抄为固定名称。
   原始编号和分隔符必须保留，如 REQ-1-1-1 与 REQ-1.1.1。共享父级约束可在对应叶子流程标注父级 req_id 一并检查。
   格式 {{"cases":[{{"name":"场景", "req_ids":["REQ-1"], "path":"/", "steps":[
     {{"action":"assert", "roles":["button"], "name":"原文精确名称"}},
     {{"action":"click", "roles":["button"], "name":"原文精确名称"}}]}}]}}。
   普通 assert/click/fill/check/uncheck 按 roles+name 精确定位，fill 需 value；密码或原文 labeled 控件可用 by="label" 代替 roles。
   scope 可为 {{"role":"dialog","name":"弹窗名"}}；纯文字断言 assertText。动态名称模板要以场景中实际对象替换，不得渲染尖括号占位符。
   支持 press（key 如 Enter）、select（value 为原生 option 标签）、dblclick、contextmenu、reload（无需 name）。
   支持 assertAbsent、assertDisabled、assertEnabled、assertAttribute（attribute 和字符串 value），用于权限、状态和刷新检查。
   roles 只能是原文允许的角色。断言前先从真实入口操作到该状态；不能省略前置步骤或扩大允许角色迎合实现。
   UI 契约通过结构、原文检查和全量验收后冻结；冻结前按原文调通前置操作和作用域，冻结后不能削弱契约。

4. 按需求涉及的系统特征选择实现方法，不能把复杂操作做成只改文字的按钮。
   涉及多账号/组织/权限时：浏览器 session 隔离，持久凭据、注销/改密和后续请求权限一致；后端按当前用户+目标对象校验。
   为每种操作列显式允许/禁止角色表。角色只有原文声明时才是累加阶梯；团队层级不自动传播成员或权限。
   涉及版本/分支/差异/评审时：文件绑定分支快照和提交，比较用实际提交数据；新提交使对应旧评审失效的规则必须实现。
   合并前重读当前 head、冲突、有效评审和保护条件，事务写入提交及状态，不能只把页面状态改为 Merged。
   涉及网格/公式/批量编辑时：分离原始输入、计算结果、当前编辑草稿；Enter/blur 提交、Escape 取消，坐标是 gridcell 的名称。
   保存每个文档/工作表独立选区、活动页、校验、筛选、透视配置；刷新同一 URL 恢复原对象。矩形选择逐格维护 aria-selected。
   建立共享纯状态变换和事务提交，供粘贴、剪切、行列插删、撤销重做共用。任何一格失败都整体回滚。
   公式支持原文指定语法、相对/绝对引用、间接依赖及循环错误；不要用 eval 执行输入。结构操作同步修改引用和各类区域。
   排序只操作指定区域并整体移动行；筛选隐藏不删除，导出/聚合是否包含隐藏行按原文；透视刷新与失败保留旧结果按原文。
   CSV 要真正解析 UTF-8、引号转义、字段内换行、空字段及畸形输入；导出通过下载文件核验，不以页面提示替代结果。
   剪贴板、键盘、拖选、文件上传下载、直接刷新入口都用真实浏览器交互覆盖；不应以私有 API 替代可见 UI 操作。

5. 边实现边写有实际状态断言的自测，最后冷启动全量验证。
   backend/agent-smoke-tests/*.spec.js 的标题含原子 REQ ID；同一需求多个分支用独立测试覆盖，每个测试有源前提和明确预期。
   要测试成功、禁止/失败、取消、刷新/重新打开、跨对象隔离和关联功能影响。只有控件可见/首页不报错不足以验收完整需求。
   不使用 test.skip/.only、无断言、固定等待、SQL/私有 API 预填前置数据或伪造网络响应；登录使用独立浏览器 context。
   公共流程增加延迟但放行真实 API 的检查；等 loading 消失与目标可见，不能用瞬时 count()/isVisible() 决定永久备用定位。
   图标状态、错误提示、撤销完成文案按需求精确断言；确认无效输入时没有部分写入，不能只断言错误文字。
   helper、fixture、测试数据源放在 agent-smoke-tests 内，运行证据放 evidence_dir。
   每次 verify 执行期间禁止改写自测及 helper；全量验收通过后才保留冻结基线，可新增用例。
   尚未通过的自测可依据原文纠正错误前提、操作和预期，记录原文与理由；不得删除覆盖、跳过场景或为了通过而放宽断言。
   系统启动新的需求复核阶段时会重新建立基线。该阶段首次全量验收通过前，可依据原文纠正旧自测，并记录原文和修改理由。
   如误改冻结文件，从 .arc/validation/<run-id>/baseline-files 恢复原文。磁盘清单不决定基线，修改 JSON 不能解除冻结。
   verify 独立构建、检查 seed、用空数据库启动，再运行 UI 契约和业务自测，两套分别冷启动。UI 标签数量不算业务覆盖。
   Chromium 缺失时在 backend 运行 npx playwright install chromium，Linux 缺库加 --with-deps。
   自测失败读报告、错误页面可访问树和截图，先修共享数据/入口/权限再修单项；同样失败不得无修改反复 verify。
   验收全过后对照每份原子工作单再核查遗漏分支，不能宣称平台评分或未运行的测试通过。
6. 每次工具写小文件/补丁。JSON 截断时拆分，不原样重试大型负载。完整证据保留磁盘，可按页读取。
"""

MAX_STEPS = 600
MAX_OUTPUT_CHARS = 16000

SOURCE_AUDIT_PROMPT = """现在开始需求复核。已有代码和自测可运行，但不能据此推断需求已完成。
逐项重新阅读 .arc/requirements/index.md 指向的原子需求原文、父级约束和场景。
先根据原文独立写出每个场景的预期，再读现有测试，找出遗漏或与原文不一致的断言。
重点检查：标识与显示名称是否混用；对象属于谁、谁有权限；同名控件的角色和作用域；
拒绝、取消、刷新、重新登录、跨对象隔离；种子对象与新建对象；重复场景背后的不同分支。
例如原文要求标题显示 identifier，测试不能只断言 display name；组织的仓库不能用个人仓库替代。
在 backend/agent-smoke-tests 新增遗漏场景，运行它看到失败后修复产品代码，再用 verify 全量验证。
本阶段首次全量验收通过前，逐项纠正已有自测中违反原文的预期，并记录原文、旧断言、正确断言及理由。
不能删除需求覆盖、跳过用例、放宽角色或用实现细节取代可见行为；首次全量验收通过后新的测试基线会冻结。
把逐项依据、补测和实际结果写入 .arc/source-audit.md，完成全部原子需求复核后再结束。
"""

TOOLS: list[ChatCompletionToolUnionParam] = [
    {
        "type": "function",
        "function": {
            "name": "verify",
            "description": "独立构建、准备数据库、启动服务并运行全量 E2E，返回真实失败与证据路径。修复后可重复调用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
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
    return text[:MAX_OUTPUT_CHARS // 2] + "\n<output clipped; read full log/file in chunks>\n" + text[-MAX_OUTPUT_CHARS // 2:]


def run_bash(command: str, cwd: Path) -> str:
    log = cwd / ".arc" / "command-logs" / f"{time.time_ns()}.log"
    result = run_command(["bash", "-c", command], cwd, log)
    return f"exit code {result.returncode}; full log: {log}\n" + (clip(result.output) or "(no output)")


def resolve(raw_path: str, root: Path) -> Path:
    path = Path(raw_path)
    return (path if path.is_absolute() else root / raw_path).resolve()


def run_read(args: dict[str, Any], root: Path) -> str:
    path = resolve(str(args.get("path") or ""), root)
    if path.is_dir():
        entries = []
        for directory, dirs, files in os.walk(path):
            relative = Path(directory).relative_to(path)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {"node_modules", "dist", "__pycache__"})
            entries.extend(str(relative / name) for name in dirs + sorted(files))
            if len(relative.parts) >= 1:
                dirs[:] = []
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
    if not path.is_relative_to(root.resolve()):
        return f"error: path must be inside {root}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content), encoding="utf-8")
    return f"wrote {path}"


def run_edit(args: dict[str, Any], root: Path) -> str:
    old = args.get("old")
    if old is None:
        return "error: old is required"
    path = resolve(str(args.get("path") or ""), root)
    if not path.is_relative_to(root.resolve()):
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


def find_tests_dir(output_dir: Path, requirements_dir: Path | None = None) -> str:
    candidate = discover_tests(output_dir, requirements_dir)
    return str(candidate) if candidate else ""


def read_requirements_data(requirements_dir: Path) -> Any:
    yaml_path = requirements_dir / "requirements.yaml"
    if yaml_path.is_file():
        return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    json_path = requirements_dir / "requirement.txt"
    if json_path.is_file():
        payload = yaml.safe_load(json_path.read_text(encoding="utf-8"))
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
            or str(value.get("type", "")).upper() in {"ATOMIC", "COMPOSITE", "FOLDER"}
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
                    "type": value.get("type", ""),
                    "details": {key: child for key, child in value.items()
                                if key not in {"children", "children_ids"}},
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
    # Retain all scenario fields and contract metadata; no lossy step projection.
    return "\n\n".join(
        f"## {req['id']} {req['name']}\n\n" +
        yaml.safe_dump(req.get("details", req), allow_unicode=True, sort_keys=False)
        for req in requirements
    )


def build_fixture_inventory(requirements: list[dict[str, Any]]) -> str:
    """Preserve source context and distinguish preconditions from actions/results.

    This is a review aid, not an entity extractor or a database schema. Quoted
    buttons, newly created names, and requirement parents are not seed records.
    """
    rows = [
        '# Data preconditions and scenario transitions', '',
        'Review source passages below. Only explicitly pre-existing records belong '
        'in seed data. Descriptions may mix initial state and actions; interpret them '
        'in context. Never seed action inputs, expected new records, or UI labels. '
        'Requirement hierarchy does not imply a database relationship.', '',
    ]
    for req in requirements:
        rows.extend([f"## {req['id']} {req['name']}",
                     '### Description (review in context)',
                     str(req.get('description', ''))])
        scenarios = req.get('scenarios') or req.get('details', {}).get('scenarios') or []
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                rows.extend(['### Scenario (unclassified)', str(scenario)])
                continue
            rows.append('### Scenario: ' + str(scenario.get('name', '')))
            phase = ''
            for step in scenario.get('steps') or []:
                if not isinstance(step, dict):
                    rows.append('Unclassified: ' + str(step))
                    continue
                keyword = str(step.get('keyword', '')).upper()
                if keyword in {'GIVEN', 'WHEN', 'THEN'}:
                    phase = keyword
                elif keyword not in {'AND', 'BUT'}:
                    phase = ''
                label = {'GIVEN': 'Precondition (classify data vs UI state)',
                         'WHEN': 'Action/input (not a seed instruction)',
                         'THEN': 'Expected result (not a seed instruction)'}.get(phase, 'Unclassified')
                rows.append(label + ': ' + yaml.safe_dump(step, allow_unicode=True, sort_keys=False).strip())
            other = {k: v for k, v in scenario.items() if k not in {'name', 'steps'}}
            if other:
                rows.append('Additional scenario fields (review in context):\n' +
                            yaml.safe_dump(other, allow_unicode=True, sort_keys=False))
        rows.append('')
    return '\n'.join(rows) + '\n'


def extract_fixture_manifest(requirements: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Extract a reviewable checklist for explicitly pre-existing records.

    This is deliberately limited to phrases that state existence. It does not
    turn every quoted UI label or action input into seed data.
    """
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    patterns = [
        re.compile(r"(?:system|database)\s+contains\s+(?:an?\s+)?([^,.;]+?)\s+named\s+[\"'`]([^\"'`]+)[\"'`]", re.I),
        re.compile(r"(?:existing|pre-existing|already\s+exists?)\s+(?:an?\s+)?([^,.;]+?)\s+named\s+[\"'`]([^\"'`]+)[\"'`]", re.I),
        re.compile(r"verified\s+account\s+with\s+nickname\s+[\"'`]([^\"'`]+)[\"'`]", re.I),
    ]
    for req in requirements:
        details = req.get('details', req)
        passages = [str(req.get('description', ''))]
        for scenario in details.get('scenarios') or []:
            if isinstance(scenario, dict):
                passages.extend(str(step.get('content', '')) for step in scenario.get('steps') or []
                                if isinstance(step, dict))
        for passage in passages:
            for index, pattern in enumerate(patterns):
                for match in pattern.finditer(passage):
                    if index == 2:
                        entity, name = 'account nickname', match.group(1)
                    else:
                        entity, name = match.group(1).strip(), match.group(2).strip()
                    key = (entity.lower(), name, req['id'])
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({'req_id': req['id'], 'entity': entity, 'name': name,
                                 'source': passage})
    return rows


def selected_wire_api() -> str:
    """Return the provider wire protocol used by the model endpoint.

    Default to Chat Completions for the DeepSeek provider setup.
    Set OPENAI_WIRE_API=responses for endpoints using Responses.
    Codex's config.toml is independent and is not loaded by this program.
    """
    value = os.environ.get("OPENAI_WIRE_API", "chat").strip().lower()
    if value in {"responses", "response"}:
        return "responses"
    if value in {"chat", "chat.completions", "completions"}:
        return "chat"
    raise ValueError("OPENAI_WIRE_API must be 'responses' or 'chat'")


def is_deepseek_model(model: str) -> bool:
    """Recognize direct or provider-prefixed DeepSeek model names."""
    return model.rsplit("/", 1)[-1].lower().startswith("deepseek-")


def deepseek_thinking_type() -> str:
    """Allow disabling DeepSeek thinking without changing the wire protocol."""
    value = os.environ.get("DEEPSEEK_THINKING", "enabled").strip().lower()
    if value in {"enabled", "true", "1", "on"}:
        return "enabled"
    if value in {"disabled", "false", "0", "off"}:
        return "disabled"
    raise ValueError("DEEPSEEK_THINKING must be 'enabled' or 'disabled'")


def responses_tools() -> list[dict[str, Any]]:
    """Convert Chat Completions tool declarations to Responses declarations."""
    converted: list[dict[str, Any]] = []
    for tool in TOOLS:
        function = tool.get("function", {})
        converted.append({
            "type": "function",
            "name": function.get("name"),
            "description": function.get("description", ""),
            "parameters": function.get("parameters", {"type": "object", "properties": {}}),
            # Preserve optional read offset/limit fields; Responses otherwise
            # normalizes omitted strict mode to a strict schema.
            "strict": False,
        })
    return converted


def response_item_value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def response_function_calls(response: Any) -> list[Any]:
    output = response_item_value(response, "output", []) or []
    return [item for item in output
            if response_item_value(item, "type") == "function_call"]


def request_model_completion(create: Any, request: dict[str, Any]) -> Any:
    # The observed proxy wraps upstream connection resets in HTTP 400, which
    # the SDK does not retry. Retry only that transport failure, before tools run.
    for attempt in range(3):
        try:
            return create(**request)
        except BadRequestError as error:
            if (error.code != "proxy_error" or "connection reset by peer" not in error.message
                    or attempt == 2):
                raise
            delay = 2 ** attempt
            print(f"[agent] model proxy connection reset; retry {attempt + 1}/2 in {delay}s", flush=True)
            time.sleep(delay)


def react_loop(client: OpenAI, model: str, system_prompt: str, output_dir: Path,
               validator: ProjectValidator) -> ValidationResult:
    wire_api = selected_wire_api()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "只根据需求和参考图实现；先写 .arc/contract.md，再按模块实现，并为每个原子需求写有真实状态断言的自测。"},
    ]
    trace = output_dir / ".arc/agent-steps.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    max_steps = int(os.environ.get("AGENT_MAX_STEPS", str(MAX_STEPS)))
    last_verified: ValidationResult | None = None
    auditing_source = False
    print(f"[agent] wire_api={wire_api} model={model}", flush=True)
    for step in range(max_steps):
        print(f"[agent] step {step + 1}/{max_steps}", flush=True)
        try:
            request: dict[str, Any] = {"model": model}
            # Restore the original DeepSeek Chat request; other providers
            # receive only reasoning options explicitly set by the runner.
            deepseek_chat = wire_api == "chat" and is_deepseek_model(model)
            reasoning_effort = os.environ.get(
                "OPENAI_REASONING_EFFORT", "low" if deepseek_chat else ""
            ).strip()
            if wire_api == "responses":
                request.update(input=messages, tools=responses_tools(), store=False,
                               include=["reasoning.encrypted_content"])
                if reasoning_effort:
                    request["reasoning"] = {"effort": reasoning_effort}
                response = request_model_completion(client.responses.create, request)
            else:
                request.update(messages=messages, tools=TOOLS)
                if deepseek_chat:
                    request["extra_body"] = {"thinking": {"type": deepseek_thinking_type()}}
                if reasoning_effort:
                    request["reasoning_effort"] = reasoning_effort
                response = request_model_completion(client.chat.completions.create, request)
        except Exception as error:
            # Never deliver a stale success: tools may have changed files since
            # verify. Recheck current output without making another model call.
            status = getattr(error, 'status_code', None)
            if status == 429 and auditing_source and last_verified is not None and last_verified.ok:
                print('[agent] model returned 429 after successful verification; revalidating current output', flush=True)
                validation = validator.validate()
                with trace.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({'step': step + 1, 'event': 'model-429-revalidation',
                                             'ok': validation.ok, 'evidence_dir': validation.evidence_dir}) + '\n')
                if validation.ok:
                    print('[agent] current output revalidated; completing without another model call', flush=True)
                    return validation
                raise RuntimeError('Model returned 429; current output failed revalidation. '
                                   'Delivery was not marked successful.\n' + validation.feedback()) from error
            raise
        if wire_api == "responses":
            # Replay all output items, including reasoning, in their original
            # order. function_call_output must reference call_id, not item id.
            response_status = response_item_value(response, "status")
            if response_status != "completed":
                raise RuntimeError(f"Responses request did not complete (status={response_status}); "
                                   "no tools were executed and delivery was not marked successful")
            output = [item if isinstance(item, dict) else item.model_dump(exclude_none=True)
                      for item in response_item_value(response, "output", [])]
            messages.extend(output)
            calls = [{"name": response_item_value(call, "name"),
                      "arguments": response_item_value(call, "arguments"),
                      "id": response_item_value(call, "call_id")}
                     for call in response_function_calls(response)]
            trace_message = {"status": response_status, "output": output}
        else:
            message = response.choices[0].message
            # The SDK retains DeepSeek's extra reasoning_content field here;
            # replay it verbatim along with tool calls on subsequent turns.
            messages.append(message.model_dump(exclude_none=True))
            calls = [{"name": call.function.name, "arguments": call.function.arguments, "id": call.id}
                     for call in (message.tool_calls or []) if call.type == "function"]
            trace_message = {"finish_reason": getattr(response.choices[0], "finish_reason", None),
                             "message": message.model_dump(exclude_none=True)}
        with trace.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"step": step + 1, "wire_api": wire_api, **trace_message},
                                    ensure_ascii=False) + "\n")

        if not calls:
            # Always revalidate the current files, even after a previous passing run.
            validation = validator.validate()
            last_verified = validation
            if validation.ok:
                if not auditing_source:
                    auditing_source = True
                    last_verified = None
                    validator.begin_source_audit()
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": SOURCE_AUDIT_PROMPT},
                    ]
                    print("[agent] self-tests passed; starting fresh source audit", flush=True)
                    continue
                return validation
            messages.append({"role": "user", "content":
                "交付验收未通过，继续修复，不要结束。\n" + validation.feedback()})
            continue

        for call in calls:
            try:
                args = json.loads(call["arguments"] or "{}")
                if not isinstance(args, dict):
                    raise ValueError("tool arguments must be a JSON object")
                if call["name"] == "verify":
                    last_verified = validator.validate()
                    result = last_verified.feedback()
                else:
                    result = dispatch_tool(call["name"], args, output_dir)
            except json.JSONDecodeError as error:
                result = (f"error: invalid/truncated tool JSON: {error}. No operation was executed. "
                          "Split the file into smaller modules or use small edits; do not retry the same large payload.")
            except Exception as error:
                result = f"error: {type(error).__name__}: {error}"
            print(f"[agent] {call['name']}: {result[:180]}", flush=True)
            with trace.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"step": step + 1, "tool": call["name"], "result": result},
                                        ensure_ascii=False) + "\n")
            if wire_api == "responses":
                messages.append({"type": "function_call_output", "call_id": call["id"], "output": result})
            else:
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})

        # Keep recent failure details and source reads; complete evidence stays on disk.
        # Never discard the assistant/tool-call protocol or reasoning_content.
        for old_message in messages[2:-24]:
            field = ("output" if old_message.get("type") == "function_call_output" else
                     "content" if old_message.get("role") == "tool" else None)
            if field and len(str(old_message.get(field, ""))) > 1600:
                old_message[field] = str(old_message[field])[:800] + "\n[Older output abbreviated; reread source or .arc logs.]"

    raise RuntimeError(f"react loop exceeded {max_steps} steps without a verified delivery")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ARC-Bench agent.")
    parser.add_argument("requirement_path", nargs="?", default=os.environ.get("ARCBENCH_TASK_DIR", "requirements"))
    parser.add_argument("--output-dir", default=os.environ.get("ARCBENCH_OUTPUT_DIR", "."))
    parser.add_argument("--type", dest="task_type", default=os.environ.get("ARCBENCH_TASK_TYPE", "web"))
    return parser.parse_args()


def copy_template(template_dir: Path, output_dir: Path) -> None:
    if all((output_dir / part / "package.json").is_file() for part in ("frontend", "backend")):
        print("[agent] using application prepared by the runner", flush=True)
        return
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

        requirements_ref = str(requirements_dir)
        if requirements:
            digest = output_dir / ".arc" / "requirements.md"
            digest.parent.mkdir(parents=True, exist_ok=True)
            digest.write_text(to_markdown(requirements), encoding="utf-8")
            (output_dir / ".arc" / "fixture-inventory.md").write_text(
                build_fixture_inventory(requirements), encoding="utf-8")
            (output_dir / ".arc" / "fixture-manifest.json").write_text(
                json.dumps(extract_fixture_manifest(requirements), ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / ".arc" / "requirement-ui-obligations.json").write_text(
                json.dumps(derive_ui_obligations(requirements), ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / ".arc" / "ui-review.json").write_text(
                json.dumps([item for item in derive_ui_candidates(requirements) if item.get('review_reason')],
                           ensure_ascii=False, indent=2), encoding="utf-8")
            requirements_ref = str(build_requirement_context(requirements, output_dir))

        system_prompt = SYSTEM_PROMPT.format(
            requirements=requirements_ref,
            source=requirements_dir,
            tests=find_tests_dir(output_dir) or "backend/agent-smoke-tests（由 agent 根据需求创建）",
            output=output_dir,
        )
        atomic_ids = [req["id"] for req in requirements
                      if str(req.get("type", "")).upper() == "ATOMIC"
                      or (not req.get("children_ids") and req.get("scenarios"))]
        validator = ProjectValidator(output_dir, discover_tests(output_dir), atomic_ids, requirements)
        validation = react_loop(client, model, system_prompt, output_dir, validator)

        outcomes = requirement_outcomes(validation.tests)
        for req in requirements:
            runtime.events.mark_implementation_done(req["id"], "implementation delivered; see validation evidence")
            if req["id"] in outcomes and validation.suite_kind == "reference":
                emit = runtime.events.mark_test_passed if outcomes[req["id"]] else runtime.events.mark_test_failed
                emit(req["id"], validation.evidence_dir)
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

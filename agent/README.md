# 编程 Agent

本目录是唯一维护的 agent。核心执行器重新实现；比赛 SDK、空白 React/Express 模板、公开需求解析和交付验证器沿用已有代码。

上下文管理参考 Pi 的 [session 格式](https://pi.dev/docs/latest/session-format)与[压缩设计](https://pi.dev/docs/latest/compaction)：完整历史保存在追加式 transcript 中，每次模型请求读取由历史生成的上下文视图。

## 安装与运行

需要 Python 3.10+、Node.js、npm 和 Playwright Chromium。比赛环境负责注入模型凭据。仓库根目录可执行：

```sh
python3 -m venv .venv-agent
(cd agent && ../.venv-agent/bin/pip install -r requirements.txt)
./run-with-gateway .venv-agent/bin/python agent/main.py /path/to/public-requirements \
  --output-dir /path/to/application --type web
```

`run-with-gateway` 从根目录 `.env` 加载配置。模型客户端读取 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL`、`OPENAI_WIRE_API`、`OPENAI_REASONING_EFFORT`。协议显式选择 `chat` 或 `responses`，默认 `chat`。无凭据时直接报错。

公开需求目录包含 `requirements.yaml` 或 `requirement.txt`。输出目录保存应用、需求索引、验证证据和会话。执行器只复制缺失的模板顶级目录，保留已有应用。比赛入口仍为：

```sh
python3 main.py /path/to/requirements --output-dir /path/to/output --type web
```

验证器需要后端依赖中的 `@playwright/test` 及 Chromium；本地首次使用可在生成应用的 `backend/` 中执行 `npx playwright install chromium`。

## 会话与恢复

默认重复执行原命令，会恢复 `.arc/session/active.json` 指向的会话。工作区、需求内容、模型、协议和常驻提示必须一致；有变化时明确使用 `--new-session`。

```sh
python3 agent/main.py /path/to/requirements --output-dir /path/to/application \
  --session /path/to/application/.arc/session/session-id.jsonl
python3 agent/main.py /path/to/requirements --output-dir /path/to/application --new-session
python3 agent/main.py --inspect /path/to/application/.arc/session/session-id.jsonl
```

`--new-session` 新建历史，保留应用文件；`--inspect` 只读状态，不请求模型。每个会话目录只允许一个写入者。

每条 JSONL 记录包含 ID、序号、父记录 ID、时间和事件类型。模型响应、工具开始与结果均先持久化并 `fsync`，再继续执行。模型上下文保留工具调用 ID、Chat reasoning 字段及 Responses 的加密 reasoning 状态。

- 已记录结果的工具不会在恢复时重做。已持久化的模型响应可继续消费。
- 工具已开始但没有结果时，标记为中断，并跳过同批剩余操作。模型必须检查当前状态，再决定下一步。
- 恢复时重新验证当前应用，不能凭旧的成功结果交付。
- 请求已送达但响应未落盘时，无法确认服务端是否计费；恢复可能重新请求。

完整记录始终保留原字节。压缩只追加摘要与截止记录 ID，保留最近的完整工具批次。摘要无法缩小到预算内时停止，并保留原上下文。原始消息可通过 `history` 检索，完整工具输出和请求内容另存 artifact。

进程崩溃可能留下不含换行的半条记录。恢复时先将该片段保存为 `.torn-*` 文件，再移除未提交片段并追加 `tail_recovered` 事件。完整但损坏的记录直接报错。

## 工具与验证

核心工具为 `read`、`write`、`edit`、`bash`、`verify`、`history`。文件写入采用临时文件替换；编辑要求目标文本唯一。Shell 有时间上限，退出后清理同组子进程。模型凭据从 shell、构建和测试环境中剥离。

文件工具限制路径，并拒绝读取需求目录中的评测测试源码。Shell 仍是宿主命令执行能力，以上检查不构成操作系统沙箱；不可信任务应在比赛容器或隔离环境中运行。

`verify` 执行构建、数据初始化、UI 契约和自编写浏览器测试。第一次全量通过后，执行器追加独立需求复核阶段，要求重新阅读原文、核查实现并再次验证。每个阶段全量通过后冻结自测基线；验证执行期间禁止改写。基线保存在 transcript 中，重启后仍生效。格式见 [validation-guide.md](validation-guide.md)。

验证失败、预算耗尽、压缩失败或工具结果不确定时，不报告交付成功。自测通过仅表示本地验收完成；比赛通过率和排名以平台正式评分为准。

## 预算

| 参数 | 环境变量 | 默认值 |
| --- | --- | --- |
| `--max-steps` | `AGENT_MAX_STEPS` | 600 |
| `--context-tokens` | `AGENT_CONTEXT_TOKENS` | 65536 |
| `--keep-recent-tokens` | `AGENT_KEEP_RECENT_TOKENS` | 16384 |
| `--max-output-tokens` | `AGENT_MAX_OUTPUT_TOKENS` | 8192 |
| `--token-budget` | `AGENT_TOKEN_BUDGET` | 0，不设总量上限 |

步数与用量按整个会话累计。上下文按 UTF-8 字节保守估算；总 token 预算使用 API 返回用量，并预留下一次请求的估计输入和最大输出。该预算不是货币费用上限，也不能统计服务端未返回的用量。瞬时连接、限流和服务端错误最多重试两次；普通参数错误直接失败。

## 测试与打包

从仓库根目录执行，无需真实模型凭据：

```sh
.venv-agent/bin/python -m unittest discover -s agent/tests -v
.venv-agent/bin/python -m unittest discover -s tools -p 'test_*.py' -v
```

测试覆盖真实文件与 shell、构建凭据隔离、进程清理、本地 HTTP 模型协议、历史投影、压缩、断点恢复和验证基线。模型回复来自本地固定响应，不能据此推断真实模型的解题能力。

比赛包从已提交并推送的版本生成，ZIP 根目录包含 `main.py`：

```sh
git archive --format=zip --output=/absolute/path/agent.zip COMMIT:agent
```

包内只包含通用执行器、空白模板、SDK 和回归测试。实际生成应用、会话、凭据、依赖安装目录和旧实现保存在包外。

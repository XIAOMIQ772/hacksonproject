# 归档的旧 agent

2026-09-29 归档，新 agent 从零重写。仅作参考，不再维护。

- `agent-transcript/`：原 `agent/`，JSONL transcript + 自编写 E2E 验证。最好成绩 github 14%、sheet 4%。
- `react-astra/`：平台提交 `178280838b16` 的源码归档（此前不在仓库中），分单元生成 + 构建/启动检查。

可参考的部分：

- `react-astra/template/`：启动时自动建表并写入种子数据，事务串行化，JSON 错误处理。比官方模板完整。
- `react-astra/agent_prompt.py`：隐藏测试的界面约定（无障碍名称、role、表格 aria-label 等）。
- `react-astra/spec_digest.py`、`agent-transcript/requirements_io.py`：需求树解析和种子数据抽取。
- DeepSeek 网关细节：`thinking` 参数、`reasoning_content` 原样回传、错误分类（`react-astra/main.py`、`agent-transcript/model.py`）。

更早的旧实现见 `local-runs/legacy-agents/` 和提交 `794555b`。

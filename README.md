# 比赛编程 Agent

唯一维护入口为 [`agent/main.py`](agent/main.py)。执行器采用 JSONL transcript、追加式上下文压缩和持久化工具记录。

- [运行、恢复和打包](agent/README.md)
- [自编写验收检查](agent/validation-guide.md)
- [`tools/arc_fetch.py`](tools/arc_fetch.py)：比赛平台客户端

旧的 Python、Rust 实现和旧 ZIP 已退出主线。历史源码保留在 Git 提交 `794555b3c3e4a60bd583190eb7129f9dd9adf943`；本机完整目录归档在 `local-runs/legacy-agents/`。

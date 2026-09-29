# 比赛编程 Agent

- [`agent/`](agent/)：编程 agent，入口 `agent/main.py`，规则见 `agent/rules.md`
- [`docs/web-app-standard.md`](docs/web-app-standard.md)：生成应用的编码规范
- [`tools/arc_fetch.py`](tools/arc_fetch.py)：比赛平台客户端（排行榜、上传、运行、日志、暂停/取消）
- [`tools/local_eval.py`](tools/local_eval.py)：用外部测试套件给生成的应用打分
- [`tasks/`](tasks/README.md)：公开任务数据
- [`archive/`](archive/README.md)：旧实现

本地运行：

```sh
set -a; . ./.env; set +a
cd agent && ../.venv-agent/bin/python main.py ../tasks/hackathon/012-sheet --output-dir /tmp/out
../.venv-agent/bin/python -m unittest discover -s tests
```

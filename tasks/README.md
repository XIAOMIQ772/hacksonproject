# 公开任务数据

2026-09-29 用 `tools/arc_fetch.py` 从 arc-bench.com 爬取。

| 目录 | 来源 | 内容 |
| --- | --- | --- |
| `hackathon/` | 正式赛 hackathon | github、sheet 的需求和参考图。评测测试不公开 |
| `arc-bench-web/` | 比赛 arc-bench-web | 12306、bookstack、ctrip、keep、prestashop、stackoverflow，需求 + Playwright 测试 |
| `arc-bench-lite/`、`arc-bench-lite-evolution/` | 比赛 | bookstack、keep 精简版和演进版 |
| `smoke/`、`smoke-evolution/` | 比赛 | counter、dice 冒烟任务 |
| `ticket-booking/` | 比赛 | 火车票预订演示 |
| `catalog-playground/` | 任务库 playground | demo、ticketbooking（30 项测试） |
| `public-agents/demo-agent/` | 官方公开 demo agent | 回放式 agent，`template.git.bundle` 含一份完整参考实现的 24 个提交 |
| `public-agents/hackathon-starter-agent/` | hackathon starter | 官方起步 agent 和空白模板 |

每个任务目录：`requirements.yaml`/`requirements.md` 为需求，`tests/` 为评测测试，`reference/`、`assets/` 为图片，`meta.json` 为来源信息。

重新爬取某个比赛：

```sh
.venv-agent/bin/python tools/arc_fetch.py crawl -c hackathon --out tasks/hackathon
```

任务库 benchmark（`catalog-benchmark/`）和 benchmark 整包（`benchmark-bundle/`）体积大，不入库，需要时用上述工具重新下载到本地同名目录。

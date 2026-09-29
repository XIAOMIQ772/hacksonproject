# GitHub 任务：角色账号未定义

任务：`hackathon--github`（TASK-011，GitHub Collaboration Platform Core Requirements）
核查日期：2026-09-29

## 结论

需求要求应用预置多种角色账号，并按角色验证权限，但只给出了一个完整账号（用户名、邮箱、密码）。其余角色账号既没有用户名，也没有密码。评测测试与应用必须使用同一组账号才能完成登录，因此依赖这些角色的场景，任何按需求实现的应用都无法确定地通过。

## 1. 需求要求应用预置角色账号

根节点描述：

> Values described as existing accounts, organizations, teams, repositories, … and permission relationships are predefined seed data. The application must provision those records before the corresponding scenario and supply each account through an isolated browser session; they are not extra features that a participant must expose through a private API.

REQ-6 描述：

> role accounts, branches, PRs, and mutable state must be provisioned and restored independently for each scenario, including repeated and parallel runs.

原子需求中共有 7 处以 “Seed data supplies …” 描述所需角色，均未给出账号标识，例如：

- “Seed data supplies a Maintain account and separate Open PRs for success and refusal.”
- “Seed data supplies a non-author Write reviewer, an Open reviewable PR …”
- “Seed data supplies an Admin, a distinct non-Admin collaborator, and a currently private repository …”
- “Seed data supplies the author and a separate Read viewer, an authored Open PR …”
- “Seed data supplies a contributor with Write permission, …”

## 2. 需求只定义了一个完整账号

- `alice-dev`：给出了用户名、邮箱 `alice.dev@example.test`、密码 `Valid-password-123!`。
- `bob-reviewer`：出现了用户名，全文未给出密码。
- Owner、Admin、Maintain、Triage、Write、Read 等角色，以及 author、reviewer、viewer、contributor、collaborator 等身份：均未给出用户名和密码。

按关键词统计（47 个原子需求，100 个场景）：

| 范围 | 原子需求 | 场景 |
| --- | --- | --- |
| 需要以某种角色登录后操作 | 32 | 64 |
| 其中至少出现一个具名账号 | 20 | 44 |
| 其中完全没有具名账号 | 12 | 20 |

至少出现一个具名账号的场景，往往也同时需要其他未具名角色。例如 REQ-6-6 需要 PR 作者和一个 Read 权限的查看者，需求只出现了 `bob-reviewer`。

## 3. 已核查的材料

以下材料中均未找到其他账号的用户名或密码：

- `requirements.yaml`、`requirements.md`、`requirement.txt`
- 比赛页面提供的需求下载包
- 比赛详情和任务详情接口返回的内容
- 官方 starter agent 及其模板
- 需求引用的 27 张参考图（均为 GitHub 界面截图，截图中的账号与任务无关）

## 4. 与评测结果一致

截至 2026-09-29 的排行榜：

| 任务 | 最高通过率 | 实际调用模型生成的队伍中的最高通过率 |
| --- | --- | --- |
| sheet | 99% | 90% |
| github | 42% | 24% |

两个任务的需求规模和测试数量相当，github 的通过率却明显偏低。我方按需求完整实现并预置了全部具名数据的参考应用，在 sheet 上达到 91%，在 github 上为 16%。这一差距与“部分场景依赖未公开账号”的情况相符。

## 5. 待主办方确认

1. 各角色场景使用的账号：用户名、邮箱、密码，以及每个账号的角色和所属组织、团队、仓库。
2. `bob-reviewer` 的密码。
3. “provisioned and restored independently for each scenario” 的预期实现方式：
   - 是否要求每个浏览器会话获得独立的数据副本；
   - 或者评测在场景之间重启应用、重置数据库。

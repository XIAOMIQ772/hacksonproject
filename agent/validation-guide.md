# 编写验收检查

原始需求是预期结果的来源。自测通过后，执行器会开启独立需求复核。

## 行为测试

在 `backend/agent-smoke-tests/*.spec.js` 中编写 Playwright 测试，标题包含原始需求编号。
每个原子需求至少有一个实际执行的行为测试。通过可见界面准备状态，再断言结果、失败、取消、刷新和对象隔离。
保留原始编号及分隔符。使用唯一测试数据，避免同一套测试内互相污染。

验证器会运行构建、初始化数据和两个浏览器测试套件。每个套件使用独立数据库和服务；套件内测试共享数据库。
整个用例的上限是 30 秒，断言上限是 3 秒。测试必须通过正常启动入口工作，服务端应响应 `/api/health` 和首页。
遵守 `ARC_DB_FILE`，正常启动执行幂等初始化，前端构建输出为 `frontend/dist/index.html`。

## UI 契约

把原文要求的精确控件和必要前置操作写入 `.arc/ui-contract.json`：

```json
{"cases":[{"name":"场景名称","req_ids":["REQ-1-1-1"],"path":"/","steps":[
  {"action":"click","roles":["button"],"name":"原文按钮名"},
  {"action":"fill","by":"label","name":"原文输入框名","value":"测试输入"},
  {"action":"assert","roles":["heading"],"name":"原文标题"}
]}]}
```

支持 `assert`、`assertText`、`assertAbsent`、`assertDisabled`、`assertEnabled`、`assertAttribute`、
`click`、`fill`、`check`、`uncheck`、`press`、`select`、`dblclick`、`contextmenu`、`reload`。
`fill/select/assertAttribute` 需要字符串 `value`；`press` 需要 `key`；`assertAttribute` 需要 `attribute`。
`select` 的 value 是原生选项标签。`reload` 无需 name。每个场景必须包含可见结果断言。
控件使用原文精确角色和名称；密码框用 `by: "label"`。同名控件用 `scope: {"role":"dialog","name":"弹窗名称"}` 区分。
动态名称替换为实际测试对象名称。`.arc/requirement-ui-obligations.json` 提供提取结果，
`.arc/ui-review.json` 列出需要回读原文的动态、否定或歧义条款。

## 修改测试与完成条件

调用 `verify`。失败时根据原文定位应用缺陷或错误预期，记录修改依据。
尚未全部通过的自编写测试可以依据原文修正；验证执行期间禁止改写测试及 helper。
全量通过后保留基线，可新增覆盖；独立需求复核阶段会重新建立一次基线。
完整源码、失败证据和冻结基线会随会话保留。自测结果不代表平台正式评分。

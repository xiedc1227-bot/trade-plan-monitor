# 日线计划恢复检查点

> 2026-10-02范围已变更：用户授权删除日线券商订单/部分/未知跟踪，改为显式原子整手模拟。本文件记录此前范围，其完成/测试结论不批准新清理。请依据[当前清理契约/任务](2026-10-02-daily-plan-simulation-cleanup.zh-CN.md)及修订后的canonical规格继续。以下历史证据保留。

英文规范版本：`daily-plan-resume.md`；本文件为对应中文审阅副本。

## R01. 用户已恢复

2026-10-01，用户曾暂停任务以关闭计算机，随后已明确恢复并撤销暂停。现已授权按下述收紧范围继续。全部本地未提交改动已保留；未提交、推送、部署，也未针对真实数据启用计划。

## R02. 范围与授权

在 `trade-plan-monitor/` 完整实现日线计划链路。阅读 `SPEC-daily-plan.md` 及中文副本、能力图和 `tasks/daily-plan-plan.md` / `daily-plan-todo.md`。原始来源：`../docs/TradingAgents/reports/新提示词.txt`（相对于本仓库）；不得修改或虚构其中缺失的策略参数。实际历史计划仍不完整且未启用。`suspension_confirmation_policy` 必须逐计划明确选择，没有默认值。

恢复后的范围将基本面完全移出新增日线监控：仅由用户在生成交易计划时审核。原文基本面/公告条款保留为非监控背景，不形成条件、买卖门槛、风险触发、执行阻断或公告核验要求，也不得改名为技术人工事实。可交易/停牌证据保留。指数暂不处理，保持全部既有指数行为。原模板不改；用户本次明确范围覆盖其旧三风险要求。

本次修订的代理顺序：`gpt-6-astra/high` 增量契约设计、`gpt-6.1-sol/high` 实现、`gpt-6-astra/high` 全新上下文独立审查、Sol 修复、Astra 复查，直至问题解决。此前设计/实现不能视为修订范围已验收。恢复后无需再次请求阶段授权。不得向其他 Codex 聊天发消息、提交、推送、部署、调用实时行情/AI/通知服务，或读取生产数据与密钥。

## R03. 已保存实现与验证

开始时工作区在 `b2572b6` 且干净。改动包括 Schema 4 日线契约与校验、`daily-ta-v2`、认证日线/QFQ 数据准入、持久信号和风险分支、实际成交记账及增量迁移 `0024`、生产调度/runtime/outbox 接入、v7 提取、独立人工补充、审核绑定启用、九个新 API 路径以及 `/daily-plans` Vue 页面。旧 Schema 1/2/3 和 prompt v1–v6 是兼容边界。许多文件未跟踪，审查必须同时查看 `git diff` 和未跟踪文件内容。

暂停前已报告的历史验证结果（全部早于本次范围修订，不能证明修订实现已通过）：

- 旧兼容性定向测试：351 passed。
- 日线测试 glob：150 passed，15.79s（包含导入的已有 fixtures，并非 150 个独立新增用例）。
- 独立安全边界文件：14 passed；迁移兼容组：115 passed；OpenAPI 快照组：14 passed。
- 前端：824 passed；类型检查通过；最终纯展示补充之前构建通过，最后一次重建结果仍需确认。
- 真实浏览器旅程：1 passed，8.9s，零控制台 warning/error 和失败请求。覆盖粘贴原文、实际 v7 不完整提取、补充缺失技术条件、独立人工证据、审核启用、CORE 100 / TACTICAL 0、UNKNOWN 100 后核实撤销、实际 40+60 成交、官方可交易/基本面事实立即触发同一 runtime 风险评估、过期及原文修改使绑定失效。
- 暂停前全 `src tests` Ruff、compileall 和 diff 空白检查通过。
- 较早的完整运行：5926 passed、22 failed、1 skipped、4 deselected，3324.78s。失败项随后已处理（迁移预期/OpenAPI），但这不是最终完整回归通过的证据。
- 后来仅排除 `tests/integration/test_backtest_acceptance.py` 的快速回归在暂停时停止，没有最终结果。其中最初旧 partial-extraction fixture 的失败已补 `dailyMapping: null` 并通过单独复测；恢复后重新运行。

修订前生成 OpenAPI SHA-256（历史记录）：`aa19f9a453ddf003fd2faecdd99285e12dc41a149891abf8b35d799c6ee3aedc`；60 个路径 = 旧 51 + 新 9。API 变化后重新生成并检查两个契约版本。

## R04. 恢复顺序与未完成工作

1. 检查当前工作区，保留所有改动。阅读本检查点、修订后的双语规范和P06/T04。旧代理/进程ID仅描述暂停检查点，不假定仍可用。先完成Astra增量契约修订，再由Sol修改实现。
2. Sol high实施P06/T04：未发布Schema 4/v7收紧为两个技术分支；移除基本面/公告事实、runtime/UI/API门槛及原文审核阻断；保留精确排除跨度和混合句技术覆盖；更新生成契约及夹具。保持旧schema/prompt/指数行为。不兼容开发草稿保留原文/审计证据，需重新提取/新审核，不自动转换或扩大迁移。此前审查冻结不再阻止本次已授权修订。
3. 修订实现及定向验证后，启动全新上下文Astra high独立审查。此前 `/root/final_review` 中断且无结论，目前没有审查批准。核查排除边界（含预览、混合句、嵌套事实及批量人工补充）、保留的技术/可交易行为、独立事件复用、风险范围/重评、晚到/修订收盘及复权基准、原文/值绑定、发送时数量/报价、目标完成及API/UI校验。通过Sol high修复，再由Astra high复查。
4. 完成双语 README/入口链接、任务勾选和验收报告，将修订后的DP-A01–DP-A20逐条关联精确测试。DP-A15/DP-A19现为证明基本面及公告检查不存在的反向测试，不能复用旧正向风险验收。实现代理已开始整理文档，但尚未确认最终日线验收报告。不得将计划中或中断的测试记为通过。
5. 审查修复稳定后，运行最终完整 `.venv/Scripts/python.exe -m pytest -m 'not live' -q`，包含 `tests/integration/test_backtest_acceptance.py`（容量用例较慢，较早完整运行约 55 分钟）。不得降低 skip、断言、阈值或 marker 要求。相关改动后运行适当的前端/类型/构建/浏览器及生成契约检查，记录实际结果。
6. 检查中英文一致性，给出简洁中文最终报告。离线合成 fixtures 不代表真实供应商认证或实际计划已获批准。

## R05. 本地证据位置

浏览器截图位于 `C:/Users/xiedc/AppData/Local/Temp/trade-plan-monitor-playwright-results/daily-plan-daily-user-revi-e730d--and-expiry-use-real-SQLite-chrome/`：`daily-current.png`、`daily-review.png`、`daily-official-risk.png`。临时产物关机后可能消失，必要时重新运行浏览器测试。

在暂停检查点，两个活动代理均已中断，并已识别本任务的快速pytest进程以停止；现有用户应用和编辑器进程保持不动。这是历史进程信息，不代表当前仍暂停。关机后不要依赖旧工具会话ID。

## R06. 恢复后审查完成的源码冻结

2026-10-01 范围修订与完整链路已实现。全新上下文 Astra/high 审查经 Sol/high 修复及独立复核后关闭 F1–F11，含实际稀疏日历生产恢复（1500天请求、1044运行时日期、500认证 bars）。源码冻结；不要从 R03/R04 重启开发，不要假定其旧结论/进程状态仍有效。未修改的原始模板是参数缺失负例，不是已启用计划。

当前证据见[验证](../docs/verification/2026-10-01-daily-plan.zh-CN.md)与[独立审查](../docs/verification/2026-10-01-daily-plan-independent-review.zh-CN.md)。新鲜定向结果：compatibility351/3.75s、daily-unit290/5.14s、critical group88/23.55s、accounting2/0.99s、OpenAPI14/8.80s；重叠组不表示新增用例数量。协调代理最新前端：60 files/828 passed/6.55s，类型检查及两版构建通过。两条真实 Chrome 流程通过。Ruff、compileall 和两版生成检查通过。公开 SHA-256：v1 `69109c2620cca5c6467753a459e9c033faaa22862d7f68ba8dec19b8c717220b`，v2 `027cafb61579a33e006bcf5874524c54e976715e166d6eea6029a5503513f484`。

最终完整离线后端结果：**6065 passed,1 skipped,4 deselected,1 warning in3208.19s (0:53:28), exit0**，命令 `.venv/Scripts/python.exe -m pytest -m 'not live' -q`；日志 `$env:TEMP/daily-plan-final-backend.log`。唯一警告为已有 StarletteDeprecationWarning。之后 `tests/integration/test_daily_sparse_calendar_regression.py` 另行1 test/5.94s通过，Ruff通过；它未包含在6065全量收集中。DPT09/C4 和 T04 最后一项已勾选，双语文档已完成。未实时调用、读取生产密钥/数据库、提交、推送、部署或批准原文计划。本工作已完成；没有新改动或失败时，不恢复旧 fast 进程 ID 或重复完整运行。

## R07. 当前模拟清理检查点

2026-10-02已授权清理取代R03–R06历史记录中的券商扣账。当前实现采用隔离聚合POSITION/SIMULATION记录、固定100股整单事务及当前权限校验，不同步共享真实持仓。C1–C7经独立复验关闭。当前日线定向组合229项通过/53.08s；最终单字段/聚合传输安全上限及模型组合8项通过/1.56s。更新当前路径、摘要预期及双语指纹后，OpenAPI检查14项通过/8.94s。这些重叠组合不能相加称为新增用例数量。

最后解析与schema更新后，前端62文件、865项通过/6.21s；类型检查及standard/runtime-status-preview/legacy-test构建通过；真实Chrome原文/刷新审核及整单模拟流程2项通过/14.0s，无控制台错误或失败请求。两版生成契约current；v1 `fd241fa2d7d804ca66ed8277014720795b47044fb143e3076146a5b8a81e80f5`，v2 `6216e2992e10532d3d83989ab1a3cebf61d78e2b36deb7bb3d728a190a709f99`。协调者已完成当前覆盖门禁：首次全量6081项通过/1失败/1跳过/4未选择/1警告，耗时3279.22s；严格的三行纯测试契约修正后160项定向通过；最终非容量复跑6074项通过/1跳过/4未选择/1警告，耗时1204.62s，八项未变容量测试已在完整运行中通过。见[最终验证](../docs/verification/2026-10-02-daily-simulation-cleanup.zh-CN.md)。不得以R06的6065冒充当前验收，也不把两次运行称为单次全量全绿。业务源码冻结，仅真实新问题可触发改动。

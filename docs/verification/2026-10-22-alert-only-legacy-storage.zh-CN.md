# 仅提醒草稿与历史模拟存储限制 — 2026-10-22

## ALERT-LEG-001 — 精确触发原因

实际数据库中，`605296.SH` 的 `daily_plan_record` 只有两条记录：
`EXTRACTION` 和 `REVIEW`。该股票没有持仓、模拟交易、成交报告、信号、
风险或评估记录，也没有已启用计划绑定。

触发点是现有表的 `ck_daily_record_kind` 约束：允许的类型没有 `SIMULATION`。
`DailyAccounting.legacy_reason` 在检查个股记录前就识别到这个数据库级条件，
返回 `DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED`。数据库迁移版本为
`0025_index_close_display`；保留的表约束早于当前 `0024_daily_plan` 迁移定义。
服务启动时不会再次执行已经登记的迁移版本。

这项模拟存储限制有实际依据，不表示该股票存在历史模拟持仓。
本次没有迁移或修补表约束和记录。

## ALERT-LEG-002 — 对技术提醒的影响

运行引擎的 `_alert_only` 路径独立处理只有提醒、没有普通规则和风险分支的
Schema 5 政策，使用未知库存投影，不创建持仓。投递校验同样将 `REMINDER`
与模拟交易资格分开处理。人工审核、启用绑定、有效数据、确认方式、
当前证据和通知有效期校验均继续生效。

隔离数据库复刻了不含 `SIMULATION` 的原约束。合成的已审核、已启用日线价格
提醒恰好产生1条 `REMINDER`，通过 `daily_delivery_allowed`，没有买卖信号
或风险退出；重复评估不重复生成事件。在没有历史报告和保留历史报告两种情况下
均通过，旧报告的版本号和原始内容保持不变。库存初始化和模拟交易请求
仍返回 HTTP 409。

用户的实际草稿仍未审核、未启用，因此当前不监测、不发出提醒。
旧模拟约束不会额外阻断这份纯提醒政策，但这不豁免正常审核和数据检查。
测试中的审核／启用只发生在隔离的合成策略夹具中。

## ALERT-LEG-003 — 显示修复与组件边界

股票运行状态接口根据已启用政策决定是否适用纯提醒例外；没有已启用政策时，
它仍可能保留模拟兼容性原因。此前 `PlanSimulationPanel` 将这个股票级结果
直接显示成所选草稿的计划状态，容易误导为草稿本身无法使用技术提醒。

现在面板根据所选已保存版本的 `version.planJson` 和审核绑定派生展示内容。
Schema 5 纯提醒草稿分别显示 `仅提醒草稿：待审核，尚未启用` 或
`仅提醒草稿：已审核，尚未启用`。模拟库存提示单独说明兼容性限制，以及
纯提醒不依赖模拟库存；同时明确未启用版本不会进行提醒监测。

`PlanWorkbench` 继续传入不可变版本及请求函数；`PlanSimulationPanel` 仅增加
纯计算的展示状态；`PlanOperationForm` 及其阻断行为不变。
这项小范围显示修正不需要新增组件或组合式函数。无效、不完整、历史格式、
含普通交易或风险分支的政策不会得到纯提醒标签。真实请求错误和保留的
技术风险历史仍然显示。

没有修改后端响应、历史数据判定、数据模型、审核／启用门槛、表单保护、
模拟交易权限、账户数据或原始 AI 输出。

## ALERT-LEG-004 — 回归结果

| 检查 | 实际结果 |
| --- | --- |
| 修复前的前端回归 | 3 failed、17 passed |
| 修复后的前端回归 | 20 passed，含新增9例 |
| 前端完整单元测试 | 83个文件共1215 passed |
| 相关后端回归选择 | 84 passed，含新增3例历史存储测试 |
| TypeScript 检查／生产构建／Ruff | 通过／通过／通过 |

前端覆盖待审核、已审核但未启用的草稿，模拟库存受保护时的已启用提醒，
请求正文和属性不变，普通／风险政策仍受限制，不完整／无效／历史文档，
以及真实读取错误。后端复刻旧表约束，验证审核前不监测、价格提醒评估及
投递资格、旧报告内容保留、拒绝模拟操作，以及实际／模拟库存不变。
所有测试数据库均与真实监控数据库隔离。

```powershell
# 在 web/ 中执行
npm test -- --run tests/unit/dailySimulation.spec.ts
npm test -- --run
npm run type-check
npm run build
# 在项目根目录中执行
.venv/Scripts/python.exe -m pytest tests/integration/test_alert_only_legacy_storage.py tests/integration/test_unified_runtime.py tests/integration/test_daily_simulation_review_regressions.py tests/integration/test_plan_read_timezone.py tests/unit/test_daily_safety_boundaries.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_alert_only_legacy_storage.py
```

后端结果仅代表所选回归范围，不代表整个后端套件。
这些测试没有调用外部 AI、行情或通知提供商。

## ALERT-LEG-005 — 实际页面与保留证据

已将生产前端重新构建至现有工作区输出目录，并重新加载实际已保存草稿页面。
页面现在分开呈现待审核草稿和模拟兼容性状态，没有替换服务或原数据库。

| 实际验收项 | 结果 |
| --- | --- |
| 草稿 | `SNGC-OBS-20261022`，版本1，`DRAFT` |
| 技术提醒 | 1条；官方日线收盘价严格低于固定 `2659` `FEN` |
| 买入／卖出／风险清仓规则 | 0／0／0 |
| 原文及计划哈希 | 不变 |
| 审核 | `review_id=null`、`review_revision=0`、`confirmed_at=null` |
| 启用 | 无启用绑定；启用按钮禁用 |
| 原有两条每日记录 | ID、类型、版本号及内容哈希均不变 |
| 存储约束 | 不变，仍不允许 `SIMULATION` |
| 实际／模拟库存、风险和激活保护快照 | 前后完全一致 |

证据位于 `evidence/2026-10-22-alert-only-legacy-storage/`：
`trigger-analysis.json`、`acceptance.json`、`protected-before.json`、
`protected-after.json`、`test-results.json` 和 `draft-state-separated.jpg`。
原人工研究附件和 AI 验证归档仍保存在
`data/research/SNGC-OBS-20261022/validation-20261022-115118/`，内容未改动。

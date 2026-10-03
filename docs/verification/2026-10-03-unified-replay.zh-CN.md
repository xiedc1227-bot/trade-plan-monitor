# 统一计划回放验证

## V01. 范围与审核

日期：2026-10-03，Asia/Shanghai。基线：`6118569`。本报告覆盖 [UR01–UR08](../specifications/backtesting/SPEC-unified-replay.zh-CN.md)、实施 [S1–S7](../../tasks/unified-replay-plan.zh-CN.md)及[可用本地指南](../operations/unified-replay.zh-CN.md)。状态：**LOCALLY_VERIFIED**。父会话最终独立审核：在 UR01–UR08 及声明限制内 **PASS**。变更均在本地且未提交。未使用生产数据库/配置、外部供应商/AI、通知投递、真实订单、提交、推送或部署。

父 Astra/high agent 负责方案、范围及独立审核。明确选择的 Sol/high 实施 agent 遇到两次容量失败。独立接续子 agent 使用继承的父配置完成其余顺序实施；没有并发代码编辑者。父审核发现并核验了提醒投影缺失、操作前后状态混淆、500 occurrence 查找限制、资金安全整数溢出、时间规范化、可读信号阻断、有界日历上下文及取消阶段兼容问题的修复。

Schema 5 运行使用 `backtest-run-v4`、报告 `backtest-report-v3`、强类型决策/操作/权益详情、摘要导出 `backtest-report-summary-v4` 及估值 CSV `explicit-simulation-valuation-v1`。保留既有持久化 v2 外层及集合哈希域。当前监控应用明确整单模拟；独立纯费用/滑点投影不能缩量或授予权限。未知库存与研究现金不足保留 null/无效估值。旧导出不变。UUID 规范序列化仅补充支持已有的计划版本查找元数据，不增加语义身份要素。

## V02. 按要求列出的验收证据

| ID | 已执行当前证据 |
|---|---|
| UR-A01 | `test_unified_replay_input.py` 拒绝缺失/不匹配研究声明、非布尔确认、未知库存带批次及不支持假设。`test_unified_replay_entries.py` 拒绝未审核/缺失/不匹配权限，并提交桶上限可选的服务器已审核未激活计划。 |
| UR-A02 | 既有字节/往返兼容测试保持通过。当前身份随输入改变。未来行情测试修改之后的日线收盘，把已经可用的证明重新绑定到新数据集，比较此前所有事件，包括身份和状态。 |
| UR-A03 | `test_unified_replay.py` 测试缺失/明确日线证明、限定范围的延迟否定/肯定事实及未来正式证明拒绝。边界测试覆盖可见但未完整的五分钟桶、日内预热、不兼容分钟接收延迟拒绝、512 行日历上下文及真实两日的日线执行。另加单一 `ALL(daily, minute, fact)` 树，拒绝早盘事实，在正式收盘后接受否定再肯定事实，只在肯定事实到达时确认，并因交易时段已结束而不可执行。 |
| UR-A04 | 边界覆盖 `PLAN_ACTIVE`、包含端点的 `DATE_RANGE`、激活窗口、下一交易日日线执行、次日分钟过期、第二个独立 occurrence，以及无明确证据不重复。 |
| UR-A05 | 当前测试覆盖停用/已审核替换、风险义务跨终止保留、明确重评及之后评估保持已消费风险证据解除。独立公开 oracle 另存后继草稿并核验原权限仍激活。 |
| UR-A06 | 实际提醒结果/原因/确认证据不产生库存变化。肯定/否定技术事实保持范围。混合分钟/日线/风险一致性覆盖风险不可用时阻断明确请求，随后零目标严重风险已履行并抑制普通日线确认。 |
| UR-A07 | 当前回放场景断言整量、重复消费、部分拒绝、T+1、CORE、最大持仓和未知库存。存储账本测试解析第 501 个 occurrence。累计资金费用超过安全整数时明确失败。 |
| UR-A08 | `test_unified_replay_parity.py` 独立重建可见分钟前缀、完成目标、报价及核验日线输入；激活另一个真实临时当前监控器；使用公开模拟接口。逐事件比较规范化信号、风险、动作与库存。仅去除存储身份与版本计数：公开变更会在同刻额外重评。证据、确认时间/窗口、阻断和数量仍参与比较，并有独立成功/阻断操作预期。 |
| UR-A09 | 校验报告/JSON/CSV 重复字节、未来事实和未来行情/证明重绑定。回放中途取消返回强类型取消结果。真实 API 在一个已评估事件后取消，达到 `CANCELLED`，无结果且不发布运行。 |
| UR-A10 | 真实本地 CLI 和临时 API→持久任务→读取/权益/导出成功。幂等提交返回同一任务；worker 不得重读实时计划权限。guard 在供应商/AI/socket/实时生命周期/outbox/投递访问时失败，并检查隔离运行数据库清理。浏览器表单/详情覆盖使用实际服务端投影字节，检查可访问性、控制台及外部请求。 |

oracle 比较分别编排的存储与公开操作，不是两次调用研究适配器。其严重分支库存明确为零，因此零目标正确达到 `FULFILLED`；独立的锁存风险场景以 100 股战术库存开始，验证停用期间 `CONFIRMED` 及明确解除。合成计划是完整研究输入，不是从不完整春秋航空原文重建，也不属于真实 AI 验收。

## V03. 最终命令与结果

Python 命令从 `trade-plan-monitor/` 执行，前端命令从 `web/` 执行。以下数字属于独立命令；重叠测试不相加为虚构总数。

| 命令 | 结果 |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 2744 passed，4 deselected，1 条既有 Starlette/httpx 弃用警告；21.94s。取消选择的是 `live` 测试。 |
| `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_compatibility.py tests/integration/test_backtest_exports.py tests/integration/test_backtest_results.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_result_api.py tests/integration/test_backtest_export_api.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_publication.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_jobs.py tests/integration/test_unified_runtime.py tests/integration/test_unified_simulation_transactions.py -q -m 'not live' -rs` | 246 passed，1 skipped，1 条既有警告；46.13s。跳过：`test_backtest_production_composition.py:501` 需要 POSIX 所有权语义。 |
| `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_replay.py tests/integration/test_unified_replay_boundaries.py tests/integration/test_unified_replay_parity.py tests/integration/test_unified_replay_entries.py -q -m 'not live'` | 37 passed，1 条既有警告；125.52s。此为收窄在线默认提醒门槛修正前最终候选；定向回归另记如下。 |
| `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_runtime.py tests/integration/test_unified_replay_boundaries.py::test_reminder_only_has_actual_evidence_without_inventory_or_authority_outside_window tests/integration/test_unified_replay_parity.py -q -m 'not live'` | 收窄在线默认提醒门槛修正后 26 passed，1 条既有警告；37.66s。 |
| `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_replay_boundaries.py::test_mixed_tree_needs_daily_minute_and_delayed_positive_fact_at_one_cutoff -q -m 'not live'` | 1 passed；3.54s（实施），父会话独立 1 passed、3.50s。在 37 用例候选之后补入，生产代码不变。 |
| `.venv/Scripts/python.exe -m ruff check src tests scripts` | 通过。 |
| `.venv/Scripts/python.exe -m compileall -q src` | 通过。 |
| `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | 通过：规范 v2 与兼容 v1 产物同步。 |
| `npm run test -- --run` | 57 文件、807 测试通过；6.21s。 |
| `npm run type-check` | 通过。 |
| `npm run build` | 通过。 |
| `npm run test:e2e -- tests/e2e/backtests.spec.ts` | 6 passed；22.8s。Chrome 路由、键盘/axe、当前研究、任务提交、布局及渲染/轮询边界检查。 |
| `git diff --check` | 最终文档交接时通过。 |

最初前端测试被误与生产 build 并发安排，build 替换 `dist` 产物时出现一个 `runtimeStatusBuild` `ENOENT`。父会话在 build 完成后顺序重跑，全量 807 通过。没有为这次编排竞态修改代码或削弱断言。[回测验收](backtest-acceptance.zh-CN.md)保留既有高成本容量证据；未重跑，也未重标为当前回放验收。

独立变异检查：父会话在内存中暂时把 `_confirmed.__code__` 换为强制转换实现。`test_review_true_is_never_coerced` 出现预期的 1 failed / 2 passed，捕获数值 `1` 被作为确认接受。进程退出后无源码变异残留。

## V04. 可复现合成运行与限制

两个 agent 分别独立执行了 `scripts/create_unified_replay_fixture.py --output <fresh-temp-directory> --run`。生成器和两个真实 CLI 运行成功。重开生成结果验证每次运行有 49 个强类型决策及真实分钟/日线信号，不只是空执行成功。空脚本维持 1,000,000 分权益、零交易。

- 数据集：`1704a62d8d35a08dceae6a6d62d8204b61d247ec6b6a9fb90a7f85d32881c752`。
- 分钟运行：`1bda3c0df33375d5470ee3403f283aaa11efe0b6447c798fa9482ceffc7ac44f`。
- 日线运行：`ae604335984e58851d43af35821901d15c54ca6174849b4187dab9cba16d4bf4`。

日线状态使用 `confirmed_trade_date`；正式日线确认的 `confirmed_at` 为 null。CSV `monitor_status` 与 `valuation_status` 有意区分回执应用和资金投影。`FULL_SESSION_SUSPENSION` 仍明确不支持且可见。数据集接收宽限仍是历史 profile 假设，不是真实采集认证。复权/交易日/报价证据缺失会阻断。不声称真实原文计划、生产迁移、实时供应商、通知、券商或部署已获验收。

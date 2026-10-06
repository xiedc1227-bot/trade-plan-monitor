# 当前任务清单：监控闭环回测

> 待实施，2026-10-06。实施方案：[plan.zh-CN.md](plan.zh-CN.md)；英文权威清单：[todo.md](todo.md)。ML-T01–ML-T29 均未实施。其后保留此前已完成的历史清单。

所有命令从 `trade-plan-monitor/` 执行；标出的新文件是预期产物。验证命令在对应实现后执行，本次编写文档不代表已运行。每项约五个主要文件以内，超出时先拆分。生成契约/批准摘要分别处理，不能为通过检查静默批准 API。

## ML-T01. 定义冻结闭环输入与时间边界

- [ ] 完成实现和本项验证.
- **依赖:** 无
- **验收:** 严格版本化输入区分原文/激活/结束时间、账户成本/市值及零/未知现金；校验建议上限，不改变旧编码。同版本沿用和结束日期解析确定。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_input.py`, `src/trade_plan_monitor/backtest/plan_schedule.py`, `tests/unit/test_monitor_loop_input.py`, `tests/unit/test_monitor_loop_schedule.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A04, ML-A09, ML-A11, ML-A12, ML-A15.

## ML-T02. 提取共用模拟参与者

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T01`
- **验收:** 将现有授权/数量/持仓转换封装为应用参与者，由调用方控制事务；在线命令和旧回放的回执、错误与行为保持一致。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_simulation_participant.py tests/integration/test_unified_simulation_transactions.py tests/integration/test_unified_replay.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/state/simulation.py`, `src/trade_plan_monitor/web/daily_service.py`, `src/trade_plan_monitor/backtest/research_session.py`, `tests/integration/test_simulation_participant.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A05, ML-A08, ML-A09.

## ML-T03. 在私有闭环会话记录提醒

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T01`, `ML-T02`
- **验收:** 使用共用监控/发送资格、隔离仓储和确定时钟/身份；记录有效提醒，拒绝陈旧证据。纯技术提醒不授权执行，不创建真实发送出口。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_unified_runtime.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_session.py`, `src/trade_plan_monitor/backtest/reminder_capture.py`, `src/trade_plan_monitor/runtime/daily_service.py`, `tests/integration/test_monitor_loop_reminders.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A02, ML-A03, ML-A06, ML-A08.

### ML-C01. 检查点

- [ ] 共用监控参与者保持在线行为。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T04. 原子提交账户与库存

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T02`, `ML-T03`
- **验收:** 精确计算费用/滑点，先检查完整数量现金，再以同事务写资金、批次、信号消费和回执。保留期初成本 401050 分；失败/重复提交不得产生部分或重复影响。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_costs.py tests/integration/test_monitor_loop_account.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_account.py`, `src/trade_plan_monitor/backtest/loop_session.py`, `tests/unit/test_monitor_loop_costs.py`, `tests/integration/test_monitor_loop_account.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A05, ML-A09, ML-A12, ML-A13.

## ML-T05. 运行单计划提醒响应闭环

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T01`, `ML-T03`, `ML-T04`
- **验收:** 已审核夹具无需交易脚本即可发现买卖时点；执行后续合格区间、风险优先级、单次消费及有限上限。观察/历史操作模式不添加未要求交易。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_cycle.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_runner.py`, `src/trade_plan_monitor/backtest/response_policy.py`, `tests/integration/test_monitor_loop_cycle.py`
- **范围:** M (3 个主要文件，含测试); **追溯:** ML-A01, ML-A02, ML-A03, ML-A04, ML-A06.

## ML-T06. 跨每日计划更新继续回放

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T05`
- **验收:** 在当天合格操作前切换，继承账户/风险并使旧普通意图失效；仅沿用有效计划，同版本不重置。后续仓位文字不能覆盖账本。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_plan_switch.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/plan_schedule.py`, `src/trade_plan_monitor/backtest/loop_session.py`, `src/trade_plan_monitor/backtest/loop_runner.py`, `tests/integration/test_monitor_loop_plan_switch.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A07, ML-A11, ML-A13.

### ML-C02. 检查点

- [ ] 已审核夹具完成单计划和每日计划链闭环，账户更新原子。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T07. 持久化准备批次与修订状态

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T01`
- **验收:** 建立独立标记准备库，保存有界原文、逐项尝试、修订和幂等，拒绝跨域路径。状态支持重启，批准与校验保持分离。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_store.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/preparation_models.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_store.py`
- **范围:** M (3 个主要文件，含测试); **追溯:** ML-A16, ML-A18.

## ML-T08. 基于有界前版上下文提取单份计划

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T07`
- **验收:** 版本化首份/后续输出契约，复用供应商/解析防护并保留原文范围。请求仅含当前原文及必要前版证据；语义缺失保留未解决，旧单份提取不变。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_plan_update_extraction.py tests/unit/test_current_plan_extraction_security.py tests/unit/test_ai_plan_extraction_v4.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/ai/plan_update_extraction.py`, `src/trade_plan_monitor/ai/extraction.py`, `tests/unit/test_plan_update_extraction.py`, `tests/fixtures/ai/plan-update-cases.json`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A12, ML-A14, ML-A16, ML-A17.

## ML-T09. 形成可追溯完整计划版本

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T07`, `ML-T08`
- **验收:** 应用强类型新增/修改/撤销/保留，区分完整与增量更新，保留继承来源证据。拒绝含糊省略、无效目标和编造人工事实，输出完整快照与差异。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_plan_update_merge.py tests/unit/test_plan_update_bindings.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/plan_updates.py`, `src/trade_plan_monitor/ai/update_review.py`, `tests/unit/test_plan_update_merge.py`, `tests/unit/test_plan_update_bindings.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A16, ML-A17.

### ML-C03. 检查点

- [ ] 准备持久化、提取和原文绑定合并通过针对性检查。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T10. 安全恢复顺序提取

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T07`, `ML-T08`, `ML-T09`
- **验收:** 用代次/原文/基线保护领取条目，共用 AI 并发预算，在调用外持久化进度。仅有界重试可重试失败，取消/重启/编辑拒绝陈旧完成并保留未受影响前序。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_worker.py`, `src/trade_plan_monitor/web/ai_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_worker.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A16, ML-A18.

## ML-T11. 审核并冻结完整准备链

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T09`, `ML-T10`
- **验收:** 明确审核绑定精确原文/基线/内容/证据修订并冻结不可变清单。修正祖先使后续失效，校验不能产生批准，也不能激活生产计划。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_review.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/preparation_review.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `src/trade_plan_monitor/ai/update_review.py`, `tests/integration/test_plan_preparation_review.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A17, ML-A18.

## ML-T12. 接通准备应用接口

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T10`, `ML-T11`
- **验收:** 将有界创建/读取/编辑/提取/取消/审核接入应用所有权和启停。真实 HTTP 测试证明修订冲突、幂等、分页与虚拟 AI 进度，不修改在线计划。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/web/preparation_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_preparations.py`, `src/trade_plan_monitor/web/app.py`, `src/trade_plan_monitor/backtest/composition.py`, `tests/integration/test_plan_preparation_api.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A10, ML-A16, ML-A18.

### ML-C04. 检查点

- [ ] 真实 HTTP 配虚拟 AI 跑通重启/取消/编辑/审核。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T13. 生成准备传输契约

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T12`
- **验收:** 从挂载生产路由生成契约，测试新增区分载荷与错误结构。保留未受影响路由/类型，将 API 变化留给 ML-T29 审阅，不提前填批准摘要。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **主要文件:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_plan_preparation_contract.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A10, ML-A16.

## ML-T14. 实现批量上传与进度页面

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T13`
- **验收:** 一次上传并明确顺序，展示逐项状态/错误，提供稳定重试/取消意图。终态/卸载停止轮询，原文错误或服务端失败可见且可修正。
- **验证:** `npm --prefix web run test -- --run tests/unit/PlanBatchPreparation.spec.ts`
- **主要文件:** `web/src/api/preparations.ts`, `web/src/composables/usePlanBatch.ts`, `web/src/components/backtests/PlanBatchSourceForm.vue`, `web/src/components/backtests/PlanBatchProgress.vue`, `web/tests/unit/PlanBatchPreparation.spec.ts`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A10, ML-A16, ML-A18.

## ML-T15. 预览并审核已准备计划日历

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T14`
- **验收:** 展示期初账户、规则差异、来源证据、生效日历与未解决条款。仅精确服务端已审核修订能继续，祖先编辑明确使受影响后续失效。
- **验证:** `npm --prefix web run test -- --run tests/unit/PlanBatchReview.spec.ts`
- **主要文件:** `web/src/components/backtests/PlanBatchReview.vue`, `web/src/views/BacktestNewView.vue`, `web/src/composables/usePlanBatch.ts`, `web/tests/unit/PlanBatchReview.spec.ts`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A10, ML-A12, ML-A17, ML-A18.

### ML-C05. 检查点

- [ ] 上传、进度和审核 UI 使用生成契约。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T16. 冻结截至明确时点的证据

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T01`, `ML-T06`
- **验收:** 末日部分时段独立表示，不标为完整交易日；校验所需已完成区间和合并计划预热。今天/节假日/延迟数据明确，旧清单字节/就绪不变。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_dataset.py tests/unit/test_monitor_loop_cutoff.py tests/integration/test_backtest_compatibility.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_dataset.py`, `src/trade_plan_monitor/backtest/dataset.py`, `src/trade_plan_monitor/backtest/market_store.py`, `tests/integration/test_monitor_loop_dataset.py`, `tests/unit/test_monitor_loop_cutoff.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A04, ML-A09, ML-A11, ML-A15.

## ML-T17. 在任务上限内保存冻结运行引用

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T01`, `ML-T07`, `ML-T11`, `ML-T16`
- **验收:** 完整已审核输入耐久保存，队列仅传 256 KiB 内已验证不可变引用。准入前复制所需产物，重试、输入缺失/损坏和准备清理不能静默改变运行。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_input_store.py tests/integration/test_backtest_jobs.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_input_store.py`, `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/jobs/models.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `tests/integration/test_monitor_loop_input_store.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A18.

## ML-T18. 以一次确定的时间边界提交闭环运行

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T16`, `ML-T17`
- **验收:** 增量提交已审核准备身份和可选结束日期，在幂等预留下冻结输入/截止。跨午夜重复请求复用原结果，拒绝陈旧审核和无效区间。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_submission.py tests/integration/test_backtest_run_api.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_runs.py`, `tests/integration/test_monitor_loop_submission.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A09, ML-A10, ML-A15, ML-A18.

### ML-C06. 检查点

- [ ] 冻结截止输入和任务引用通过重试与陈旧审核检查。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T19. 通过后台工作者执行冻结闭环输入

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T05`, `ML-T06`, `ML-T17`, `ML-T18`
- **验收:** 按输入区分值分发，沿用租约/取消所有权，只读取冻结产物。不保留回测 CLI 入口、兼容适配器或命令专用协调器。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_worker.py tests/integration/test_backtest_job_coordinator.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/runner.py`, `tests/integration/test_monitor_loop_worker.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A01, ML-A09, ML-A10.

## ML-T20. 投影因果事件与有效估值

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T04`, `ML-T05`, `ML-T06`
- **验收:** 区分评估/提醒/请求/成交/结果状态并保留因果关联。历史成本盈亏与区间收益分开，未知价格/现金、零分母不编造指标或清仓。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_report.py tests/integration/test_monitor_loop_valuation.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_report.py`, `src/trade_plan_monitor/backtest/loop_runner.py`, `tests/unit/test_monitor_loop_report.py`, `tests/integration/test_monitor_loop_valuation.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A01, ML-A03, ML-A09, ML-A12, ML-A13, ML-A15.

## ML-T21. 原子发布与保留闭环结果

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T19`, `ML-T20`
- **验收:** 流式保存强类型事件，验证输入/报告哈希，只发布完整运行。取消/失败/超限不留下已完成部分报告，保留期固定结果和导出依赖的计划链。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_publication.py tests/integration/test_monitor_loop_retention.py tests/integration/test_backtest_publication.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/jobs/maintenance.py`, `tests/integration/test_monitor_loop_publication.py`, `tests/integration/test_monitor_loop_retention.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A10.

### ML-C07. 检查点

- [ ] 工作者只发布完整且依赖保留正确的结果。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T22. 提供分页闭环结果与导出

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T21`
- **验收:** 既有结果/明细/导出路径分页提供强类型闭环事件、版本历史和截止覆盖。旧摘要/CSV/JSON 字节兼容，新投影明确区分模式。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_result_api.py tests/integration/test_monitor_loop_exports.py tests/integration/test_backtest_exports.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/backtest_export.py`, `tests/integration/test_monitor_loop_result_api.py`, `tests/integration/test_monitor_loop_exports.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A10, ML-A15.

## ML-T23. 生成最终运行与结果契约

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T18`, `ML-T22`
- **验收:** 在真实运行/结果 API 变化后重新生成，校验新旧区分载荷、上限和安全整数。批准摘要留待 ML-T29 审阅，不消除基线批准失败断言。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **主要文件:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_monitor_loop_contract.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A10.

## ML-T24. 从现有运行表单提交已准备计划

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T15`, `ML-T23`
- **验收:** 使用已审核清单和提取期初账户，无需原始操作 JSON；可选结束由服务端默认。展示解析截止、缺失事实和不支持条款，沿用任务/结果跳转。
- **验证:** `npm --prefix web run test -- --run tests/unit/MonitorLoopRunForm.spec.ts`
- **主要文件:** `web/src/components/backtests/BacktestRunForm.vue`, `web/src/composables/useBacktestRunForm.ts`, `web/src/api/backtests.ts`, `web/src/views/BacktestNewView.vue`, `web/tests/unit/MonitorLoopRunForm.spec.ts`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A10, ML-A12, ML-A14, ML-A15.

### ML-C08. 检查点

- [ ] 结果/导出 API 和运行创建兼容新旧契约。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T25. 在结果中解释计划与执行历史

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T22`, `ML-T23`
- **验收:** 将分页因果事件和每日版本轨迹接入实际结果页，区分持有、拒绝/未成交意图和已成交。展示账户演进、有效指标与实际数据截止，前端不实现交易决策。
- **验证:** `npm --prefix web run test -- --run tests/unit/MonitorLoopResults.spec.ts`
- **主要文件:** `web/src/components/backtests/MonitorLoopTimeline.vue`, `web/src/components/backtests/PlanVersionTimeline.vue`, `web/src/views/BacktestRunDetailView.vue`, `web/src/composables/useBacktestResults.ts`, `web/tests/unit/MonitorLoopResults.spec.ts`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A01, ML-A07, ML-A10, ML-A13, ML-A15.

## ML-T26. 证明一致性、因果性与故障原子性

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T06`, `ML-T11`, `ML-T16`, `ML-T21`
- **验收:** 以独立预期输出对比在线参与者与闭环状态，修改未来证据并注入事务/工作者故障。做一次关键约束变异检查，虚拟 AI/供应商/出口计数证明隔离。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_parity.py tests/integration/test_monitor_loop_faults.py tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **主要文件:** `tests/integration/test_monitor_loop_parity.py`, `tests/integration/test_monitor_loop_faults.py`, `tests/fixtures/monitor-loop/scenarios.json`, `tests/integration/test_plan_preparation_worker.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A01–ML-A18.

## ML-T27. 验证完整浏览器流程

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T24`, `ML-T25`, `ML-T26`
- **验收:** 真实挂载 API/组合配虚拟外部服务，贯通上传→重试/编辑→审核→运行→结果/导出。证明夹具未预写未来交易，不只测假结果页，不访问真实用户库。
- **验证:** `npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts`; `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_production_composition.py -q -m "not live"`
- **主要文件:** `web/tests/e2e/monitor-loop-backtest.spec.ts`, `web/tests/fixtures/monitor-loop.json`, `tests/integration/test_monitor_loop_production_composition.py`
- **范围:** M (3 个主要文件，含测试); **追溯:** ML-A10, ML-A16, ML-A18.

### ML-C09. 检查点

- [ ] 独立故障/一致性与完整浏览器流程通过。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T28. 记录操作指南与实际验证证据

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T27`
- **验收:** 双语记录实际支持的 API/UI 行为及原文限制。执行方案相关最终检查并记录真实结果、未解决失败和证据范围，不宣称真实 AI/供应商认证。
- **验证:** `git diff --check`
- **主要文件:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A01–ML-A18.

## ML-T29. 对齐已审阅规格与API批准

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T23`, `ML-T28`
- **验收:** 结合双语契约审阅最终 API/行为差异，仅记录由此批准的快照身份和最终实现范围。保留旧批准历史，明确区分此前已知基线不一致。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py -q -m "not live"`
- **主要文件:** `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.md`, `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.zh-CN.md`, `docs/specifications/monitoring/SPEC-unified-plan.md`, `docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A09, ML-A10.

### ML-C10. 检查点

- [ ] 全部 ML-A01–ML-A18 证据及已审阅双语契约完整。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

---

以下为原有已完成历史记录，保留原内容；不代表本次实现已完成。

# 任务清单：market-index-context

> 中文审阅任务清单。英文权威版为 `todo.md`；ID、文件、命令和验收标准必须一致。

> 状态：IDX001–IDX012及WEBF13已完成。本表记录历史验收范围；42路径及当时命令不是当前全量契约。当前日线与运行协议见[文档索引](../docs/README.zh-CN.md)。

## 基础

- [x] `IDX001`——实现封闭板块指数身份映射。
  - 验收：五条映射和所有非法/回退场景均确定；绑定不可变且可重新计算。
  - 验证：`python -m pytest tests/unit/test_market_index_identity.py -q`。
  - 文件：`tests/unit/test_market_index_identity.py`、`src/trade_plan_monitor/market_index/identity.py`、`src/trade_plan_monitor/market_index/__init__.py`。
- [x] `IDX002`——实现指数 K 线、规范哈希、公式和健康状态。
  - 验收：准确完整周期校验、SMA/回看/涨跌幅黄金值、问题代码和内容哈希符合规格。
  - 验证：`python -m pytest tests/unit/test_market_index_data.py -q`。
  - 文件：`tests/unit/test_market_index_data.py`、`market_index/models.py`、`market_index/canonical.py`、`market_index/formulas.py`。
- [x] `IDX003`——实现供应商边界和共用截止时间快照协调器。
  - 验收：合并请求只获取一次；相同并发键共用；板块故障隔离；不泄露供应商密钥。
  - 验证：`python -m pytest tests/integration/test_market_index_snapshots.py -q`。
  - 文件：`tests/integration/test_market_index_snapshots.py`、`market_index/provider.py`、`market_index/requirements.py`、`market_index/snapshots.py`。

## 计划判断

- [x] `IDX004`——增加明确 Schema v2 绑定和六种条件模型。
  - 验收：v1 拒绝新字段/叶子且哈希不漂移；v2 要求重算绑定和准确范围。
  - 验证：`python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_plan_domain.py -q`。
  - 文件：`tests/unit/test_plan_index_conditions.py`、`domain/plan_models.py`、`domain/plan_validation.py`、`domain/plan_codec.py`。
- [x] `IDX005`——使用准确计划路径和缺失证据判断指数叶子。
  - 验收：等号、全部策略根、三值组合、两计划分歧和无条件行为通过。
  - 验证：`python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_decision_engine.py tests/replay/test_decision_replay.py -q`。
  - 文件：`decision/models.py`、`decision/conditions.py`、`decision/episodes.py`、`decision/risk.py`、`tests/unit/test_plan_index_conditions.py`。

## 监控

- [x] `IDX006`——把共用快照注入实时判断，并分开保存最新共用/计划投影。
  - 验收：每个截止/指数一份快照、无条件故障隔离和运行证据持久化通过。
  - 验证：`python -m pytest tests/integration/test_market_index_runtime.py tests/integration/test_ten_symbol_runtime.py -q`。
  - 文件：`tests/integration/test_market_index_runtime.py`、`runtime/service.py`、`runtime/symbol_service.py`、`web/lifespan.py`。
- [x] `IDX007`——增加监控 API、历史端点、失效通知、OpenAPI 和生成类型。
  - 验收：有界安全 Schema/端点/事件和可空迁移字段通过契约测试。
  - 验证：`python -m pytest tests/integration/test_market_index_web.py tests/integration/test_openapi_snapshot.py tests/integration/test_websocket.py -q`；`python scripts/generate_frontend_types.py --check`。
  - 文件：`web/schemas.py`、`web/routers/market_indexes.py`、`web/app.py`、`web/websocket.py`、生成契约/测试。
- [x] `IDX008`——测试先行增加监控 Vue 组件和序列组合函数。
  - 验收：共用数据和计划结果明显分开；加载/故障/未使用/键盘/响应式状态通过。
  - 验证：`npm --prefix web run type-check`；`npm --prefix web run test -- --run`。
  - 文件：`web/src/components/market-index/*`、`web/src/composables/useMarketIndexSeries.ts`、总览/详情页面、单元测试。

## 回测

- [x] `IDX009`——增加 v2 指数 artifact、动态覆盖/预热、共用回放快照和 v3 运行身份。
  - 验收：禁止未来数据、实时/回放字节一致、旧黄金值不变、无条件覆盖隔离、零网络。
  - 验证：`python -m pytest tests/unit/test_backtest_index_data.py tests/integration/test_backtest_index_dataset.py tests/integration/test_backtest_runner.py -q`。
  - 文件：`backtest/index_data.py`、`backtest/dataset.py`、`backtest/market_store.py`、`backtest/runner.py`、测试。
- [x] `IDX010`——持久化/投影回测指数证据，增加序列 API，并版本化正式导出。
  - 验收：旧运行可空、准确身份/数量、512 点限制、保留明细和稳定导出通过。
  - 验证：`python -m pytest tests/integration/test_backtest_index_api.py tests/integration/test_backtest_export_api.py -q`；OpenAPI 检查。
  - 文件：`backtest/results.py`、`web/backtest_schemas.py`、`web/routers/backtest_results.py`、`web/backtest_export.py`、测试/生成契约。
- [x] `IDX011`——测试先行增加回测指数表单/摘要/页签组件。
  - 验收：后端覆盖只读、摘要/路径身份一致、全部可用状态和无障碍通过。
  - 验证：`npm --prefix web run type-check`；`npm --prefix web run test -- --run`；聚焦 Playwright。
  - 文件：回测指数组件/组合函数、新建/详情页面、API 适配器、单元/E2E 测试。

## 完成

- [x] `IDX012`——完成配对 README/API/测试报告并运行全部离线门禁。
  - 验收：双语一致、记录供应商限制、完整文件/测试/风险报告、密钥扫描干净、全部必需门禁通过。
  - 验证：[项目README](../README.zh-CN.md) 中全部命令、`git diff --check`、`git status --short`。
  - 文件：`README.md`、`README.zh-CN.md`、`docs/README*`、配对验证报告、`openapi.json`、生成 TypeScript。

## WEBF13 路由与旅程收口

- [x] `WEBF13`——证明真实生产路由/新建回测旅程边界，并在不改变冻结契约的前提下记录离线验收证据。
  - 验收：配对规格把曾经的占位路由 `/`、`/stocks/:symbol`、`/plans/:id`、`/alerts` 和 `/system` 标记为真实惰性 SFC；精确的 10 路由地图和 `submit → run+job URL → poll → remove jobId → materialized result` 链路具备单元、浏览器与后端 fake 证据；OpenAPI 继续精确为 42 条路径（27 条实时加 15 条回测）；配对报告状态为 `PASS`。
  - 验证：聚焦后端 pytest 与 production-fake 旅程；Ruff；OpenAPI 快照与生成 TypeScript 一致性；完整 Vitest、`vue-tsc`、构建与 Chromium 套件；`git diff --check`。
  - 文件：`README*`、`docs/README*`、配对 local-Web/backtest/API/ADR 规格、`tasks/plan*`、`tasks/todo*`、`docs/verification/webf13-acceptance*`、`web/tests/unit/BacktestRouter.spec.ts`、`web/tests/e2e/backtests.spec.ts` 和 `web/tests/e2e/accessibility.spec.ts`。

# 当前任务清单：监控闭环回测

> 已授权实施，更新于 2026-10-08。实施方案：[plan.zh-CN.md](plan.zh-CN.md)；英文权威清单：[todo.md](todo.md)。ML-T01–ML-T05、ML-T07/ML-T08/ML-T10/ML-T11、ML-T30–ML-T34、ML-C01/ML-C02/ML-C03 与 ML-C12 已实现并验证，其余任务待完成。证据：[验证记录](../docs/verification/monitor-loop-backtest.zh-CN.md)。其后保留此前已完成的历史清单。
> 2026-10-07 范围纠正；2026-10-08 进度：ML-T06/ML-T09 已取消；完成 14 项、待完成活动任务 23 项，37 项活动 / 保留 39 个 ID，13 个检查点。ML-A07 不作门槛，每次运行固定一份计划，最多一个未完成任务，证据 MV17–MV23。

所有命令从 `trade-plan-monitor/` 执行；标出的新文件是预期产物。验证命令在对应实现后执行，本次编写文档不代表已运行。每项约五个主要文件以内，超出时先拆分。生成契约/批准摘要分别处理，不能为通过检查静默批准 API。

完整交付缺口按 [MV10](../docs/verification/monitor-loop-backtest.zh-CN.md#mv10-完整验收缺口清单) 分组。仅启动解耦验收见 [MV11](../docs/verification/monitor-loop-backtest.zh-CN.md#mv11-仅启动解耦验收)，不得把待完成业务/资源改造作为其前置条件。两者均引用既有范围，不新增要求。已取消保护项不能重新成为隐含前置条件。

## ML-T01. 定义冻结闭环输入与时间边界

- [x] 完成实现和本项验证.
- **依赖:** `ML-T30`
- **验收:** 严格版本化输入接受恰好一份计划/原文，区分原文/激活/结束时间、成本/市值和零/未知现金。构造/复制/解码拒绝第二条目；保留跨日激活、有效性及确定的结束解析，旧字节不变。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_input.py`, `src/trade_plan_monitor/backtest/plan_schedule.py`, `tests/unit/test_monitor_loop_input.py`, `tests/unit/test_monitor_loop_schedule.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A04, ML-A09, ML-A11, ML-A12, ML-A15.
- **进展:** 已实现独立 `monitor-loop-input-v1` / `backtest-run-v5` 契约、精确期初成本、独立市值、未知/零现金、已审核证据及确定边界/日历。2026-10-07 范围纠正将原文/条目数量限为一，移除后继选择。一份激活在有效时跨日延续；仅编写日期输入保持明确。其他批次/安全整数/求值/供应商防护不变。原始证据 MV14，当前范围回归 MV17。

## ML-T02. 提取共用模拟参与者

- [x] 完成实现和本项验证.
- **依赖:** `ML-T01`
- **验收:** 将现有授权/数量/持仓转换封装为应用参与者，由调用方控制事务；在线命令和旧回放的回执、错误与行为保持一致。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_simulation_participant.py tests/integration/test_unified_simulation_transactions.py tests/integration/test_unified_replay.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/state/simulation.py`, `src/trade_plan_monitor/web/daily_service.py`, `src/trade_plan_monitor/backtest/research_session.py`, `tests/integration/test_simulation_participant.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A05, ML-A08, ML-A09.
- **进展:** `state/simulation.py` 承载类型化命令/回执，以及既有授权、完整数量、持仓、信号与风险转换。调用方控制提交/回滚；Web 将领域拒绝映射到既有错误信封，旧研究模拟不再调用私有 HTTP 辅助函数。独立回滚/修订/不导入 Web 测试及在线/旧回放回归通过。本项尚未实现研究资金提交或提醒记录。已执行证据：MV14。

## ML-T03. 在私有闭环会话记录提醒

- [x] 完成实现和本项验证.
- **依赖:** `ML-T01`, `ML-T02`
- **验收:** 使用共用监控/发送资格、隔离仓储和确定时钟/身份；记录有效提醒，拒绝陈旧证据。纯技术提醒不授权执行，不创建真实发送出口。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_unified_runtime.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_session.py`, `src/trade_plan_monitor/backtest/reminder_capture.py`, `src/trade_plan_monitor/runtime/daily_service.py`, `src/trade_plan_monitor/state/daily_accounting.py`, `src/trade_plan_monitor/state/daily_state_models.py`, `tests/integration/test_monitor_loop_reminders.py`
- **范围:** M (6 个主要文件，含测试); **追溯:** ML-A02, ML-A03, ML-A06, ML-A08.
- **实施薄片:** ML-T03.1 覆盖期初批次状态模型、账户计算及测试（3 个文件）；ML-T03.2 覆盖私有会话/记录器、运行时 ID/资格注入与同一测试文件（4 个文件）。私有批次保留未知买入日期及可卖量，不包含生产迁移或传输合同变更。
- **进展:** 新建私有 SQLite 状态使用共用监控和发送资格、冻结审阅/激活记录、虚拟时钟及因果提醒 ID。有界分页记录具备事务性和幂等性；陈旧报价/分钟/事实/持仓/审阅/激活证据均被抑制。纯提醒不携带交易授权。普通发送路径现拒绝已修订的来源分钟，与纯提醒既有校验一致。私有循环不加载发送出口、供应商、网络或 Web 参与者。已执行证据：MV15。

### ML-C01. 检查点

- [x] 共用监控参与者保持在线行为。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T04. 原子提交账户与库存

- [x] 完成实现和本项验证.
- **依赖:** `ML-T02`, `ML-T03`
- **验收:** 精确计算费用/滑点，先检查完整数量现金，再以同事务写资金、批次、信号消费和回执。保留期初成本 401050 分；失败/重复提交不得产生部分或重复影响。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_costs.py tests/integration/test_monitor_loop_account.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_account.py`, `src/trade_plan_monitor/backtest/loop_session.py`, `tests/unit/test_monitor_loop_costs.py`, `tests/integration/test_monitor_loop_account.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A05, ML-A09, ML-A12, ML-A13.
- **进展:** 精确整分结算使用每股绝对滑点及既有费用向上取整。私有资金/批次成本、共用持仓/信号/风险转换和两类回执位于同一调用方控制的事务。资金检查包含全部费用；未知或不足的资金不会提交部分数量。期初成本保持 401050 分，卖出成本跟随实际扣减批次并把尾差留在剩余批次，未知成本保持未知盈亏。重复请求键校验命令/费用绑定；前后阶段故障、陈旧修订及已修订来源分钟均无法提交。已执行证据：MV16。ML-T05 已实现响应时序/自动循环，证据 MV19。

## ML-T05. 运行单计划提醒响应闭环

- [x] 完成实现和本项验证。
- **依赖:** `ML-T01`, `ML-T03`, `ML-T04`
- **验收:** 已审核夹具无需交易脚本即可发现买卖时点；执行后续合格区间、风险优先级、单次消费及有限上限。观察/历史操作模式不添加未要求交易。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_cycle.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_runner.py`, `src/trade_plan_monitor/backtest/response_policy.py`, `src/trade_plan_monitor/backtest/loop_session.py`, `tests/integration/test_monitor_loop_cycle.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A01, ML-A02, ML-A03, ML-A04, ML-A06.
- **进展:** 私有帧绑定当前分钟成交证据，合格捕获提醒产生有界意图，下一完整分钟区间遵守响应延迟，共享状态控制风险/冲突及完整数量，每次成交刷新监控。计划到期关闭普通权限并保留风险维护。观察/已记录模式不自动生成交易。ML-T05/ML-C02 通过 MV19；已记录动作导入、冻结数据集读取、工作线程/API/UI/报告集成仍为独立待完成任务。

## ML-T06. 已取消：按日计划切换

- [ ] 用户于 2026-10-07 取消；排除实施和完成门槛，不标记完成。
- **依赖:** 无
- **验收:** 不属单计划版本，保留 ID 供追溯。
- **验证:** 无；取消是范围决定，不是测试通过。
- **主要文件:** 无；不再计划原切换/继承产物。
- **范围:** 已取消；**追溯:** ML-A07。

### ML-C02. 检查点

- [x] 已审核夹具运行完整单计划闭环及原子账户；ML-T06 已取消。
- [x] 在 MV19 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T07. 持久化单计划准备及修订状态

- [x] 完成实现和本项验证.
- **依赖:** `ML-T01`
- **验收:** 创建独立标记准备库，恰好一份原文、有界尝试、候选/审核修订及幂等；拒绝跨领域路径。持久化重启状态，校验与批准分开。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_store.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/preparation_models.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_store.py`
- **范围:** M (3 个主要文件，含测试); **追溯:** ML-A16, ML-A18.
- **证据:** MV20：53 项准备库案例在 92 项相关集成回归中通过。仅完成私有持久化；MV21 完成 ML-T08 提取及 ML-C03。ML-T10/ML-T11/ML-T12 分别保留工作线程排空/全局准入、语义审核/冻结及 API 集成。

## ML-T08. 提取一份完整计划及期初账户

- [x] 完成实现和本项验证.
- **依赖:** `ML-T07`
- **验收:** 版本化完整计划/期初账户输出，复用供应商/解析防护并保留原文范围。单份原文不含前版上下文/更新操作，缺失事实/不支持语义保持待解决。保留普通提取回归。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_extraction.py tests/unit/test_current_plan_extraction_security.py tests/unit/test_ai_plan_extraction_v4.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/ai/loop_plan_extraction.py`, `src/trade_plan_monitor/ai/extraction.py`, `tests/unit/test_monitor_loop_extraction.py`, `tests/fixtures/ai/monitor-loop-extraction-cases.json`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A12, ML-A14, ML-A16, ML-A17.
- **证据:** MV21：70 项新增提取案例，93 项本项门禁及完整相关回归通过。一份版本化 Schema 5 候选保留精确期初事实/原文范围及未知输入，拒绝目标/假想/伪造事实，可通过 ML-T07 存储往返恢复。未增加工作线程、公开入口或批准。

## ML-T09. 已取消：后继继承与合并

- [ ] 用户于 2026-10-07 取消；排除实施和完成门槛，不标记完成。
- **依赖:** 无
- **验收:** 不属单计划版本，保留 ID 供追溯。
- **验证:** 无；取消是范围决定，不是测试通过。
- **主要文件:** 无；不再计划原切换/继承产物。
- **范围:** 已取消；**追溯:** ML-A16, ML-A17。

### ML-C03. 检查点

- [x] 单原文持久化、完整提取及原始证据绑定通过；ML-T09 已取消。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。MV20/MV21 记录私有持久化/提取门禁；ML-T10 通过 MV22，ML-T11 通过 MV23，下一项为 ML-T12。

## ML-T10. 安全恢复单原文提取

- [x] 完成实现和本项验证.
- **依赖:** `ML-T07`, `ML-T08`, `ML-T34`
- **验收:** 以代次/原文/修订防护认领一份原文，在调用外持久化进度。复用既有防护及有界可重试尝试，编辑/取消/重启拒绝晚到完成。使用自有回测线程。未知付费结果需明确恢复，不新增全局 AI 预算作为隔离门槛。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/preparation_models.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_worker.py`, `src/trade_plan_monitor/web/ai_service.py`, `tests/integration/test_plan_preparation_worker.py`
- **范围:** 拆成两个 M 切片，每个 4 个主要文件（含共用测试共 7 个不同文件）；**追溯:** ML-A16, ML-A18。先持久化工作线程归属/进度并读取既有准入预留以恢复，再接入自有调用和配置 AI。不新增任务类型、队列、数据库或公开路由。
- **证据:** MV22：29 项工作线程检查及 3000 项最终回归通过。自有调用在实际排空前保留既有全局准入；未知付费结果要求明确确认旧工作已结束。读取/旧回执重放不发起调用，已知重试仍限制在三次持久化尝试内。语义审核/冻结及公开准备集成仍属于 ML-T11/ML-T12。

## ML-T11. 审核并冻结一份完整准备计划

- [x] 完成实现和本项验证.
- **依赖:** `ML-T08`, `ML-T10`
- **验收:** 明确审核绑定精确原文/内容/账户/证据修订，冻结一份不可变清单。修正原文使其候选/审核失效，已提交运行保持冻结。校验不能产生批准或激活生产计划。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_review.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/preparation_review.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_review.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A17, ML-A18.
- **证据:** MV23：51 项审核检查通过。已验证精确修订/原文/计划/账户/证据绑定、清单与声明原子写入、原始收据重放及实际准入保留。期初未知事实继续明确保留，伪造 AI/旧审核标记及未来期初行情不能产生权限。公开准备集成仍属于 ML-T12，ML-C04 仍待完成。

## ML-T12. 接通准备应用接口

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T10`, `ML-T11`, `ML-T33`
- **验收:** 将恰好单原文的创建/读取/编辑/提取/取消/审核接入按需能力归属及已取得资源关闭。HTTP 测试证明拒绝第二原文、修订、幂等、有界投影和假 AI 进度，不变更在线计划。守住就绪门槛，准备库失败仅降级回测。
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

## ML-T14. 构建单原文上传及进度 UI

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T13`
- **验收:** 恰好接受一份原文，显示提取状态/错误并支持稳定重试/取消。终态/卸载停止轮询，错误原文/服务错误保持可见可编辑。不含批次排序或多计划选择。
- **验证:** `npm --prefix web run test -- --run tests/unit/PlanPreparation.spec.ts`
- **主要文件:** `web/src/api/preparations.ts`, `web/src/composables/usePlanPreparation.ts`, `web/src/components/backtests/PlanPreparationSourceForm.vue`, `web/src/components/backtests/PlanPreparationProgress.vue`, `web/tests/unit/PlanPreparation.spec.ts`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A10, ML-A16, ML-A18.

## ML-T15. 预览并审核一份准备计划

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T14`
- **验收:** 展示期初账户、完整规则、来源证据、历史起点/可用时间及未解决条款。仅精确已审核修订可继续，原文编辑明确使批准失效。不含规则差异、后继日历或后代。
- **验证:** `npm --prefix web run test -- --run tests/unit/PlanPreparationReview.spec.ts`
- **主要文件:** `web/src/components/backtests/PlanPreparationReview.vue`, `web/src/views/BacktestNewView.vue`, `web/src/composables/usePlanPreparation.ts`, `web/tests/unit/PlanPreparationReview.spec.ts`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A10, ML-A12, ML-A17, ML-A18.

### ML-C05. 检查点

- [ ] 上传、进度和审核 UI 使用生成契约。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T16. 冻结截至明确时点的证据

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T01`, `ML-T05`
- **验收:** 表示部分终端时段而不标为完整，校验所需已结束区间和该单份计划预热。明确当天/节假日/延迟数据，旧清单字节/就绪语义不变。
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
- **依赖:** `ML-T16`, `ML-T17`, `ML-T33`
- **验收:** 增量提交已审核准备身份和可选结束日期，在幂等预留下冻结输入/截止。跨午夜重复请求复用原结果，拒绝陈旧审核和无效区间。 通过回测服务和自有仓库执行器解析/冻结提交，保持独立存储归属。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_submission.py tests/integration/test_backtest_run_api.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_runs.py`, `tests/integration/test_monitor_loop_submission.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A09, ML-A10, ML-A15, ML-A18.

### ML-C06. 检查点

- [ ] 冻结截止输入和任务引用通过重试与陈旧审核检查。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T19. 通过后台工作者执行冻结闭环输入

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T05`, `ML-T17`, `ML-T18`, `ML-T34`
- **验收:** 按输入区分值分发，沿用租约/取消所有权，只读取冻结产物。不保留回测 CLI 入口、兼容适配器或命令专用协调器。 生命周期/准入门槛后在专用线程分派，保留单槽和原子发布语义。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_worker.py tests/integration/test_backtest_job_coordinator.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/runner.py`, `tests/integration/test_monitor_loop_worker.py`
- **范围:** M (3 个主要文件，含测试); **追溯:** ML-A01, ML-A09, ML-A10.

## ML-T20. 投影因果事件与有效估值

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T04`, `ML-T05`
- **验收:** 区分评估/提醒/请求/成交/结果状态并保留因果关联。历史成本盈亏与区间收益分开，未知价格/现金、零分母不编造指标或清仓。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_report.py tests/integration/test_monitor_loop_valuation.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_report.py`, `src/trade_plan_monitor/backtest/loop_runner.py`, `tests/unit/test_monitor_loop_report.py`, `tests/integration/test_monitor_loop_valuation.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A01, ML-A03, ML-A09, ML-A12, ML-A13, ML-A15.

## ML-T21. 原子发布与保留闭环结果

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T19`, `ML-T20`
- **验收:** 流式类型化事件，验证存储输入/报告哈希，仅发布完整运行。失败/取消/超限不留下已完成部分报告。总共保留最新 30 条已物化历史运行，按发布/保留时间降序、run_id 破同序。发布后既有有界维护删除最旧超额摘要/成交/详情，置顶不绕过上限。保护排队/运行引用、共享数据集/快照及保留冻结单计划输入。既有导出保持字节兼容，不新增清理调度器或资源预算框架。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_publication.py tests/integration/test_monitor_loop_retention.py tests/integration/test_backtest_publication.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/jobs/maintenance.py`, `tests/integration/test_monitor_loop_publication.py`, `tests/integration/test_monitor_loop_retention.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A10.

### ML-C07. 检查点

- [ ] 工作者只发布完整且依赖保留正确的结果。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T22. 提供分页闭环结果，保留导出兼容

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T21`
- **验收:** 结果/详情以稳定分页/模式标识暴露类型化闭环事件、冻结计划来源及截止覆盖。保留旧摘要及支持模式 CSV/JSON 字节。不新增闭环导出格式/路由/UI/任务/互斥。重投影使用自有线程和有界分页，背压仅影响回测准入。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_result_api.py tests/integration/test_backtest_exports.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `tests/integration/test_monitor_loop_result_api.py`
- **范围:** M (3 个主要文件，含测试); **追溯:** ML-A09, ML-A10, ML-A15.

## ML-T23. 生成最终运行与结果契约

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T18`, `ML-T22`
- **验收:** 在真实运行/结果 API 变化后重新生成，校验新旧区分载荷、上限和安全整数。批准摘要留待 ML-T29 审阅，不消除基线批准失败断言。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **主要文件:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_monitor_loop_contract.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A10.

## ML-T24. 从既有运行表单提交一份准备计划

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T15`, `ML-T23`
- **验收:** 使用一份已审核快照及提取的期初账户，无需原始操作 JSON。结束在服务端默认解析。展示截止、缺失事实及不支持条款，接入既有任务/结果导航，不含多计划选择。
- **验证:** `npm --prefix web run test -- --run tests/unit/MonitorLoopRunForm.spec.ts`
- **主要文件:** `web/src/components/backtests/BacktestRunForm.vue`, `web/src/composables/useBacktestRunForm.ts`, `web/src/api/backtests.ts`, `web/src/views/BacktestNewView.vue`, `web/tests/unit/MonitorLoopRunForm.spec.ts`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A10, ML-A12, ML-A14, ML-A15.

### ML-C08. 检查点

- [ ] 结果 API 和运行创建兼容新旧契约，既有导出保持兼容，不新增开发。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T25. 在结果中解释计划与执行历史

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T22`, `ML-T23`
- **验收:** 将分页因果事件及冻结单计划来源接入结果页，区分持仓、阻断/未成交意图与成交。展示账户演进、有效指标及实际截止，无客户端交易逻辑或版本切换时间线。
- **验证:** `npm --prefix web run test -- --run tests/unit/MonitorLoopResults.spec.ts`
- **主要文件:** `web/src/components/backtests/MonitorLoopTimeline.vue`, `web/src/views/BacktestRunDetailView.vue`, `web/src/composables/useBacktestResults.ts`, `web/tests/unit/MonitorLoopResults.spec.ts`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A01, ML-A10, ML-A13, ML-A15.

## ML-T26. 证明一致性、因果性与故障原子性

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T05`, `ML-T11`, `ML-T16`, `ML-T21`, `ML-T34`
- **验收:** 以独立预期输出对比在线参与者与闭环状态，修改未来证据并注入事务/工作者故障。做一次关键约束变异检查，虚拟 AI/供应商/出口计数证明隔离。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_parity.py tests/integration/test_monitor_loop_faults.py tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **主要文件:** `tests/integration/test_monitor_loop_parity.py`, `tests/integration/test_monitor_loop_faults.py`, `tests/fixtures/monitor-loop/scenarios.json`, `tests/integration/test_plan_preparation_worker.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A01–ML-A24，排除已取消 ML-A07。

## ML-T27. 验证完整浏览器流程

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T24`, `ML-T25`, `ML-T26`, `ML-T36`
- **验收:** 真实挂载 API/组合配虚拟外部服务，贯通上传→重试/编辑→审核→运行→结果。证明夹具未预写未来交易，不只测假结果页，不访问真实用户库。 加入服务停止/未知取消/恢复导航，监控页面保持可用。
- **验证:** `npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts`; `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_production_composition.py -q -m "not live"`
- **主要文件:** `web/tests/e2e/monitor-loop-backtest.spec.ts`, `web/tests/fixtures/monitor-loop.json`, `tests/integration/test_monitor_loop_production_composition.py`
- **范围:** M (3 个主要文件，含测试); **追溯:** ML-A10, ML-A16, ML-A18.

### ML-C09. 检查点

- [ ] 独立故障/一致性与完整浏览器流程通过。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T28. 记录操作指南与实际验证证据

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T27`, `ML-T37`
- **验收:** 双语记录实际支持的 API/UI 行为及原文限制。执行方案相关最终检查并记录真实结果、未解决失败和证据范围，不宣称真实 AI/供应商认证。
- **验证:** `git diff --check`
- **主要文件:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A01–ML-A24，排除已取消 ML-A07。

## ML-T29. 对齐已审阅规格与API批准

- [ ] 完成实现和本项验证.
- **依赖:** `ML-T23`, `ML-T28`, `ML-T38`, `ML-T39`
- **验收:** 结合双语契约审阅最终 API/行为差异，仅记录由此批准的快照身份和最终实现范围。保留旧批准历史，明确区分此前已知基线不一致。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py -q -m "not live"`
- **主要文件:** `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.md`, `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.zh-CN.md`, `docs/specifications/monitoring/SPEC-unified-plan.md`, `docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A09, ML-A10.

### ML-C10. 检查点

- [ ] ML-A01–ML-A24 中活动证据（排除已取消 ML-A07）及双语审核契约完整。
- [ ] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T30. 冻结按需生命周期与能力契约

- [x] 完成实现和本项验证。
- **依赖:** 无
- **验收:** 定义 NOT_INITIALIZED/READ_READY 与执行就绪，无副作用启动/状态、single-flight 门槛、会话授权任务 ID 和物理排空。保留身份/原子发布，不后台预热、不直接填批准摘要。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_backtest_service_contract.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/service_contract.py`, `src/trade_plan_monitor/backtest/service_config.py`, `tests/unit/test_backtest_service_contract.py`
- **范围:** M (3 个主要文件，含测试); **追溯:** ML-A19, ML-A22, ML-A24.

## ML-T31. 从应用启动移除回测准备

- [x] 完成实现和本项验证。
- **依赖:** `ML-T30`
- **验收:** 应用启动/关闭/状态/OpenAPI/监控导航不调用回测工厂/start/存储/密钥/执行器/供应商、不安排预热。回测专用无效配置不阻止健康监控/Web 启动。仅清理已取得资源，首次使用失败保持局部。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_startup_isolation.py tests/integration/test_backtest_production_composition.py tests/integration/test_monitor_production_composition.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/web/lifespan.py`, `src/trade_plan_monitor/web/app.py`, `src/trade_plan_monitor/backtest/composition.py`, `tests/integration/test_backtest_startup_isolation.py`, `tests/integration/test_backtest_production_composition.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A19, ML-A20.

## ML-T32. 按需一次初始化有界回测能力

- [x] 完成实现和本项验证。
- **依赖:** `ML-T31`
- **验收:** 受保护 single-flight 管理器处理并发首次使用、按需执行器、等待者取消及代次保护。拆分元数据 READ_READY 与执行 READY，读取/状态不激活协调器。真实返回初始化/不可用，物理排空前保留资源归属。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_production_composition.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/thread_lifecycle.py`, `src/trade_plan_monitor/backtest/thread_ownership.py`, `src/trade_plan_monitor/backtest/service_lifecycle.py`, `src/trade_plan_monitor/web/app.py`, `tests/integration/test_backtest_thread_ownership.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A19, ML-A20, ML-A22.
- **实际连接改动:** `web/lifespan.py` 导入管理器，`backtest/composition.py` 拥有元数据适配器。用户明确授权 `web/errors.py` 中 503 `Retry-After` 的窄扩展及其响应测试。实际证据见验证记录。

### ML-C11. 检查点

- [x] 无副作用启动/状态/关闭、single-flight 首次使用及读取/执行分离通过。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T33. 用明确使用约束任务恢复与取消

- [x] 完成实现和本项验证。
- **依赖:** `ML-T32`
- **验收:** 重启保持积压休眠。读取/就绪不领取/恢复/执行任务，当前会话新任务和明确选择恢复 ID 约束协调器。保留取消/完成/租约保护、30 秒租约/3 个领取代次及排空后替换。不盲目付费重试、不重排失败/取消。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_jobs.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/service_lifecycle.py`, `src/trade_plan_monitor/backtest/jobs/coordinator.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `src/trade_plan_monitor/backtest/composition.py`, `tests/integration/test_backtest_thread_recovery.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A20, ML-A21.
- **进展:** 用户于 2026-10-07 的最新纠正覆盖按租约过期释放任务槽：未完成 QUEUED/RUNNING/CANCEL_REQUESTED 任务在终态前占用准入，包括过期/未知租约。明确恢复仅在物理排空后授权一个既有任务，不会授权第二个新任务。既有 30 秒租约/3 代领取、旧 token、取消/发布/幂等保护保留。不新增状态/数据库迁移。证据：MV18、ADR 0009；MV12 保留为历史。

## ML-T34. 保留既有限制并为历史同步限速

- [x] 完成实现和本项验证。
- **依赖:** `ML-T33`
- **验收:** 保留并回归既有有限队列/输入/事件限制、单执行、有界线程/分页及存储领域防护。不新增动态内存/CPU 采样控制器、压力阈值或压力触发的准入/取消。历史同步保留单活跃操作，仅增加本地固定请求开始间隔，初始沿用已有 1.25 秒节奏值。保留既有请求超时/错误映射及等待期间取消，不新增重试策略。监测请求控制保持既有行为。不新增全局额度池、正式容量预留、跨业务调度、共用冷却、账号/接口注册表、动态分配或额度页面。低频 AI 提取保留既有单原文提取防护，不阻塞本项。流式记录、协作取消，不保证每线程硬 CPU/内存上限。回放不构造正式供应商/发送器。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_sync_pacing.py tests/integration/test_backtest_results.py tests/integration/test_backtest_thread_ownership.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/sync.py`, `tests/integration/test_backtest_sync_pacing.py`
- **范围:** S (2 个主要文件，含测试); **追溯:** ML-A20, ML-A22, ML-A23.
- **范围决策:** 2026-10-07 用户要求最小范围。原正式容量预留项替换为 `backtest/sync.py` 内本地限速及虚拟间隔/取消测试。移除计划中的通用 `backtest/capability_admission.py` 模块及供应商准入测试，本项不要求新增 `web/ai_service.py`、`runtime/request_control.py` 或 `backtest/application.py` 连接。额度认证或共用预算决策不再构成门槛。存储保护仅保留既有独立默认文件、路径规范化及正式表/领域混用防护，不新增深度文件身份或跨文件别名框架。取消磁盘/日志预算及空闲容量准入阈值。历史回测最新 30 个保留策略归 ML-T21，不作为隔离门槛。取消计划中的 `backtest/resource_control.py` 及通用 `test_backtest_resource_boundaries.py`，既有防护只需回归。本地同步限速及既有防护回归已通过，ML-T33 依赖已完成；实际证据见 MV12。用户最新纠正要求一个未完成任务，终态前排除新的互斥准备/同步/验证/回放。通过现有事务准入及准备修订/冻结保护落实，不新增通用锁、队列或调度层。已实现任务准入证据见 MV18；准备入口仍待完成。

### ML-C12. 检查点

- [x] 感知排空恢复/取消、既有防护回归及本地同步限速通过。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T35. 公开惰性服务状态与明确恢复 API

- [ ] 完成实现和本项验证。
- **依赖:** `ML-T12`, `ML-T23`, `ML-T33`, `ML-T34`
- **验收:** 未使用时状态/停止无副作用，真正数据/操作请求通过 guard/校验后激活所需能力。恢复按 epoch/修订/幂等明确重试准备或已选 resumeJobIds（<=1）。局部 503/Retry-After 表示任务未准入，初始化轮询不能重启失败准备。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_service_api.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/web/routers/backtest_service.py`, `src/trade_plan_monitor/web/backtest_service_schemas.py`, `src/trade_plan_monitor/web/app.py`, `tests/integration/test_backtest_service_api.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A19, ML-A21, ML-A24.

## ML-T39. 生成独立服务传输契约

- [ ] 完成实现和本项验证。
- **依赖:** `ML-T35`
- **验收:** 生成已挂载服务资源及强类型能力/错误，覆盖两种契约 profile。检查监控端点和未受影响载荷语义不变；陈旧批准记录留待明确最终审阅。不手写重复传输模型。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_service_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **主要文件:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_backtest_service_contract.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A19, ML-A24.

## ML-T36. 网页显示首次使用准备与局部恢复

- [ ] 完成实现和本项验证。
- **依赖:** `ML-T39`
- **验收:** 仅活跃回测数据请求触发惰性准备，路由预取/全局状态轮询无副作用。区分未用/初始化/读取就绪/执行就绪/失败，503 保留表单并复用变更键。打开历史不恢复任务/AI，明确重试/恢复展示选中积压，监控可用。
- **验证:** `npm --prefix web run test -- --run tests/unit/BacktestServiceState.spec.ts`; `npm --prefix web run type-check`
- **主要文件:** `web/src/api/backtestService.ts`, `web/src/composables/useBacktestService.ts`, `web/src/components/backtests/BacktestServiceState.vue`, `web/src/views/BacktestNewView.vue`, `web/tests/unit/BacktestServiceState.spec.ts`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A21, ML-A24.

## ML-T37. 验证 Windows 惰性激活与线程边界

- [ ] 完成实现和本项验证。
- **依赖:** `ML-T26`, `ML-T27`, `ML-T34`, `ML-T36`
- **验收:** 证明应用启动/监控导航/状态/预取/关闭零回测工作、并发首次使用只初始化一次、只读历史不执行积压、明确选择恢复。可控夹具注入首次使用错误/晚到 future/取消竞态，保留 ML17 10 只股票负载门槛及已接受线程限制。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_isolation_fault_matrix.py tests/integration/test_monitor_loop_parity.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/verify_backtest_thread_load.py --profile windows-threads --offline`
- **主要文件:** `tests/integration/test_backtest_isolation_fault_matrix.py`, `tests/fixtures/monitor-loop/isolation.json`, `scripts/verify_backtest_thread_load.py`, `tests/integration/test_backtest_sync_pacing.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A08, ML-A19–ML-A24.

## ML-T38. 记录按需线程操作指导

- [ ] 完成实现和本项验证。
- **依赖:** `ML-T37`
- **验收:** 双语指导解释休眠启动、首次准备、元数据与执行、明确积压恢复、局部修复和感知排空停止。说明共享进程风险，不必升级进程，保留身份及历史基线批准不一致与其审阅修复记录。
- **验证:** `git diff --check`
- **主要文件:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A19–ML-A24.

### ML-C13. 检查点

- [ ] 服务 API/UI 及有记录的 Windows 线程故障/负载验收通过；ML-C10 仍为最终合并门槛。
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

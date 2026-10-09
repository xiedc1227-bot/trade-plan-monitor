# 当前任务清单：监控闭环回测

> 已授权实施，更新于 2026-10-09。实施方案：[plan.zh-CN.md](plan.zh-CN.md)；英文权威清单：[todo.md](todo.md)。已实施并验证：ML-T01, ML-T02, ML-T03, ML-T04, ML-T05, ML-T07, ML-T08, ML-T10, ML-T11, ML-T12, ML-T13, ML-T14, ML-T15, ML-T16, ML-T17, ML-T18, ML-T19, ML-T20, ML-T21, ML-T22, ML-T23, ML-T24, ML-T25, ML-T26, ML-T27, ML-T28, ML-T29, ML-T30, ML-T31, ML-T32, ML-T33, ML-T34, ML-T35, ML-T39, ML-T36, ML-T37, ML-T38. 证据：[验证记录](../docs/verification/monitor-loop-backtest.zh-CN.md)。其后保留此前已完成的历史清单。
> 2026-10-07 范围纠正；2026-10-09 进度：ML-T06/ML-T09 已取消；完成 37 项、待完成活动任务 0 项，37 项活动 / 保留 39 个 ID，13 个检查点。ML-A07 不作门槛，每次运行固定一份计划，最多一个未完成任务，证据 MV17–MV46。

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
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。MV20/MV21 记录私有持久化/提取门禁；ML-T10 通过 MV22，ML-T11 通过 MV23，ML-T12/ML-C04 通过 MV24，ML-T13 通过 MV25，ML-T14 通过 MV26，下一项为 ML-T15。

## ML-T10. 安全恢复单原文提取

- [x] 完成实现和本项验证.
- **依赖:** `ML-T07`, `ML-T08`, `ML-T34`
- **验收:** 以代次/原文/修订防护认领一份原文，在调用外持久化进度。复用既有防护及有界可重试尝试，编辑/取消/重启拒绝晚到完成。使用自有回测线程。未知付费结果需明确恢复，不新增全局 AI 预算作为隔离门槛。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/preparation_models.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_worker.py`, `src/trade_plan_monitor/web/ai_service.py`, `tests/integration/test_plan_preparation_worker.py`
- **范围:** 拆成两个 M 切片，每个 4 个主要文件（含共用测试共 7 个不同文件）；**追溯:** ML-A16, ML-A18。先持久化工作线程归属/进度并读取既有准入预留以恢复，再接入自有调用和配置 AI。不新增任务类型、队列、数据库或公开路由。
- **证据:** MV22：29 项工作线程检查及 3000 项最终回归通过。自有调用在实际排空前保留既有全局准入；未知付费结果要求明确确认旧工作已结束。读取/旧回执重放不发起调用，已知重试仍限制在三次持久化尝试内。语义审核/冻结及公开准备集成在 MV23/MV24 通过 ML-T11/ML-T12。

## ML-T11. 审核并冻结一份完整准备计划

- [x] 完成实现和本项验证.
- **依赖:** `ML-T08`, `ML-T10`
- **验收:** 明确审核绑定精确原文/内容/账户/证据修订，冻结一份不可变清单。修正原文使其候选/审核失效，已提交运行保持冻结。校验不能产生批准或激活生产计划。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_review.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/preparation_review.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_review.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A17, ML-A18.
- **证据:** MV23：51 项审核检查通过。已验证精确修订/原文/计划/账户/证据绑定、清单与声明原子写入、原始收据重放及实际准入保留。期初未知事实继续明确保留，伪造 AI/旧审核标记及未来期初行情不能产生权限。公开准备集成及 ML-C04 在 MV24 通过。

## ML-T12. 接通准备应用接口

- [x] 完成实现和本项验证.
- **依赖:** `ML-T10`, `ML-T11`, `ML-T33`
- **验收:** 将恰好单原文的创建/读取/编辑/提取/取消/审核接入按需能力归属及已取得资源关闭。HTTP 测试证明拒绝第二原文、修订、幂等、有界投影和假 AI 进度，不变更在线计划。守住就绪门槛，准备库失败仅降级回测。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/web/preparation_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_preparations.py`, `src/trade_plan_monitor/web/app.py`, `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_api.py`
- **范围:** 两个 M 切片，每个 4 个主要文件（含共用测试共 7 个不同文件）；**追溯:** ML-A10, ML-A16, ML-A18。先补齐创建准入/收据及能力归属，再挂载有界 HTTP 命令。模式发布暂存至 ML-T13，保留已批准契约/摘要。
- **证据:** MV24：53 项任务检查通过，包括真实本地 HTTP 配假 AI 的取消/编辑/提取/审核/重启流程。非法请求不取得资源；准备库按需打开，失败会缓存，读取不激活任务协调器，旧回执在其他工作进行时仍可重放，全局准入持续到实际排空。未知结果恢复不重新提交，旧标记/原始载荷不能产生冻结权限。ML-T13 通过 MV25，ML-T14 通过 MV26，下一项为 ML-T15。

### ML-C04. 检查点

- [x] 真实 HTTP 配虚拟 AI 跑通重启/取消/编辑/审核。
- [x] 在 MV24 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T13. 生成准备传输契约

- [x] 完成实现和本项验证.
- **依赖:** `ML-T12`
- **验收:** 从挂载生产路由生成契约，测试新增区分载荷与错误结构。保留未受影响路由/类型，将 API 变化留给 ML-T29 审阅，不提前填批准摘要。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **主要文件:** `src/trade_plan_monitor/web/preparation_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_preparations.py`, `scripts/generate_frontend_types.py`, `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_plan_preparation_contract.py`
- **范围:** 三个切片（2 / 2 / 6 个主要文件，含共用测试共 8 个不同文件）；**追溯:** ML-A10, ML-A16。先收窄候选分支及公开修订边界，不改变成功响应值；再发布已挂载路由及实际成功/错误状态；最后规范化新出现的输入/输出模式名称，保留旧响应名称，再生成两种 profile 并验证既有路由/类型不变。发布及生成产物切片在漂移检查通过后共同提交。旧批准摘要/路径门禁保持不动，留待 ML-T29，完整记录实际结果而不抑制。
- **证据:** MV25：20 项准备契约用例通过；两种 profile 新增七项操作，全部旧路径/模式/类型保持一致。候选分支收窄及命令拒绝编译验证通过。最终回归 3509 项通过，恰有两项未改动批准门禁待 ML-T29；前端 807 项测试、类型检查和构建通过。ML-T14 通过 MV26，下一项为 ML-T15，ML-C05 仍需页面/审核 UI。

## ML-T14. 构建单原文上传及进度 UI

- [x] 完成实现和本项验证.
- **依赖:** `ML-T13`
- **验收:** 恰好接受一份原文，显示提取状态/错误并支持稳定重试/取消。空闲或终态且实际排空、隐藏页面及卸载停止轮询；未保存原文先保存才可提取。取消等待、UNKNOWN 及其他未结束工作继续阻止新操作；错误原文/服务错误保持可见可编辑。不含批次排序或多计划选择。
- **验证:** `npm --prefix web run test -- --run tests/unit/PlanPreparation.spec.ts`
- **主要文件:** `web/src/api/preparations.ts`, `web/src/composables/usePlanPreparation.ts`, `web/src/components/backtests/PlanPreparationSourceForm.vue`, `web/src/components/backtests/PlanPreparationProgress.vue`, `web/tests/unit/PlanPreparation.spec.ts`
- **范围:** 三个切片（2 / 2 / 4 个主要文件，含共用测试共 5 个不同文件）；**追溯:** ML-A10, ML-A16, ML-A18。先增加有界同源传输及稳定请求回执；再实现单份准备控制器，保留修订安全重试、实际排空/未知状态保护并停止轮询；最后实现受控单份文本/文件输入及进度组件，并补齐同一控制器的未保存原文/旧读取刷新保护；不同主要文件总数仍为 5。明确结束确认仅恢复 UNKNOWN 工作，不重新提交。页面及审核预览在 ML-T15 接入。复用现有设计变量，通过临时界面验证真实浏览器行为；不改后端、生成契约或批准门禁。
- **证据:** MV26：50 项针对性测试通过，全部前端 857 项 / 58 文件通过，类型检查及构建通过。真实隔离 Chrome 界面验证取消实际结束等待、同请求重试、明确 UNKNOWN 恢复、无效 UTF-8 原文保留及停止轮询；320 / 768 / 1024 / 1440 宽度无溢出、axe 违规或浏览器错误。相关后端检查 92 项通过；原有两项 API 批准门禁仍待 ML-T29。下一项为 ML-T15，ML-C05 仍待页面组合及审核 UI。

## ML-T15. 预览并审核一份准备计划

- [x] 完成实现和本项验证.
- **依赖:** `ML-T14`
- **验收:** 展示期初账户、完整规则、来源证据、历史起点/可用时间及未解决条款。仅精确已审核修订可继续，原文编辑明确使批准失效。不含规则差异、后继日历或后代。
- **验证:** `npm --prefix web run test -- --run tests/unit/PlanPreparationReview.spec.ts`
- **主要文件:** `web/src/api/preparations.ts`, `web/src/api/preparationReview.ts`, `web/src/components/backtests/PlanPreparationReview.vue`, `web/src/views/BacktestNewView.vue`, `web/src/composables/usePlanPreparation.ts`, `web/tests/unit/PlanPreparationReview.spec.ts`, `web/tests/unit/PlanPreparation.spec.ts`, `web/tests/fixtures/plan-preparation-review.json`
- **范围:** 四个切片（5 / 3 / 2 / 5 个主要文件，含共用测试共 8 个不同文件）； **追溯:** ML-A10, ML-A12, ML-A17, ML-A18. 第一个切片包含后端实际生成的候选/冻结样例，并为既有 API 测试替身补齐必需的审核命令。真实 HTTP 验证发现审核凭据使用独立的 `PreparationFrozenView`；第四个切片在最终验证前修正传输、控制器及测试替身，不改服务端契约。

- **实施边界:** 先补齐审核传输与只读预览所需的有界候选/来源/账户形状校验；再增加单份控制器的明确审核及可读完整预览；最后在既有创建页面按明确选择接入原文/进度/审核。未保存原文、未结束工作及不确定操作阻止审核与模式切换；确认随原文/候选/审核修订变化清除。缺失事实保持可见；必需时间/仓位归属缺失及未解决规则阻止冻结，可保留的未知账户事实须明确确认。不补造价格/时间/现金。只提交当前提取内容的明确审核；原文修正后重新提取，复杂语义仍由后端判定。新闭环运行提交留在 ML-T24；不改后端、生成契约或批准门禁。

- **证据:** MV27：27 项审核/页面测试及 96 项相关前端测试通过；全部前端 884 项 / 59 文件、类型检查、构建、124 项准备 API/审核/契约检查及两种生成 profile 通过。真实本地 HTTP 配假 AI 验证上传、提取、逐项确认、冻结与原文编辑失效；四种宽度无溢出、axe 违规或浏览器错误。ML-C05 完成，下一项为 ML-T16；API 批准仍待 ML-T29。

### ML-C05. 检查点

- [x] 上传、进度和审核 UI 使用生成契约。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T16. 冻结截至明确时点的证据

- [x] 完成实现和本项验证.
- **依赖:** `ML-T01`, `ML-T05`
- **验收:** 表示部分终端时段而不标为完整，校验所需已结束区间和该单份计划预热。明确当天/节假日/延迟数据，旧清单字节/就绪语义不变。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_dataset.py tests/unit/test_monitor_loop_cutoff.py tests/integration/test_backtest_compatibility.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_dataset.py`, `src/trade_plan_monitor/backtest/dataset.py`, `src/trade_plan_monitor/backtest/market_store.py`, `tests/integration/test_monitor_loop_dataset.py`, `tests/unit/test_monitor_loop_cutoff.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A04, ML-A09, ML-A11, ML-A15.
- **实施边界:** 增加独立版本的不可变选择和支持截止点的单日模型；不放松 `FrozenSymbolDay`、历史批次校验或旧目录/清单字节。在同一 SQLite 快照读取既有不可变日历/分钟/涨跌停/日线修订，排除未来可用证据，并保留已可用修正作为后续证据。根据单份已审核快照推导需求，明确缺失闭合区间及初始预热，不把末日部分时段标成完整日。打开冻结选择只读引用产物，不查询可变头部或服务商。ML-T17 随运行输入持久化/复制选择及所需产物；本项不新增数据库/表/迁移或真实采集。
- **证据:** MV28：30 项任务检查及 159 项相关回归通过，覆盖午休/收盘/节假日、缺失分钟/限价/官方收盘、逐分钟修订、完整五分钟预热、引用损坏、取消与旧清单/目录兼容。初始分钟预热不足保持可见，受影响规则等待足够完成区间；日线预热不足拒绝冻结。变异审阅识别少一条组成分钟的错误。ML-T16 完成，下一项为 ML-T17；本项不改变 HTTP 契约或批准。

## ML-T17. 在任务上限内保存冻结运行引用

- [x] 完成实现和本项验证.
- **依赖:** `ML-T01`, `ML-T07`, `ML-T11`, `ML-T16`
- **验收:** 完整已审核输入耐久保存，队列仅传 256 KiB 内已验证不可变引用。准入前复制所需产物，重试、输入缺失/损坏和准备清理不能静默改变运行。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_input_store.py tests/integration/test_backtest_jobs.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_input_store.py`, `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/jobs/models.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `tests/integration/test_monitor_loop_input_store.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A18.
- **实施边界:** 在配置结果存储拥有的不可变内容寻址目录保存完整已审核原文/账户/计划、规范闭环输入及截止清单；复制每个已验证单日后，在既有结果输入表绑定引用。目录在明确持久化/读取前保持惰性，采用原子且不覆盖的发布，损坏文件明确拒绝。在不变的 256 KiB 上限内排入不含路径的引用；首次准入前，通过现有单任务事务验证。此处不新增数据库/表/迁移、服务商调用、留存政策或工作线程分派；ML-T19 消费引用，ML-T21 处理留存及依赖工件。
- **证据:** MV29：28 项任务检查和 199 项相关回归通过；完整审核输入与所需行情耐久复制，超过 256 KiB 的行情仅以小引用排入任务。源记录清理、重启、重复保存、缺失/损坏、原子发布故障、规范绑定及单任务准入均验证。两种生成契约保持一致，依赖校验变异被识别。ML-T17 完成，ML-T18 接入提交，ML-T19 接入工作线程，ML-T21 完成留存；API 批准仍待 ML-T29。

## ML-T18. 以一次确定的时间边界提交闭环运行

- [x] 完成实现和本项验证.
- **依赖:** `ML-T16`, `ML-T17`, `ML-T33`
- **验收:** 增量提交已审核准备身份和可选结束日期，在幂等预留下冻结输入/截止。跨午夜重复请求复用原结果，拒绝陈旧审核和无效区间。 通过回测服务和自有仓库执行器解析/冻结提交，保持独立存储归属。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_submission.py tests/integration/test_backtest_run_api.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_runs.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `tests/integration/test_monitor_loop_submission.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A10, ML-A15, ML-A18.
- **验证推动的修正:** 已提交公共请求标识下改变响应必须冲突。在既有预约事务返回已提交绑定前比较保存的意图哈希，保留过期绑定行为及全部准入规则。元数据复制与预约续期使用既有自有线程原语的两个惰性、有界职责，不增加队列或协调器。
- **实施边界:** 在既有 `POST /api/v1/backtest-runs` 增加封闭的 `PreparedBacktestRunCommand` 变体，保留旧 `BacktestRunCommand` 字节/字段。要求 `preparationId`、精确 `manifestHash`、类型化 `response`/`costs` 及可选 `endDate`；开始时间来自已审核原文的可用时间/生效日期。读取准备/数据前先声明不变公共意图，以预约时间解析提交。通过独立归属的准备服务读取审核，通过市场存储推导已有预热时段，并在回测元数据执行器冻结/复制。任何新查询前先重放原收据/引用。准备缺失对应 404，审核陈旧/行情缺失对应 409，时间/费率/范围无效对应 422，自有服务不可用对应 503。生成契约发布仍由 ML-T23 完成，工作线程消费仍由 ML-T19 完成，不调用服务商或新增准入机制。
- **证据:** MV30：75 项最终任务检查、261 项相关回归通过，1 项既有环境条件跳过；改变意图的变异测试预期失败并恢复原始字节。挂载 HTTP、原始截止/跨午夜重试、缺失行情、陈旧审核、精确费率、长复制续期、取消物理排空及单任务互斥均验证。ML-T18/ML-C06 完成，下一项 ML-T19；生成契约与批准分别仍由 ML-T23/ML-T29 完成。

### ML-C06. 检查点

- [x] 冻结截止输入和任务引用通过重试与陈旧审核检查。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T19. 通过后台工作者执行冻结闭环输入

- [x] 完成实现和本项验证.
- **依赖:** `ML-T05`, `ML-T17`, `ML-T18`, `ML-T20`, `ML-T21`, `ML-T34`
- **验收:** 按输入区分值分发，沿用租约/取消所有权，只读取冻结产物。不保留回测 CLI 入口、兼容适配器或命令专用协调器。 生命周期/准入门槛后在专用线程分派，保留单槽和原子发布语义。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_worker.py tests/integration/test_backtest_job_coordinator.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/loop_replay.py`, `src/trade_plan_monitor/backtest/jobs/operations.py`, `src/trade_plan_monitor/backtest/jobs/coordinator.py`, `tests/integration/test_monitor_loop_worker.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A01, ML-A09, ML-A10.
- **实施边界:** 新增 `loop_replay.py` 直接从自有冻结副本生成按可用时间排序的市场/日历帧，在临时私有会话及流式审计文件中驱动既有 `LoopRunner`。预热不授予权限；缺少冻结复权证明时，日线技术条件保持明确未知，不伪造认证序列。扩展既有工作请求判别/分派，在同一受生命周期和授权约束的工作线程执行；完成后在该自有线程调用既有有界维护，每段间响应停止。既有 `runner.py` 兼容回放不改，不增加命令入口、队列或调度器。
- **证据:** MV33：最终任务/生产组合门禁 46 项通过、1 项既有环境跳过，相关回归 192 项通过。工作/维护同线程、明确授权、冻结副本独立执行、声明身份绑定、单槽、取消排空及精确回放验证；身份保护变异产生 1 项预期失败、恢复精确字节。ML-T19/ML-C07 完成，下一项 ML-T22。

## ML-T20. 投影因果事件与有效估值

- [x] 完成实现和本项验证.
- **依赖:** `ML-T04`, `ML-T05`
- **验收:** 区分评估/提醒/请求/成交/结果状态并保留因果关联。历史成本盈亏与区间收益分开，未知价格/现金、零分母不编造指标或清仓。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_report.py tests/integration/test_monitor_loop_valuation.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/loop_report.py`, `src/trade_plan_monitor/backtest/loop_runner.py`, `tests/unit/test_monitor_loop_report.py`, `tests/integration/test_monitor_loop_valuation.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A01, ML-A03, ML-A09, ML-A12, ML-A13, ML-A15.
- **实施边界:** 为评估、捕获提醒、响应请求、执行、结果状态和估值定义独立的 `backtest-report-v4` 及类型化 `monitor-loop-event-v1` 信封。在 `LoopRunner` 通过可选报告写入者流式计算规范有序事件摘要，保留既有尝试回调和私有循环行为。初始市值权益只用明确有效的初始估值，绝不使用批次成本或稍后报价。分别保留成本损益、区间收益、已付费用和绝对滑点；未知持仓/现金/价格及零分母保留空指标。记录原始边界及实际证据/估值时间，不在结束时清仓。报告物化/留存和工作线程接入仍由 ML-T21/ML-T19 完成。
- **证据:** MV31：24 项报告专项检查及 137 项最终相关回归通过；零分母变异产生 1 项预期失败、恢复精确字节。完整因果链、风险/到期/观察、成本与市值差异、未知/零值、规范摘要、相同回放、写入故障及取消不产生完成报告均验证。ML-T20 完成，下一项 ML-T21，随后 ML-T19；不改变交付数量或验收标准。

## ML-T21. 原子发布与保留闭环结果

- [x] 完成实现和本项验证.
- **依赖:** `ML-T17`, `ML-T20`
- **验收:** 流式类型化事件，验证存储输入/报告哈希，仅发布完整运行。失败/取消/超限不留下已完成部分报告。总共保留最新 30 条已物化历史运行，按发布/保留时间降序、run_id 破同序。发布后既有有界维护删除最旧超额摘要/成交/详情，置顶不绕过上限。保护排队/运行引用、共享数据集/快照及保留冻结单计划输入。既有导出保持字节兼容，不新增清理调度器或资源预算框架。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_publication.py tests/integration/test_monitor_loop_retention.py tests/integration/test_backtest_publication.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/loop_publication.py`, `src/trade_plan_monitor/backtest/loop_input_store.py`, `src/trade_plan_monitor/backtest/loop_account.py`, `src/trade_plan_monitor/backtest/jobs/maintenance.py`, `tests/integration/test_monitor_loop_publication.py`, `tests/integration/test_monitor_loop_retention.py`, `tests/integration/test_backtest_results.py`
- **范围:** M，实施前拆为两个分段；**追溯:** ML-A09, ML-A10.
- **实施分段:** ML-T21.1 在 `results.py`、`loop_publication.py`、`loop_input_store.py`、`loop_account.py` 的共用纯期初状态构造及其发布测试完成类型化暂存/发布（5 个文件）。ML-T21.2 在 `results.py`、`loop_input_store.py`、`jobs/maintenance.py` 及其留存测试完成有界整次运行/文件留存（4 个文件）。工作线程调用仍由 ML-T19 完成。既有规范存储信封保持版本兼容，用明确的 `backtest-report-v4`/`monitor-loop-event-v1` 载荷标识新语义。大型报告头部以既有对象边界内的不可变结果文件保存，保留 32 KiB 行限制。既有决策工件族保存有序类型化审计，既有成交账本保存已提交收据；在既有令牌保护的发布前验证输入/报告绑定、逐条审计/成交及暂存修订。复用既有调用者预算的维护事务和归属标记，安全有界清理文件，不增加调度器、数据库或队列。
- **兼容性验证边界：** ML-T21.2 同步更新现有 `tests/integration/test_backtest_results.py` 中被最新 30 次总量策略替代的旧保留数量断言（合计 5 个主要文件）。保留年龄、分批预算、共享输入及导出回归断言，不降低检查要求。
- **证据:** MV32：22 项最终任务检查及 118 项相关回归通过；最近 30 次上限变异产生 1 项预期失败，恢复精确字节。任务令牌原子发布、部分/取消/损坏拒绝、逐条成交审计绑定、总量/时间/并列顺序、置顶不豁免、有界归属文件清理及未完成预留/任务保护已验证。下一项 ML-T19 接入后台消费及完成后的既有维护调用。

### ML-C07. 检查点

- [x] 工作者只发布完整且依赖保留正确的结果。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T22. 提供分页闭环结果，保留导出兼容

- [x] 完成实现和本项验证.
- **依赖:** `ML-T21`
- **验收:** 结果/详情以稳定分页/模式标识暴露类型化闭环事件、冻结计划来源及截止覆盖。保留旧摘要及支持模式 CSV/JSON 字节。不新增闭环导出格式/路由/UI/任务/互斥。重投影使用自有线程和有界分页，背压仅影响回测准入。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_result_api.py tests/integration/test_backtest_exports.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_runs.py`, `tests/integration/test_monitor_loop_result_api.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A09, ML-A10, ML-A15.
- **实现边界：** 补齐既有结果行读取和既有运行响应联合类型，同时实现专属线程投影、有界结果类型及聚焦 HTTP 测试。保留既有路由、游标、导出格式和旧模式字节；不增加调度器、队列、锁或批准更新。
- **证据:** MV34：12 项闭环结果检查，最终任务/导出/生产组合门禁 44 项通过、1 项既有环境跳过，相关回归 189 项通过。分页、原生因果哈希、冻结来源、截止时间、未知/零值、详情过期、固定标记及线程背压验证；身份保护变异产生 1 项预期失败并恢复精确字节。旧导出兼容，闭环导出在响应流之前拒绝。下一项 ML-T23，批准保持待 ML-T29。

## ML-T23. 生成最终运行与结果契约

- [x] 完成实现和本项验证.
- **依赖:** `ML-T18`, `ML-T22`
- **验收:** 在真实运行/结果 API 变化后重新生成，校验新旧区分载荷、上限和安全整数。批准摘要留待 ML-T29 审阅，不消除基线批准失败断言。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **主要文件:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_monitor_loop_contract.py`, `scripts/generate_frontend_types.py`, `web/src/components/backtests/BacktestDetailTable.vue`, `web/src/components/backtests/BacktestFillTable.vue`, `web/src/components/backtests/BacktestRunTable.vue`, `web/tests/unit/backtestsApi.spec.ts`
- **范围:** M (10 个主要文件，分三片实施); **追溯:** ML-A09, ML-A10.
- **实施分片:** ML-T23.1 修正判别标签生成并增加聚焦契约测试（2 个文件）；ML-T23.2 生成既有两套配置（4 个文件）；ML-T23.3 使既有表格及 API 测试夹具准确处理新类型（4 个文件）。不增加完整闭环时间线、新路由/导出、生命周期或批准更新；ML-T25 负责完整结果体验。
- **证据:** MV35：两套真实运行/结果契约生成并保持最新。专项 11 项、相关契约 50 项、前端回归 114 项通过，前端类型检查通过。标签生成变异产生 1 项预期失败并恢复精确字节；2 项既有批准门禁独立验证仍未批准，未改摘要或路径许可。下一项 ML-T24，最终批准保持 ML-T29。

## ML-T24. 从既有运行表单提交一份准备计划

- [x] 完成实现和本项验证.
- **依赖:** `ML-T15`, `ML-T23`
- **验收:** 使用一份已审核快照及提取的期初账户，无需原始操作 JSON。结束在服务端默认解析。展示截止、缺失事实及不支持条款，接入既有任务/结果导航，不含多计划选择。
- **验证:** `npm --prefix web run test -- --run tests/unit/MonitorLoopRunForm.spec.ts`
- **主要文件:** `web/src/components/backtests/BacktestRunForm.vue`, `web/src/composables/useBacktestRunForm.ts`, `web/src/api/backtests.ts`, `web/src/views/BacktestNewView.vue`, `web/tests/unit/MonitorLoopRunForm.spec.ts`, `web/tests/unit/BacktestNewView.spec.ts`, `web/tests/unit/BacktestAccessibility.spec.ts`
- **范围:** M (7 个主要文件，分两片实施); **追溯:** ML-A10, ML-A12, ML-A14, ML-A15.
- **夹具兼容:** 类型检查要求既有无障碍表单夹具包含新增字段。仅补齐其值，保留全部既有无障碍断言。
- **实施分片:** ML-T24.1 扩展既有 API/组合函数及聚焦测试（3 个文件）；ML-T24.2 接入既有表单/页面并修正过时的未知结果替换断言（含共享测试共 4 个文件）。提交待确认时冻结原文/运行控件，保留精确重试身份。表单说明服务端结束时间解析；完成后的既有已验证结果边界提供精确截止时间，完整展示由 ML-T25 接入。提交时保留无关页面标题修改。
- **证据:** MV36：准备提交专项 11 项及相关前端回归共 195 项通过，类型检查通过。待确认结果改写请求的变异检查产生 1 项预期失败，精确字节已恢复。单份冻结计划/账户、服务端默认结束、原请求重试、准备互斥及既有导航已验证；无关页面标题修改保留。ML-C08 完成，下一项 ML-T25，最终批准仍为 ML-T29。

### ML-C08. 检查点

- [x] 结果 API 和运行创建兼容新旧契约，既有导出保持兼容，不新增开发。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。

## ML-T25. 在结果中解释计划与执行历史

- [x] 完成实现和本项验证.
- **依赖:** `ML-T22`, `ML-T23`
- **验收:** 将分页因果事件及冻结单计划来源接入结果页，区分持仓、阻断/未成交意图与成交。展示账户演进、有效指标及实际截止，无客户端交易逻辑或版本切换时间线。
- **验证:** `npm --prefix web run test -- --run tests/unit/MonitorLoopResults.spec.ts`
- **主要文件:** `web/src/components/backtests/MonitorLoopTimeline.vue`, `web/src/components/backtests/MonitorLoopSummary.vue`, `web/src/views/BacktestRunDetailView.vue`, `web/src/composables/useBacktestResults.ts`, `web/src/api/backtests.ts`, `web/src/api/monitorLoopValues.ts`, `web/src/components/backtests/BacktestResultActions.vue`, `web/tests/unit/MonitorLoopResults.spec.ts`, `web/tests/fixtures/monitor-loop-results.json`, `web/tests/unit/backtestsApi.spec.ts`
- **范围:** M (10 个主要文件，分三片实施); **追溯:** ML-A01, ML-A10, ML-A13, ML-A15.
- **夹具兼容:** 先收窄一处既有旧 API 断言，再读取旧类型独有的假设；保留该断言及全部旧行为检查。
- **实施分片:** ML-T25.1 用真实后端响应夹具验证既有原生 HTTP 类型（API/校验器/夹具/测试，4 个文件）；ML-T25.2 在既有页面接入只读汇总和时间线（组件/页面/测试，4 个文件）；ML-T25.3 扩展既有结果组合函数及固定操作，隐藏不支持的原生导出（含共享测试共 3 个文件）。保留无关页面标题修改。不增加路由、导出、重放、交易计算或计划切换支持。
- **证据:** MV37：原生结果专项 17 项、相关前端共 157 项通过，类型检查通过。真实 Chrome 验证 1440/390 像素、32 条因果事件及当前资源的 2 次请求，无运行错误或横向溢出。输入/来源绑定变异产生 1 项预期失败并恢复精确字节。实际 HTTP 夹具、分页、固定、过期与未知/零展示已验证；无关页面标题修改保留。下一项 ML-T26，最终批准仍为 ML-T29。

## ML-T26. 证明一致性、因果性与故障原子性

- [x] 完成实现和本项验证.
- **依赖:** `ML-T05`, `ML-T11`, `ML-T16`, `ML-T21`, `ML-T34`
- **验收:** 以独立预期输出对比在线参与者与闭环状态，修改未来证据并注入事务/工作者故障。做一次关键约束变异检查，虚拟 AI/供应商/出口计数证明隔离。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_parity.py tests/integration/test_monitor_loop_faults.py tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **主要文件:** `tests/integration/test_monitor_loop_parity.py`, `tests/integration/test_monitor_loop_faults.py`, `tests/fixtures/monitor-loop/scenarios.json`, `tests/integration/test_plan_preparation_worker.py`, `src/trade_plan_monitor/backtest/loop_report.py`, `web/tests/fixtures/monitor-loop-results.json`
- **范围:** M (6 个主要文件，分两片实施); **追溯:** ML-A01–ML-A24，排除已取消 ML-A07。
- **实施分片:** ML-T26.1 增加独立在线/预期值与未来证据检查，必要时在证明后最小修正因果事件身份（3 个文件）；ML-T26.2 覆盖事务/工作者/准备故障，并在身份修正后更新真实 HTTP 夹具（3 个文件）。完整事件流摘要和独立运行绑定仍须检出跨运行替换；不增加模式字段、调度器或执行策略。
- **证据:** MV38：89 项后端检查通过，包括独立在线 15 次评估、两笔成交的字面量预期值及账户/发布/工作线程/准备故障。因果身份变异按预期失败并恢复精确字节；实际 HTTP 夹具已刷新。下一项 ML-T35，最终批准仍为 ML-T29。


## ML-T27. 验证完整浏览器流程

- [x] 完成实现和本项验证.
- **依赖:** `ML-T24`, `ML-T25`, `ML-T26`, `ML-T36`
- **验收:** 真实挂载 API/组合配虚拟外部服务，贯通上传→重试/编辑→审核→运行→结果。证明夹具未预写未来交易，不只测假结果页，不访问真实用户库。 加入服务停止/未知取消/恢复导航，监控页面保持可用。
- **验证:** `npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts`; `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_production_composition.py -q -m "not live"`
- **主要文件:** `web/tests/e2e/monitor-loop-backtest.spec.ts`, `web/tests/fixtures/monitor-loop.json`, `tests/integration/test_monitor_loop_production_composition.py`, `web/src/router.ts`, `web/src/views/BacktestNewView.vue`, `src/trade_plan_monitor/web/preparation_schemas.py`, `web/tests/fixtures/plan-preparation-review.json`
- **范围:** M (7 个主要文件，含已验证的导航与冻结身份修正); **追溯:** ML-A10, ML-A16, ML-A18.

- **验证驱动修正:** 真实浏览器证明保存原文后 URL 未绑定准备记录，刷新/返回会丢失目标。仅补充已接受记录的 URL 身份及路由初始载入；共享页面标题修改保留。

冻结身份修正：浏览器证明 FROZEN 进度投影公开了存储候选摘要，而非运行提交要求的权威准备清单摘要。现有 candidateHash 改为由已验证冻结清单投影，保留提取/存储绑定并刷新类型夹具。不改变 API 字段/路径或 Schema。

### ML-C09. 检查点

- [x] 独立故障/一致性与完整浏览器流程通过。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。
- **证据:** MV42：2 条真实 Chrome 流程、75 项后端检查、96 项前端检查和类型检查通过。浏览器发现并验证了局部导航与权威冻结身份修正。移除冻结身份投影产生 1 个预期失败，已精确恢复。C09 通过；接续 ML-T37。


## ML-T28. 记录操作指南与实际验证证据

- [x] 完成实现和本项验证.
- **依赖:** `ML-T27`, `ML-T37`
- **验收:** 双语记录实际支持的 API/UI 行为及原文限制。执行方案相关最终检查并记录真实结果、未解决失败和证据范围，不宣称真实 AI/供应商认证。
- **验证:** `git diff --check`
- **主要文件:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`, `web/tests/e2e/backtests.spec.ts`
- **范围:** M (5 个主要文件，含操作证据及已验证的旧浏览器夹具修正); **追溯:** ML-A01–ML-A24，排除已取消 ML-A07。

最终检查修正：完整真实 Chrome 套件发现旧浏览器夹具未处理新增惰性服务状态读取，主动返回 500。仅补齐明确夹具契约，保留所有错误/请求/缩放/溢出断言及无关界面修改。
- **证据:** MV44：双语操作说明覆盖已实现单计划来源/审核/运行/结果、精确账户/截止语义、单个未完成任务、取消/未知恢复、导出兼容及实测负载边界。最终相关检查通过：58 项后端、935 项前端、类型检查、构建、34 项真实 Chrome 流程、Ruff 及两份生成接口。两项不变的精确接口审批门禁仍待 ML-T29，保留其真实失败。ML-T28 完成，接续 ML-T38。


## ML-T29. 对齐已审阅规格与API批准

- [x] 完成实现和本项验证.
- **依赖:** `ML-T23`, `ML-T28`, `ML-T38`, `ML-T39`
- **验收:** 结合双语契约审阅最终 API/行为差异，仅记录由此批准的快照身份和最终实现范围。保留旧批准历史，明确区分此前已知基线不一致。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py -q -m "not live"`
- **主要文件:** `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.md`, `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.zh-CN.md`, `docs/specifications/monitoring/SPEC-unified-plan.md`, `docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md`, `tests/integration/test_openapi_snapshot.py`
- **范围:** M (5 个主要文件，含审阅规范及精确批准路径白名单); **追溯:** ML-A09, ML-A10.

### ML-C10. 检查点

- [x] ML-A01–ML-A24 中活动证据（排除已取消 ML-A07）及双语审核契约完整。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。
- **证据:** MV46：最终审阅保留全部 52 条原路径，仅批准 10 条新增路径及已记录原生增量分支，并保留历史身份。两份已审阅快照/类型与已提交源码一致。精确白名单、双语批准、公共错误及生成 TypeScript 门禁通过：51 项集成与 18 项服务值检查。删除一条批准路径会失败，精确恢复字节后通过。C10 完成，全部 37 个活动任务及用户要求本轮 20 项完成。


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

- [x] 完成实现和本项验证。
- **依赖:** `ML-T12`, `ML-T23`, `ML-T33`, `ML-T34`
- **验收:** 未使用时状态/停止无副作用，真正数据/操作请求通过 guard/校验后激活所需能力。恢复按 epoch/修订/幂等明确重试准备或已选 resumeJobIds（<=1）。局部 503/Retry-After 表示任务未准入，初始化轮询不能重启失败准备。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_service_api.py -q -m "not live"`
- **主要文件:** `src/trade_plan_monitor/web/routers/backtest_service.py`, `src/trade_plan_monitor/web/backtest_service_schemas.py`, `src/trade_plan_monitor/web/app.py`, `src/trade_plan_monitor/backtest/service_lifecycle.py`, `tests/integration/test_backtest_service_api.py`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A19, ML-A21, ML-A24.
- **证据:** MV39：77 项检查通过，另有 1 项既有环境跳过。启动身份/修订/幂等、单个指定恢复、首次失败缓存、实际排空后修复、无启动副作用的状态/停止及 1000 回执上限均通过。移除启动身份保护产生 1 项预期失败并恢复精确字节。下一项 ML-T39。


## ML-T39. 生成独立服务传输契约

- [x] 完成实现和本项验证。
- **依赖:** `ML-T35`
- **验收:** 生成已挂载服务资源及强类型能力/错误，覆盖两种契约 profile。检查监控端点和未受影响载荷语义不变；陈旧批准记录留待明确最终审阅。不手写重复传输模型。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_service_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **主要文件:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_backtest_service_contract.py`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A19, ML-A24.
- **证据:** MV40：37 项契约检查及前端类型检查通过，两套生成契约均为最新。两项既有批准门禁仍待 ML-T29，快照为 dde2866b81a9710a51bf7817eeeb30513cfb4e844437adba7a2ef202fd52caa0。扩大恢复数量上限产生两项预期失败并恢复精确字节。下一项 ML-T36。


## ML-T36. 网页显示首次使用准备与局部恢复

- [x] 完成实现和本项验证。
- **依赖:** `ML-T39`
- **验收:** 仅活跃回测数据请求触发惰性准备，路由预取/全局状态轮询无副作用。区分未用/初始化/读取就绪/执行就绪/失败，503 保留表单并复用变更键。打开历史不恢复任务/AI，明确重试/恢复展示选中积压，监控可用。
- **验证:** `npm --prefix web run test -- --run tests/unit/BacktestServiceState.spec.ts`; `npm --prefix web run type-check`
- **主要文件:** `web/src/api/backtestService.ts`, `web/src/composables/useBacktestService.ts`, `web/src/components/backtests/BacktestServiceState.vue`, `web/src/layouts/AppShell.vue`, `web/src/composables/useBacktestRunForm.ts`, `web/tests/unit/BacktestServiceState.spec.ts`
- **范围:** M (5 个主要文件，含测试); **追溯:** ML-A21, ML-A24.

- **实施分片:** 先完成独立 API/组合函数/状态组件及专项测试，再接入仅活动回测路由的共享布局和既有提交请求的 503 保留；不在预取或监控路由进行服务控制。
- **证据:** MV41：前端全部 935 项检查、类型检查及生产构建通过。真实 Chrome 验证只读历史及一次明确勾选恢复，在 1440/390/320 像素下无运行错误或溢出。移除 503 请求保留产生 1 项预期失败并恢复精确字节。下一项 ML-T27。


## ML-T37. 验证 Windows 惰性激活与线程边界

- [x] 完成实现和本项验证。
- **依赖:** `ML-T26`, `ML-T27`, `ML-T34`, `ML-T36`
- **验收:** 证明应用启动/监控导航/状态/预取/关闭零回测工作、并发首次使用只初始化一次、只读历史不执行积压、明确选择恢复。可控夹具注入首次使用错误/晚到 future/取消竞态，保留 ML17 10 只股票负载门槛及已接受线程限制。
- **验证:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_isolation_fault_matrix.py tests/integration/test_monitor_loop_parity.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/verify_backtest_thread_load.py --profile windows-threads --offline`
- **主要文件:** `tests/integration/test_backtest_isolation_fault_matrix.py`, `tests/fixtures/monitor-loop/isolation.json`, `scripts/verify_backtest_thread_load.py`, `tests/integration/test_backtest_sync_pacing.py`, `src/trade_plan_monitor/backtest/loop_publication.py`, `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/backtest/results.py`, `tests/integration/test_monitor_loop_publication.py`, `src/trade_plan_monitor/state/daily_accounting.py`, `tests/unit/test_daily_safety_boundaries.py`, `src/trade_plan_monitor/runtime/daily_service.py`
- **范围:** M (11 个主要文件，含已验证的发布、繁忙重试及事务内旧数据扫描修正); **追溯:** ML-A08, ML-A19–ML-A24.

验证驱动修正：真实准入负载证明，不同响应延迟的顺序原生运行会在全局回执成交键上碰撞。仅将内部存储成交键绑定 run_id，保留公开回执标识，并严格验证/重放既有旧行。不改变 Schema/API 路径或权限/事件身份。


负载夹具纠正：首次 600/600 秒无节奏回放压力在阶段末超过固定监测节奏。保留失败、全部原有时长/延迟/完整性门禁和完全相同的真实监测负载；仅将离线回放准入起点间隔调整为至少 120 秒，遵循 ML17 允许降低已准入负载的约定。最终断言前记录阶段轮次与耗时，使失败门禁仍保留实际测量。不修改生产监测或资源控制器。


进一步实测纠正：5 秒夹具完成全部评估，但暴露至少 30 份输入维护争用、原始 SQLite 繁忙异常及 7340.370 ms 调度 p99。保留失败报告及严格清理验证。仅将真实 SQLITE_BUSY/SQLITE_LOCKED 元数据调用错误转换为既有 503/Retry-After，保留原意图重试，其他 SQL 故障继续抛出。离线验收 profile 每十分钟最多准入五次原生实验（起点间隔 >=120 秒），全部原监测节奏/延迟/完整性门禁保持。不增加生产节奏、锁或通用资源系统。


实测监测纠正：即使每十分钟五次回放，历史增长仍导致失败。可控十股票单轮耗时 0.964 秒，legacy_reason 占 0.631 秒 / 24,390 次 JSON 解析，每股票扫描两次；写锁仅占 0.119 秒，保持不变。仅利用既有 SQLite JSON 支持筛选 EVALUATION 兼容候选，保留原 Python 判定及损坏/非对象错误语义，增加有界解析/末尾旧记录/损坏数据安全用例。不新增缓存、模式、监测规则、任务框架或质量门槛变化。

事务内扫描修正：真实累计历史剖析证明同一评估事务重复解析历史占据主要耗时。仅在 SQL 中筛去无旧订单标记的当前 EVALUATION 行，保留损坏/非对象/重复键的原 Python 检查，并在同一事务内复用一次旧数据判定；不增加持久缓存、修改历史数据或改变监测规则。准入脚本显式遵守名义阶段截止时间，结束后的排空不再启动额外实验。
- **证据:** MV43：Windows 600/600 秒十股票负载通过，完成 5 次顺序原生运行及精确 12000 次评估，无重复/缺失语义提醒。最终 209 项相关回归及 131 项共享运行时/账本检查通过，1 项既有环境条件跳过；Ruff 通过。公开成交身份稳定，内部存储绑定运行，旧记录精确重试通过。保留首次无节奏失败，全部原有门槛保持。ML-T37 完成，接续 ML-T28。


## ML-T38. 记录按需线程操作指导

- [x] 完成实现和本项验证。
- **依赖:** `ML-T37`
- **验收:** 双语指导解释休眠启动、首次准备、元数据与执行、明确积压恢复、局部修复和感知排空停止。说明共享进程风险，不必升级进程，保留身份及历史基线批准不一致与其审阅修复记录。
- **验证:** `git diff --check`
- **主要文件:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`
- **范围:** M (4 个主要文件，含测试); **追溯:** ML-A19–ML-A24.

### ML-C13. 检查点

- [x] 服务 API/UI 及有记录的 Windows 线程故障/负载验收通过；ML-C10 仍为最终合并门槛。
- [x] 记录实际证据；失败不降低门槛，先修复再继续依赖工作。
- **证据:** MV45：双语说明记录休眠启动、明确元数据/执行权限、只恢复一个明确选择的任务、局部修复、控制确认与实际排空、启动/修订/幂等防护及已接受共同进程限制。引用实际 MV43 负载及 MV44 最终/浏览器证据，不重跑或扩大其结论。C13 完成，仅余 ML-T29/C10 最终审阅批准。


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

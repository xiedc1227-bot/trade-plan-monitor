# 独立审查：日线模拟交易范围清理

日期：2026-10-02。审查员：独立 Astra/high 代理。英文版为规范输入；本 `.zh-CN.md` 为语义等价的中文审阅副本。

## R01. 范围与当前结论

**最终独立结论：本次冻结改动的已审范围内无剩余实质问题；C1–C7 全部 CLOSED。** 首轮结论为 Request changes。下文保留每项原始反例；只有独立重读源码并定向验证后才关闭问题。协调员的独立验证门禁现已按 R05 的两轮覆盖证据满足；不表述为单次全量全绿。

本次以[清理契约](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/030075c4946bf34833a0155fde6b4deda3c79055/tasks/2026-10-02-daily-plan-simulation-cleanup.zh-CN.md)和 [SPEC-daily-plan](../specifications/monitoring/SPEC-daily-plan.zh-CN.md)为准。审查日线券商执行跟踪是否真正删除，并替换为用户明确操作、原子提交、100股整数倍的完整模拟交易；同时检查技术风险、当前权限、库存隔离、旧数据诊断和共享旧能力的保留。[2026-10-01审查](2026-10-01-daily-plan-independent-review.zh-CN.md)仅为旧范围的历史证据，其中协调员运行的6065项测试不是本轮门禁。

本审查员只读源码和测试。离线反例使用临时 SQLite 和假 SDK。未使用实时行情、AI、通知发送、生产数据库、提交、推送或部署。新的完整后端测试由协调员负责。

## R02. 问题与独立反例

下列位置指首轮源码，后续修改可能改变行号。临时反例是诊断证据，不能代替永久回归测试。

| ID | 严重级别 / 状态 | 位置与故障 | 必须修复与回归 |
|---|---|---|---|
| C1 | P2 / CLOSED | `src/trade_plan_monitor/runtime/daily_service.py:146–149`，`reevaluate_version`：日历升序 `limit(1000)` 在已有超过1000个历史开市日时裁掉当日和未来交易日。原本 READY 的100股信号，经公开修改操作使用的同一重评入口后变成 `quote.tradable=False`，尽管当日已有认证开市记录。 | 读取包含当日、下一交易日和恢复证明的有界日线日历窗口，保留3000历史自然日 / 32未来自然日边界。用超过1000个存储开市日回归公开修改后的重评，不扩大无关旧日历行为。 |
| C2 | P2 / CLOSED | `src/trade_plan_monitor/web/daily_service.py:360–361`，`_simulate`：任意 `state.data_blockers` 都拒绝所有模拟。已 CONFIRMED 的严重风险，CORE100已结算，当日认证开市且报价新鲜、已核验可交易，运行结果为 `risk_action.core_qty=100`；但辅助日线缺失（`DAILY_QFQ_PROVIDER_UNAVAILABLE`）导致 POST 返回 `409 DAILY_SIMULATION_CURRENT_EVALUATION_REQUIRED`。 | 保留普通交易输入门槛；锁定风险退出按当前 cause、事实、库存、交易日、报价和可交易状态校验，不强求无关辅助日线。回归真实 POST，并验证确实缺少执行权限时零变更。 |
| C3 | P2 / CLOSED | `src/trade_plan_monitor/runtime/production.py:4208` 与 `runtime/daily_service.py:102`：`run_target` 在旧数据检查之前进入生产准备。保留的旧评估 head 含 `inventory.orders`，GET 正确显示 UNSUPPORTED，但真实生产准备先用新严格模型解析并抛出 `ValidationError`。 | 在严格解析 head 或获取提供商数据前识别不支持的开发数据，返回不可执行诊断并保留原始记录。回归生产 factory/preparation 及其他修改/恢复入口，不能只测 GET 或直接 `run_inputs`。 |
| C4 | P1 / CLOSED | `src/trade_plan_monitor/notifications/outbox.py:790–820`，`_event_from_row`：不变的 `daily-plan-alert-v1` 标记直接由新模拟载荷模型解析。旧合法 `filled_qty`、`REGISTER_ACTUAL_EXECUTION` 及精确历史文案现在触发 `OutboxStorageError`。一条旧记录就使未按股票过滤的共享 `list_events` 失败，影响其他股票，并可能影响待发送恢复。 | 保留旧字节为明确过期、不可发送的历史，不把成交转换成模拟，也不恢复券商执行工作流。覆盖共享列表、单条读取、已阅和待发送恢复；其他旧 schema 和新股票仍须可用。 |
| C5 | P2 / CLOSED | `src/trade_plan_monitor/runtime/daily_service.py:233–237`：DATE_RANGE/TRADING_DAY 启用范围到期拒绝整个运行提交，连已有 CONFIRMED 风险也被挡住。仅周五有效的计划周五确认严重风险、最早周二执行；周二新鲜报价评估抛出 `daily runtime commit admission is closed`。生产资格过滤也可能移除该目标。 | 到期后保留已锁定风险的当前评估及明确模拟操作，不新增普通信号权限、不改变旧 schema 启用规则。回归真实生产 target/deadline/recovery 与公开操作。协调员已确认 D07 / DP-A16 要求修复此项。 |
| C6 | P1 / CLOSED | `src/trade_plan_monitor/web/plan_service.py:1092` / `web/routers/plans.py` 与 `runtime/production.py:1198`：保留的 ACTIVE 开发版 Schema4 文档含旧券商 `trading_rules`，虽已识别过期，`PlanVersionView` 却拒绝带阻塞的active行，GET失败。生产active计划枚举同样严格解析该旧文档，返回任何目标前就抛 `PlanDocumentError`，影响其他股票。 | 保留原文档/哈希/来源/启用证据，明确只读过期状态并拒绝执行，不改写原行而排除不兼容日线目标。用其他不受影响的股票一起覆盖公开版本/列表及所有生产active枚举、权限和恢复入口。 |
| C7 | P2 / CLOSED | `src/trade_plan_monitor/runtime/daily_service.py:488–506`：SIGNAL_INVALIDATION事实无条件将已SIMULATED信号改为INVALIDATED，却保留 `simulated_qty=planned_qty`，新原子消费模型拒绝此不一致状态。事实已提交，其POST因此失败，之后评估持续同样失败。 | 保留SIMULATED及其不可变的完整消费/回执；后续失效事实保留审计，不回退已完成模拟。回归真实事实POST、即时评估、重启和拒绝第二次交易。 |

独立临时反例保存在 `D:/Workspace/Projects/ai-quant-pilot/Temp/test_daily_simulation_review.py`：

- C1 和 C2：2项失败，2.21s；C1断言重评后当日认证可交易，C2通过 POST 断言锁定风险完整模拟可成功。
- C3：1项失败，1.93s；使用 `ProductionDailyChain`、真实生产服务/preparation绑定和假 SDK。仅将存储 head 改为应保留的旧形状，并先验证公开 GET 为 UNSUPPORTED。
- C4：1项失败，1.68s；用基线旧字段、旧去重哈希和精确基线文案还原存储提醒，再读取共享 outbox 列表。失败为 `OutboxStorageError`，不是测试调用参数错误。

- C5：1项失败，1.71s。已审核的仅周五 DATE_RANGE 计划，初始化 CORE100 并提交两项严重风险事实，到期前达到 CONFIRMED，随后无法评估周二退出。

- C6：独立参数化公开 GET 与真实生产目标枚举，2项失败，2.74s。临时旧文档含原6个券商规则字段及匹配的规范SHA，持久ACTIVE绑定保留。

- C7：成功完整BUY100后，通过公开SIGNAL_INVALIDATION事实引用该信号，1项失败，1.97s。失败发生在即时重评的持久 `DailySignalState` 校验。

## R03. 审阅覆盖与检查

已完整读取新的模拟记账及事务、日线仓库/状态模型、数量/域契约、普通信号生命周期、风险执行、运行投影和发送权限、生产输入准备及不支持数据路径。已完整读取日线操作/表单/工作台 Vue 源码、composable和相关UI schema行为，包含未跟踪新文件。检索了日线源码的券商订单字段/状态，确认剩余 REPORT 引用用于保留存储/诊断。

已读记账实现使用日线 POSITION/SIMULATION 记录和取得日期，不读取、写入或锁定共享真实 `PositionLot`、`PositionInventoryConfirmation`、期初余额或 `PositionInventoryState`。模拟事务在原子持久化库存/消费/回执之前，核验当前审核/启用、cause和库存版本、当前事实、报价/交易时段、完整整手数量和策略权限。提醒不改变库存。UI绑定完整数量和当前版本，保留技术风险 PENDING，不再提供券商回报/部分成交/内部扣账表单。

独立定向运行：`tests/integration/test_daily_simulation.py`、`tests/integration/test_daily_history_regression.py`、`tests/unit/test_daily_lifecycle.py`、`tests/unit/test_daily_plan.py`：**32 passed, 1 failed, 1 warning，10.83s**。失败的旧风险诊断用例在实现仍改动时遇到 `read_daily` 局部 `json` 导入导致的暂态 `NameError`，已通知实现者。这不是通过的最终门禁，将纳入旧数据边界复查。

实现者冻结 C1–C3 后的独立复查：原临时三反例通过（**3 passed，2.59s**）。重读了完整有界日历查询、按cause区分的辅助数据门槛，以及runtime和生产准备两处提前识别旧数据的检查。随后四文件定向组合通过（**33 passed，10.25s**），包含修复后的旧风险诊断。另独立编写发送竞争反例：禁用运行重评后提交SIGNAL_INVALIDATION，发送权限从允许转为拒绝（**1 passed，1.60s**）。据此关闭C1–C3并确认当前事实的发送校验，最终仍检查最后差异。

进一步独立后端检查：扩展临时组合 **10项通过，10.38s**，包含明确使用原 `daily-plan-alert-v1` 标记的C4、C5运行到期、C6 API/production、C7和事实校验。组合还独立关闭周五production lifespan，在到期后的周二用同一SQLite重建composition，保留锁定目标，运行5次真实分钟deadline，执行完整风险模拟，并确认完成后摘除目标（**单独1 passed，6.30s**）。该中间检查点的C4–C7仍待最终源码和消费端审阅；现已按下文完成。

C6消费端补充：真实公开API对完整但未审核日线草稿返回 `canActivate=false`、空 `reviewIssues`/`validationIssues`/`dailyIssues`、`reviewId=null`。通过Vite加载真实 `web/src/api/plans.ts`，将该响应交给 `createPlanApi.getPlanVersion`，仍在HTTP200抛 `INVALID_RESPONSE`。解析器仅凭问题列表为空推导启用资格，漏掉日线审核绑定。已直接交UI实现者做仅针对日线契约的修复，保留旧schema严格校验。

## R04. 最终关闭与独立证据

最终源码审查关闭 C4–C7：

- **C4：** 新提醒使用 `daily-simulation-alert-v1`。原 `daily-plan-alert-v1` 记录通过独立的类型化 UNSUPPORTED 只读视图保留存储的文案、身份、时间和原始载荷。共享 list/get/ack/replay 仍可用。dispatcher 的无条件保护即使在 `enforce_current_plan=False` 时也拒绝过期事件；不会把旧成交转换成模拟。前端提醒解析器和表格明确区分这些变体与未改动的旧版/显式提醒。
- **C5：** 生产 active targets、权限消费者、提交准入和启动恢复在计划到期后保留已锁定的日线风险，不续授普通权限或新 cause。独立验证的真实 composition 重启及五次分钟 deadline 流程能完成完整风险模拟，并移除已完成目标。旧 schema 的启用行为保持独立。
- **C6：** 已识别的过期 Schema 4 文档只读保留，不改写原文/hash/active binding；公开列表/详情和全局生产读取隔离该文档，同时另一只已审核股票仍可用。分钟消费者原有的文档解析失败处理仍有效；新增全局过滤只针对已识别的过期日线文档。最终前端解析保留旧 schema 严格校验，并检查日线身份、mapping/content hash、审核 hashes/revision 和审核绑定。独立将同一版本真实审核前后 API JSON 交给 Vite SSR 加载的模块，均读取成功，`canActivate` 分别为 `false` 与 `true`。
- **C7：** 后续失效事实不会替换 SIMULATED 状态或不可变的完整消费记录。永久回归和独立原反例覆盖公开事实提交、即时重评、重启、无重复提醒、新 key 二次交易被拒绝以及仅一条持久回执。

最终独立定向后端检查（不是全量运行）：

| 范围 | 结果 |
|---|---|
| 13 个日线文件：simulation review regressions、simulation、history、production reevaluation、sparse calendar、scope HTTP、simulation contract、plan、review、extraction、lifecycle、risk、risk allocation | **79 passed，1 warning，38.12s** |
| 共享 `test_notification_outbox.py`、`test_notification_delivery.py`、`test_alert_production_composition.py` | **89 passed，1 warning，6.08s** |
| 最后数量机械改动：单项/合计超安全整数的初始化 API 反例与 `test_daily_plan.py` | **8 passed，1 warning，1.49s** |
| 实际 API JSON 经过 Vite SSR 加载的真实 `createPlanApi` 模块 | **未审核与已审核响应均成功；exit 0** |

警告为 Starlette/httpx TestClient 弃用提示。最终数量审查核对了非负/正整手类型的 `9_007_199_254_740_991` 上限、初始化合计上限及受计划最大仓位限制的目标；未改变冻结旧域契约的通用数量/revision 含义。固定软件 `trading_rules` 使用服务端 PRODUCT_CONTRACT 绑定，没有新增券商证据表单。

最终覆盖还包括拒绝少于完整计划的数量、max 300 与独立下一次 BUY、普通 SELL/CORE 保护、初始化重试不重置、T+1、幂等/body 冲突、当前事实/库存发送围栏、旧 REPORT/POSITION/head/非整手风险/layout 的不支持诊断，以及基本面范围拒绝。与清理前快照对比确认 shared 真实库存模型/repositories/unit-of-work、共享 runtime service、日线指标/conditions/scope 和 monitor composition 未变。新日线记账没有读取/写入/锁定共享真实库存的路径。这些证据支持限定的兼容边界，并不声称穷尽证明所有既有行为。

## R05. 最终协调员门禁与限制

最终源码冻结后，协调员实际运行新的完整后端，结果为 **6081 passed、1 failed、1 skipped、4 deselected、1 warning，3279.22s（54:39）**，该次运行没有通过。唯一失败是 `tests/integration/test_web_api.py::test_plan_versions_are_paginated_and_details_revalidate_canonical_identity`：精确摘要字段集合未加入新声明的 `obsoleteReason`。

本审查员独立检查修复差异：只在精确预期集合增加 `obsoleteReason`，并对正常摘要和详情均明确断言其为 `None`。没有删除或放宽断言；分页、canonical plan JSON、缺失版本响应及 service-call 身份断言均保留。这属于纯测试契约预期修正。实现者定向运行 `test_web_api.py` 和 `test_openapi_snapshot.py`，结果为 **160 项通过，19.70s**，包含现有 Starlette 警告；两个文件的 Ruff 通过。随后协调员运行 `pytest -q -m "not live" --ignore=tests/integration/test_backtest_acceptance.py`，exit 0，结果为 **6074 passed、1 skipped、4 deselected、1 warning，1204.62s（20:04）**。日志为 `D:/Workspace/Projects/ai-quant-pilot/Temp/daily-simulation-cleanup-final-backend-recheck.log`。

被排除的容量文件收集到 **8 项测试**，没有 skip 标记，8 项均在首次完整运行通过；首轮唯一失败是上述无关的 API 预期。协调员最后核对 851 文件冻结清单，确认只有已审测试修正，没有缺失文件，也没有业务/生成物/assets 变化。因此验证门禁已通过**两轮覆盖证据满足**，复用未变化容量测试的首轮通过结果。C1–C7 保持 CLOSED，无剩余实质问题。不把重叠测试数量相加，也不将首轮失败或组合证据表述为单次全量全绿。

UI 实现者报告最后解析器变更后的门禁：**62 个文件、865 项通过，6.21s**，typecheck 和三个 build 均 exit 0，**2 个 Chrome 流程通过，14.0s**。日志位于 `D:/Workspace/Projects/ai-quant-pilot/Temp/daily-simulation-ui-final-c6-reviewed`。这些协调员/实现者运行是明确归因的证据，不冒充本审查员独立执行。原 6065 项结果仅为历史，不能替代清理后的门禁。

本审查使用受控离线 fixture、临时 SQLite、假 SDK 数据、源码检查及真实本地 API/解析器/composition 边界。未验证实时提供商可用性、实际交易所数据、外部发送或生产数据库。结论是上述范围内无剩余实质问题，不是部署批准。

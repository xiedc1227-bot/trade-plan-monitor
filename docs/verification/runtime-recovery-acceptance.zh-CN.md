# 运行恢复：完整流程验收证据

> 第一阶段已按用户批准的离线进程重启标准于 2026-09-23 验收。第二阶段提醒安全已于 2026-09-24 完成离线接通实现及验证；更广的发布门禁仍未关闭。真实行情源验证、用户数据库迁移及部署均未获批准。下文旧章节保留其当时的阶段状态。

## 业务第 3 步发送排空切片 — 2026-09-24

临时 SQLite 用例先显示：模拟外部发送仍停在 `deliver` 内、回执尚不存在时，`NotificationDispatcher.aclose()` 已返回。另一项生命周期用例显示分发器排空出错后仍释放行情控制器并关闭数据库，两项均为红测。现在分发器关闭阻断新发送，跟踪并保护已开始的渠道 IO 及回执最终写入，在关闭渠道资源前至多等待五秒。若超时，发送继续运行，回执提交后可再次关闭。分发器排空失败会阻止控制器所有权释放、WAL 检查点及数据库关闭。测试还取消发起等待方，证明发送回执仍会提交。通知发送、生命周期、组合及生产认证回归 **122 项通过**，仅有 1 项既有 Starlette/httpx 警告；定向 Ruff 与 diff 检查通过。这尚未证明完整重载/关闭验收矩阵。

## 业务第 3 步相关配置比较 — 2026-09-24

此前有效的 `web.port` 编辑会使 `configuration_is_current()` 返回 false，进而阻断既有 Tushare 管线。失败先行的生产测试复现了该结果。现在检查会完整解析 YAML，只以已校验的 `tushare` 投影比较行情代次身份；仅更改 web 设置后仍使用同一管线，且不增加 SDK 调用。既有令牌变化测试仍会阻断行情工作。无效 YAML 依然无法通过校验。这项有界修正不执行重载，也不改变所有者、数据库、监督器或代次安装。

## 业务第 3 步参考数据提交围栏 — 2026-09-24

此前首次模拟 `trade_cal` 响应在 SDK 调用返回前更改本地令牌后，仍提交了 399 条日历记录；下一次行情调用才失败。新的事务围栏在每个日历、每日涨跌停及历史日线参考数据提交前，复核捕获的激活/计划需求、当前配置、股票语义修订及运行代次。令牌变化用例现在回滚首次结果，保留零条日历记录，也不启动第二次物理请求。该生产专项用例先以 399 条失败、修正后以零条通过；之前三项用例已改为预期更严格的提交前 `ReferenceDependenciesChangedError`，相关生产/实时管线/重启文件通过。本围栏尚未实现已校验重载，也未覆盖全部决策/发送提交。

## 业务第 3 步日历权限切片 — 2026-09-24

目前仅 `TRADING_CALENDAR` 接通受控生产权限复核。锚点取自过去七天已持久化且完成的 `SSE` 日期。专用只读 `trade_cal` 调用只请求该交易所和该日期，严格验证每一行返回，且要求一条非空规范化结果。控制器在准入前持久预约该操作 300 秒，物理调用期间保留权限封锁，并优先应用任何共享 429 冷却。成功后，在清除封锁前再次核对当前配置、股票语义修订和运行代次。无锚点时行情健康可见 `BLOCKED_PERMISSION`，且不发物理探针。探针不持久化日历或决策数据。

- 红测：此前物理调用成功后，即使本地证据在解锁前变化，控制器仍会清除权限封锁；亦无专用严格日历权限路径或无锚点生产健康/重试用例。
- 绿测：单元探针拒绝空表、错误日期、错误交易所、重复、混入和畸形数据。生产集成验证单日请求形态及日历行数不变；空响应、429、配置及代次变化保留封锁与预约。无锚点时运行时持续 `DEGRADED`，报告 `BLOCKED_PERMISSION`，不发后续物理探针。相关离线回归 **215 项通过**，仅有 1 项既有 Starlette/httpx 警告；健康时间戳修正后的定向检查亦通过。
- 未完成：其他操作尚无生产权限探针；`INDEX_MINUTES` 涉及两个物理 API，仍需独立迁移决策。本切片不关闭 A05、完整业务第 3 步、已校验配置重载或 C1/C3。只使用模拟 SDK 结果及临时 SQLite。

## 业务第 3 步行情状态绑定切片 — 2026-09-24

生产环境现先创建安全关闭的请求控制器，再于数据库迁移和五天存活准入后绑定恢复仓储。身份对有效 Tushare 端点和稳定实时配置档案取哈希，排除令牌及语义文件修订。缺失端点时无恢复身份，缺失令牌时不创建实时管线。损坏的检查点使启动停止并释放本地所有权。已恢复的限流与分范围退避证据在行情工作前生效。新绑定所有者在首次物理调用前保守等待 1.25 秒，包括重建控制器后的首次调用。正常重复能力探查保留管线和控制器。配置变更或当前语义记录缺失/损坏会阻断后续物理工作，而非静默重建管线。物理工作者排空失败会阻止 WAL 检查点及数据库关闭，可稍后再次清理。

- 红测：必须绑定而尚未绑定的控制器曾允许工作；损坏的生产检查点及绑定失败尚无经过演练的安全关闭路径；新控制器曾在虚拟时刻 0 发起请求而未等待 1.25 秒；物理排空失败后关闭流程仍会继续尝试数据库关闭。
- 绿测：`tests/integration/test_provider_cooldown_process_restart.py` 让两个独立 Python 进程使用同一临时 SQLite 数据库。进程一观察并提交模拟 429 后正常停止；进程二在两分钟后启动，恢复同一五分钟冷却，物理 SDK 调用为零。有界单元/生命周期/生产/语义/实时管线回归 **200 项通过**，仅有 1 项既有 Starlette/httpx 警告。定向用例还覆盖损坏检查点释放所有者、令牌变化但端点身份稳定、重复能力探查、物理调用间配置及语义失效、排空失败。
- 未完成：这属于已批准的单数据库单所有者前提下的受控串行重启，不包含多个独立进程并发共享同一数据库。进程在 429 提交前被强制终止，无法恢复未记录的观察。受控权限复核、已校验配置重载及原子安装、完整依赖故障矩阵、全部旧代次提交/发送保护及完整 A04–A06/A09/A11/C1/C3 验收仍开放。未使用真实行情源、外部发送器、用户数据库迁移、部署或推送。

## 业务第 3 步首个生命周期切片 — 2026-09-24

失败先行的生命周期测试先证明，运行中的 `RequestControlError(TRANSIENT)` 会结束运行时并关闭控制器。有界修正保留原运行代次和请求控制器，以 `DEGRADED` 及重试下限报告状态，并在本地恢复后继续调度。本次仅将 `TRANSIENT`、`TIMEOUT` 和 `RATE_LIMITED` 归入该重试；`ERROR`、存储故障及类型/契约故障继续上抛。控制器给出的未来重试截止点会显示在健康状态，关闭可中断等待。生产组合测试用模拟 SDK 和临时 SQLite 证明：一次连接故障后出现后续物理实时请求，运行时/控制器未被替换。该测试证明接续本身，不单独证明已完成交易决策或跨进程持久重试。

另一项先失败的生产测试证明，`realtime:{bar_end}` 使下一分钟在注入的五分钟传输退避内再次发起物理请求。稳定的 `realtime:stock` 故障范围使该分钟受阻且不发起物理请求。此前 RR004 测试曾被缺失的心跳夹具挡住；现在设置有效心跳。测试验证首次物理调用后删除或损坏*当前语义记录*会阻止第二次调用。冷参考缓存可以合法地重新补取参考数据，因此重复截止任务测试现核对真正的不变量：已提交目标不会再次实时取数、增加评估结果或提醒。

- 红测：`test_transient_deadline_failure_keeps_owner_and_resumes_after_recovery` 超时，原 `RequestControlError` 结束运行循环；`test_next_minute_cannot_bypass_realtime_transport_backoff` 观察到两次而非一次物理 `rt_min` 调用。新增启动/复核存储及类型故障测试揭示静默重试，启动限流测试揭示 09:35 冷却被 09:30:30 的本地计时覆盖。
- 绿测：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_lifecycle.py tests/integration/test_production_certification_gate.py tests/integration/test_monitor_production_composition.py -q --tb=short` — 66 项通过，1 项既有 Starlette/httpx 弃用警告。改动的四个源/测试文件定向 Ruff 通过。检查仅使用模拟行情结果和临时 SQLite。
- 业务第 3 步仍开放：生产 `ProviderRecoveryRepository` 绑定；权限复核及受控重启后的冷却；股票/指数与两类计划独立故障矩阵；配置变更暂停准入与原子安装；重载时旧代次提交/发送保护；物理工作者排空失败行为；完整 A04–A06/A09/A11 和 C1/C3 验收。不兼容语义目前在启动时安全失败，尚未形成最终的逐范围受阻生命周期状态。未使用真实行情源、外部发送器、用户数据库、迁移或部署。

## RR004/RR006/A06 独立指数准入 — 2026-09-24

此前开放的四项 `test_production_semantic_gate.py` 用例失败，是因为 `run_deadline` 在检查是否有计划需要股票数据前，先刷新了股票交易日历参考数据。现在无活动计划的截止任务直接进入独立的展示指数路径；股票认证无效的活动计划则在请求股票行情源前受阻，独立指数工作仍可单独调用。原有逐物理调用的指数语义校验现能在已到达的指数路径上执行。这四项测试先在前一个提交上确认失败；本次修正后整份语义门禁文件 11 项通过。相邻生产、指数和激活保护集成测试文件 91 项通过，只有 1 项既有 Starlette/httpx 弃用警告。

这是有界的依赖准入修正，不代表已证明完整的逐计划依赖恢复、配置重载、股票失败后的调度器接续、业务第 3 步、A06 的两类计划完整故障矩阵、C0–C5 或发布就绪。测试使用模拟行情和临时状态；未使用真实行情源、外部发送器、用户数据库或部署。

## RR010 激活保护与指数捕获修正 — 2026-09-24

此前的 `test_deadline_does_not_admit_captured_plan_reactivated_during_reference_await` 在修改前单独复现失败：截止任务等待参考数据刷新后，用重新读取的计划/激活依赖键覆盖入口时捕获的键，因此同一计划重激活未抛出 `ReferenceDependenciesChangedError`。`run_deadline` 现保留入口键，并在参考数据刷新及历史恢复后、准入计划前核对。原回归和新增的历史等待期间重激活回归均通过；旧身份计划不会被准入。

此前记录的两项 `test_live_pipeline_acceptance.py` 指数失败也各自复现。`test_market_index_persistence_reuses_an_older_canonical_content_revision` 在后续出现相同修订时，快照头时间仍停在第一次捕获的 10:36，未前进到 10:38。`test_startup_batches_persisted_pending_closes_by_date_and_shared_index[index_error]` 在新的指数请求失败后复用旧 `LIVE` 快照头，致使依赖该指数的历史决策错误显示 `LIVE`。二者均源于同一持久化短路：旧头为 `LIVE` 或问题码相同，就丢弃较新的 `BLOCKED` 捕获。移除短路后保留规范快照复用及修订冲突校验，同时记录当前捕获；两项定向测试现均通过。本修正针对指数捕获持久化，不代表完整依赖恢复生命周期已完成。

- RR010 指定回归：`tests/integration/test_explicit_runtime_production.py tests/integration/test_recovery_activation_fences.py` — 31 项通过、1 项既有 Starlette/httpx 弃用警告。相邻遗漏收盘/生产组合/历史读取回归 — 48 项通过，同一警告。离线指数测试组（`test_live_pipeline_acceptance.py`、`test_market_index_runtime.py`、`test_persistent_market_index_history.py`、`test_market_index_data.py`）— 53 项通过；（`test_market_index_snapshots.py`、`test_market_index_web.py`、`test_tushare_market_index.py`）— 39 项通过。原激活用例在保护修正前失败，两项指数用例在持久化修正前失败。
- 在该 RR010 检查点，另有四项不同的 `test_production_semantic_gate.py` 用例仍失败：`test_missing_stock_binding_does_not_block_index_only_display`、`test_wrong_surface_bindings_cannot_issue_requests`、`test_index_contract_is_rechecked_between_physical_calls` 和 `test_index_display_remains_independently_callable_after_selected_stock_is_blocked`。它们在新增 RR010 校验前失败：无计划/仅指数截止任务请求了股票交易日历，或返回该请求错误而非预期的股票认证阻断。上文后续 RR004/RR006/A06 修正解决了这四项具体失败；业务第 3 步、C0–C5 及完整发布门禁仍开放。未使用真实行情源、外部发送器、用户数据库迁移或部署。

## 第二阶段离线接通证据 — 2026-09-24

生产的两类评估器现与规范提醒一起提交初始 `HOLD` 回执。生产发送器在逐渠道认领前，以及认领后紧邻渠道 I/O 前，均调用 `CurrentDeliveryAdmission` 读取最新状态。测试仅使用本地 `IN_APP` 和模拟渠道。使用临时 SQLite 的三进程重启验收现还确认：恢复后此前暂缓的风险提醒产生一次持久的本地投递尝试，重复重启不增加规范结果/提醒。SQLite 事务不跨渠道 I/O，既有不确定发送重试行为保持。

接通测试覆盖 D1 突破后 D2 退出或解除、D2/D3 相同退出只释放最新项、人工卖出使当前持仓不再适用、只指定数量的期初余额退出、已证明的旧风险提醒在停用后抑制、显式风险和操作提醒、90 秒失效、当前权威证据缺失、认领后变化，以及较早 `HOLD` 行存在时的待发扫描。重复复核相同的显式或旧版分类不会增加审计数和修订号。每次检查从同一个已提交本地快照读取历史归属、当前官方收盘完成度、激活身份、持仓及运行代次证据。缺失或无效前提绝不构成发送许可。

- 接通回归：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_notification_delivery.py tests/integration/test_delivery_admission.py tests/integration/test_delivery_eligibility_storage.py tests/integration/test_recovery_alert_eligibility.py tests/integration/test_missed_close_execution.py tests/integration/test_runtime_restart_gap_acceptance.py tests/integration/test_monitor_production_composition.py tests/integration/test_explicit_runtime_production.py tests/unit/test_legacy_recovery_delivery_eligibility.py -q --tb=short` — 264 项通过、1 项既有 Starlette/httpx 弃用警告，91.24 秒。
- 在这个第二阶段检查点，C0–C5、完整 `not live` 测试、高交易量证明预算、更广停机矩阵及独立发布评审仍待完成。当时两项市场指数测试和 `test_deadline_does_not_admit_captured_plan_reactivated_during_reference_await` 仍失败；上文较后的 RR010 修正解决了这几项特定失败，不改变本阶段限定的投递结论。未使用真实行情源、外部发送器、用户数据库、迁移或部署。

## 第一阶段进程重启验收 — 2026-09-23

`test_stopped_monitor_recovers_missed_close_once_after_process_restart` 使用三个独立启动的 Python 进程、同一份临时 SQLite 数据库和生产 `create_monitor_composition` 生命周期；只以确定性的离线数据替换外部 Tushare SDK。活动旧版计划在收盘前启动，第一个进程于 14:00 突然退出；此时没有当日正式日线或收盘结果。新进程于 16:00 启动，取得并存储当日 55.00 的正式收盘，恰好提交一条收盘结果与一条风险提醒，原计划仍活动，运行状态为 `RUNNING`、没有逐标的恢复问题，且已安排下一次唤醒。在第一阶段检查点，该提醒保持持久 `HOLD` 且没有渠道投递尝试；上文第二阶段运行将同一场景扩展至本地投递。第三个进程于 16:01 启动，没有增加重复占用、结果或提醒。中断小于批准的 120 小时作废边界。本场景没有更早已提交的收盘；已有的单独检查点测试覆盖不重新评估旧决策的接续。

- 专项验收 1 项通过。5 个直接相关的恢复/生命周期模块共 97 项通过，有 1 项既有 Starlette/httpx 弃用警告；Ruff 与 `git diff --check` 通过。更广的 6 模块测试为 114 通过、2 项可单独复现的市场指数测试失败，不宣称全绿。之前记录的计划重激活准入失败也仍在第一阶段限定口径之外待处理。
- 本结论只验收已约定的测试范围——服务中断后重启并恢复原任务——不表示任何历史数据库都能无限制恢复。有限的持仓证明预算及未解决的旧库/跨激活证据问题遇到时仍会安全阻止。未使用真实行情源、外部发送器、用户数据库、浏览器服务器进程或部署。第二阶段仍须在释放暂缓提醒前复核最新风险与持仓。

## 重启接续清理与健康状态可见性 — 2026-09-23

已接通的生产路径现在可连续分页读取未完成的正式收盘尾段，不再止于一次 32 天读取窗口。32 天只保留为单次发现调用的上限，不是计划作废、检查点选择条件，也不会单独阻止恢复。无论计划运行多久，准备阶段都从最近一次已证明提交的收盘之后接续；已提交决策不会重新计算。仅在核对当前风险来源时读取所需的更早检查点。持久存活时间的 120 小时准入及人工确认的库存仍为权威依据。过期的行情源观测不再声称 `READY`；仍兼容的持久股票语义契约可允许受保护的行情工作。降级启动按封顶的 30/60/120/300 秒间隔自行重试，无须重启进程。运行健康提供 `degradedReason`、`nextRetryAt` 和逐标的 `recoveryIssues`；页面横幅区分“连接正常但监控暂停”和“浏览器连接断开”。可操作的买入/卖出提醒引导到独立的人工成交登记区；风险提醒和已读确认都不会登记成交。

- 受影响后端回归：647 通过，1 项既有 Starlette/httpx 弃用警告；随后运行任务失败原因调整也通过对应的 20 项组合测试。前端：676 项单元测试通过，类型检查和正式构建通过。Ruff、OpenAPI/TypeScript 生成文件检查及 `git diff --check` 通过。
- 检查点年龄修正：新增回归在修复前的第 4 天和第 31 天失败，修复后第 4、31、32、33 天均通过。较早日期的日历缺失不再阻止从已证明的风险检查点接续；孤立风险审计仍安全拒绝。恢复关联回归 204 通过、1 项既有 Starlette/httpx 警告；全仓 Ruff 和 `git diff --check` 通过。曾尝试完整非 live 测试，但不相关的回测容量用例耗时较长而未完成；本次修正不声称取得全量测试结果。
- 日历窗口评审：35 天接续尾段的上交所日历查询从批量化前 34 次降至 2 次；独立的 32 天发现窗口从 32 次降至 1 次。两项查询次数回归均在修改前失败、修改后通过。缺失或异常的日历证据仍保持未知。8 个关联离线测试模块共 247 通过、1 项既有 Starlette/httpx 警告；全仓 Ruff 与 `git diff --check` 通过。数字 32 仍是单次调用的有界实现选择，未证明为性能最优值，也不是业务作废规则。
- 风险检查点评审：三次变更历史（`BREACHED` → 错误的 `EXIT_PENDING_SETTLEMENT` → `CLEAR`）此前因只核对最新变更而错误通过；新增回归在修复前失败，现返回 `UNKNOWN`。准备阶段读取并核对已存风险变更检查点及紧邻的已完成前驱，不重新评估普通 `WAIT` 收盘。另一项回归确认再增加 11 条尾部 `WAIT` 收盘也不会增加评估占用/结果检查点查询次数。4 个直接相关模块共 177 项通过，有 1 项既有 Starlette/httpx 警告；全仓 Ruff 和 `git diff --check` 通过。更广的 8 模块运行得到 296 通过、1 项独立可复现的 `test_deadline_does_not_admit_captured_plan_reactivated_during_reference_await` 失败；本次修改未改动截止时刻准入逻辑，不宣称广义回归全绿。
- 浏览器检查：11 项提醒/系统/股票页面用例通过，包括详情异步加载后定位至人工成交登记区；安装版网页完成一次真实进程停止与重启，前后均没有控制台错误或浏览器请求失败。另有 4 项真实进程交易计划用例通过：活动计划接续、替换、停用及超过 120 小时作废。
- 首次活动计划浏览器测试在重启前停住，原因是前端提取响应校验器只接受 `plan-extract-v4`，而后端返回已支持的 `plan-extract-v5`。追踪记录证明提取已经成功；按后端 v4/v5/v6 映射契约放行并补充三版本测试后，前置阻断已解除。这里不声称全量测试或真实行情源验收通过。
- 剩余限制：历史库存证明仍有明确的 256 项变更/成员和字节预算；独立成交登记流程尚未提供直接关联提醒的实际成交确认 API。提醒及其已读确认均不改变持仓。

## 最近节点接续与期初持仓 — 2026-09-23

基线版本 `c16be1ee10c78825d093b9038dee71574bcd9337`；检查覆盖尚未提交的修改。对于长期活动的旧版计划，历史读取器验证最近已提交的正式收盘节点，只检查其后有界的遗漏日期；短历史恢复保留原有的完整前缀风险/审计校验。生产组合现于准入当期工作前执行按日期补算的旧版收盘恢复，并将逐证券重试状态绑定到准确激活身份；补算提醒初始进入持久 `HOLD`。已确认期初余额计入历史及实时持仓/可卖量，不虚构批次、成本或购入日期；只有期初持仓的旧版风险退出可生成仅指定数量的卖出提醒。普通提醒不虚构批次预填，也不登记成交。新版可执行计划的 `SELL` 规则仍依据已确认的总可卖量，而非批次优先级。

- 首次集中回归暴露 9 项短历史审计回归（393 通过 / 9 失败）。已将检查点捷径限定于长期活动计划，并补充其变更/前驱审计校验；未移除失败断言。
- `.\.venv\Scripts\python.exe -m pytest tests/integration/test_historical_close_evidence.py tests/integration/test_missed_close_execution.py -q` — 修复后 64 通过。后来补充检查点审计损坏用例，历史读取器文件达到 44 通过。
- 最终专项命令覆盖 `test_decision_engine.py`、`test_production_historical_recovery.py`、`test_historical_close_evidence.py`、`test_missed_close_execution.py`、`test_notification_delivery.py`、`test_certified_production_runtime.py`、`test_monitor_production_composition.py`、`test_explicit_decision_persistence.py` 和 `test_decision_replay.py`：430 通过、1 项既有 Starlette/httpx 弃用警告，59.15 秒。全部修改源码/测试文件的 Ruff 与 `git diff --check` 通过；Windows 行尾提示仅供参考。

业务第 1 步仍未关闭：尚未以安装式生命周期执行完整的有缺口进程重启；历史持仓/风险证明仍有有限事件预算；完整停机/故障矩阵及独立评审仍待完成。历史 `HOLD` 防止提前发送，但依据最新状态释放资格及逐渠道发送前复核属于业务第 2 步。未使用真实行情源、发送器、用户数据库迁移或部署。

## 五天准入基础 — 2026-09-23

在 `codex/consolidate-r19-r32` 上，仅本地测试的迁移 `0022_runtime_liveness` 与持久单行心跳/判定器确定了获批的准确 120 小时边界。缺失/损坏/非规范证据、时钟回拨，以及旧库中有活动计划却没有心跳时，都不能静默准入。另一个可选工作单元事务目前可作废运行程序所支持的最多 10 个活动计划及其待收盘任务和已有投递资格记录；持仓、旧结果及提醒保留。单条超时审计保留最后存活及判定时间。重复作废不增加计划/收盘审计；第二个计划处理中注入失败会回滚第一个计划、待收盘删除、事件与审计。没有资格记录的升级前提醒，在停用后仍受生产发送器的活动计划关联门禁阻止；为此类旧行持久记录逐提醒的终态回执尚待后续实现。

- RED：`test_runtime_liveness.py` 在新模块不存在时首先收集失败；可解析但非规范的时间戳测试在严格解码前失败。`test_runtime_plan_expiry.py` 在工作单元方法不存在时先失败；总审计与资格抑制用例也先失败再实现。
- GREEN/受影响回归：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_plan_expiry.py tests/integration/test_runtime_liveness.py tests/integration/test_sqlite_repositories.py tests/integration/test_runtime_lifecycle.py tests/integration/test_recovery_alert_eligibility.py tests/integration/test_notification_delivery.py -q` — 229 通过，1 项既有 Starlette/httpx 警告，25.55 秒。
- 补充暂缓资格回滚断言后，执行 `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_plan_expiry.py -q` — 5 通过；上方较大范围的成功运行只早于这项测试断言。
- 对本轮修改的运行/状态/测试文件执行 `.\.venv\Scripts\python.exe -m ruff check` — 通过。未使用真实行情源、发送器、用户数据库或部署。

本节基础测试早于下文的生产生命周期接入。短时中断仍需经验证的近期来源和历史状态重建。V1d、C2 和业务第 1 步仍未关闭；完整非 live 测试及已知四项基线失败仍是最终门禁。

### 生产准入与心跳切片 — 2026-09-23

生产生命周期现已在打开数据库后、加载活动计划、探测行情源、恢复或发送前调用持久准入门禁。门禁对已证明超过 120 小时的空白期原子作废计划，再通过修订号保护推进心跳。30 秒心跳在只读/降级待机时仍运行，并在关闭数据库前结束。休眠进程不能跨越超过 120 小时的空白期补写心跳：它会停止并留下旧证据供下次准入处理。在该检查点，缺失/无效旧证据阻止自动启动，人工复核界面尚无；后续缺心跳路径记录于 `2026-09-23-legacy-maintenance.zh-CN.md`。当前发送器用活动计划身份阻止旧版过时提醒，但逐条持久终态回执尚未实现。

- RED/GREEN：生命周期顺序及准入失败测试先因缺少所有者接口而失败；休眠心跳测试在补充空白期检查前先失败。新增生产状态集成验证：超过 120 小时的两个活动计划在可被加载前作废，同时保留 1,000 单位持仓及五条审计记录。
- `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_plan_expiry.py tests/integration/test_runtime_liveness.py tests/integration/test_sqlite_repositories.py tests/integration/test_runtime_lifecycle.py tests/integration/test_recovery_alert_eligibility.py tests/integration/test_notification_delivery.py tests/integration/test_live_pipeline_acceptance.py::test_real_composition_starts_runs_a_timer_and_restores_its_projection tests/integration/test_monitor_production_composition.py tests/integration/test_certified_production_runtime.py -q --tb=short` — 261 通过，1 项既有 Starlette/httpx 警告，47.15 秒，已包含降级待机心跳断言。
- 较大范围的 `test_live_pipeline_acceptance.py` 运行有 42 项通过、三项失败：新增的旧夹具需要显式提供先前心跳证据，修正后单独运行通过；另外两个行情指数预期失败尚未修改。本切片未迁移用户数据库，亦未使用真实行情源或发送器。
- 另一个基于 `spawn` 的测试先启动 Python 进程提交作废，并以代码 17 退出，再由第二个进程从同一临时 SQLite 文件重启。活动计划未恢复，审计仍为五条，1,000 单位持仓保留。这证明提交后进程退出/重启，不代表已验证作废事务进行中退出。
- 生产准入恰好 120 小时的用例最初失败，因为作废分类和心跳更新分别读取时钟。准入现冻结同一个观察时间供两步使用；临界测试通过，两个计划均未被作废。
- 上述补充完成后重新执行前列受影响回归命令：263 通过，1 项既有警告，52.11 秒。
- 真实子进程在第一个计划于事务内停用后暂停并被强制结束。重新打开临时 SQLite 文件可见两个计划与待收盘任务均完整、没有作废审计、暂缓提醒资格未变、最后存活时间仍为旧值。新进程随后恰好作废两个计划一次、抑制暂缓资格，并保留 1,000 单位持仓。初版测试夹具在 Windows 上终止等待者后又操作同一进程间事件而卡住；改为子进程有界睡眠后排除了夹具故障。此项无需修改运行源码。
- `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_plan_expiry.py tests/integration/test_runtime_liveness.py tests/integration/test_runtime_lifecycle.py -q --tb=short` — 45 通过，8.53 秒。修改的测试文件 Ruff 检查通过。

- 独立的临时数据库用例同时保存一个通过校验的 Schema v1 `TradePlan` 和一个通过校验的 Schema v3 `ExplicitTradePlan`，随后作废两者。两个版本都变为 `SUPERSEDED`，规范计划 JSON 与 1,000 单位持仓保持不变。这验证共享作废边界覆盖两类文档；真实行情源端到端运行不属于本切片。
- 增加该用例后重新执行上方同一专项命令：46 通过，8.72 秒；Ruff 通过。

## 实际进程重启切片 — 2026-09-23

可选的旧版离线路径在多个独立启动的 Python 进程中，共用一份临时 SQLite 文件。D1、D2 各自在新进程提交；后续两个新进程只得到重复结果。评估器边界强制退出后，没有留下结果、风险变更或提醒意图；新进程将 D1 提交一次，另一个新进程只得到重复结果。HOLD 投递资格记录仍在。这验证了解释器/进程重启，不只是释放引擎或重开 SQLite。首次运行中固定不变的观察时钟及测试专用 SQL 列名错误导致测试夹具失败；两者均已修正，未改运行源码。

- `.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py tests/integration/test_historical_close_evidence.py tests/integration/test_recovery_activation_fences.py -q --tb=short` — 68 通过、1 项既有 Starlette/httpx 警告，28.17 秒（在增加突然退出后的最终重复断言之前）。
- `.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py -q` — 增加最终断言及子进程超时清理后 19 通过，14.13 秒。
- `.\.venv\Scripts\python.exe -m ruff check tests/integration/test_missed_close_execution.py` 与 `git diff --check` — 增加最终断言后通过（只有普通 Windows 行尾提示）。

未涉及生产协调器、真实行情源、发送器或用户数据库。仅测试层的进程覆盖不关闭 V1c/RR009/C2：无限制历史、支持期初持仓的评估、多计划时间顺序准入和生产集成仍未完成；提交后进程终止及完整生命周期重启验收也仍待完成。

## 有界流程接通 — 2026-09-23

基线版本：`ac9da66705829d5da769af616363533f2f6caf7a`，分支为 `codex/consolidate-r19-r32`；检查覆盖尚未提交的接通修改。可选的 `LegacyHistoricalCloseReader` 和 `HistoricalOfficialContextBuilder` 从一次有界自有快照向既有收盘评估器提供输入。历史风险使用可归因的来源收盘时间；提交结果保存准确的已证明历史批次。D2 登记的人工卖出减少 D2 数量，但即使其生效交易日为 D1，也不减少 D1 数量。补算产生的两条风险提醒均从 `HOLD` 开始。

真实临时 SQLite 场景用 200 股提交 D1，重开后用 100 股提交 D2，再次重开仅得到重复结果。结果保存前和提醒插入后模拟退出，会一起回滚占用、结果、风险及投递资格。提交后发布失败保留唯一持久结果。并发持仓/风险变化、全局发布、旧激活，以及保护核对后占用前插入的写入，均拒绝过期输入。乱序 D2 不留下待收盘标记。持仓/日历资料不足及先前受阻结果不能被占用。旧版批次模型无法表达的期初持仓保持不可用，不会从评估数量中消失。

- 修复审计前驱问题前：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py tests/integration/test_historical_close_evidence.py tests/integration/test_recovery_activation_fences.py tests/integration/test_close_recovery_evidence.py tests/integration/test_close_recovery_session_ownership.py tests/unit/test_missed_close_recovery.py tests/integration/test_position_inventory_history.py tests/integration/test_inventory_history_boundaries.py tests/integration/test_recovery_alert_eligibility.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_sqlite_repositories.py tests/integration/test_certified_production_runtime.py -q --tb=short` — 469 通过、1 项既有 Starlette/httpx 警告，80.93 秒。
- 新的只读 `gpt-6-astra` / `xhigh` 评审确认了期初持仓和缺失日历问题，随后复现物理版本大于 1 时本激活首条风险变更缺少前驱审计连接。每一项均先有专项失败测试，再补保护/连接。先前 `BLOCKED_DATA` 记录也由失败测试证实后改为未知。
- 评审修复后：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py tests/integration/test_historical_close_evidence.py tests/integration/test_recovery_activation_fences.py -q --tb=short` — 64 通过、1 项既有 Starlette/httpx 警告，17.03 秒。既有 OpenAPI/前端类型快照检查通过。未使用真实行情源、发送器、生产配置、用户数据库迁移或部署。
- 单计划共享指数顺序修复：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py -q --tb=short` — 17 通过，4.86 秒；无效的较晚目标不会准备指数，已有占用的目标保留原有重复入口行为。
- 修复后受影响回归：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_recovery_activation_fences.py -q --tb=short` — 75 通过、1 项既有 Starlette/httpx 警告，14.75 秒。源码修改后 Ruff 与 `git diff --check` 均通过。一次有界只读复查未发现该单计划预检存在必改问题。

V1a、V1b 基础已完成。V1c、RR009 和业务第 1 步仍未完成：当前使用方仅覆盖激活起最多 32 个自然日，且无法评估历史期初持仓。仍需生产协调器接入、更完整的进程重启/故障覆盖，以及解决先前记录的 4 项全量测试失败。单计划共享指数路径现已预检尚未占用的目标；多计划批处理在生产集成前仍需逐计划时间顺序准入规则。本报告不表示任意时段重启或投递安全已经完成。

## 此前范围 — 2026-09-22

基线版本：`1f50439`，分支为 `codex/consolidate-r19-r32`；下述命令测试了包含 `state/inventory_evidence.py`、`state/position_inventory_history.py`、四个新测试文件、模型索引及仅新增索引的迁移 `0021_inventory_history_index` 的工作区修改。更新了既有最新迁移版本断言，未改变历史迁移目标。此前仅调整流程的计划/任务表修改仍在范围内，作为独立文档修改。未改变依赖、规范哈希、通知行为或生产默认值；未迁移用户数据库。

确认和自动持仓变更记录现在共用有界一致性解码器。真实写入到解码用例覆盖确认缺失/过期/同步、原始 UTC 表示、复用确认 ID、零股余额/可变交易单位及回滚/重开。故意允许解码尚未提交的记录；解码不是已提交历史证明或回放许可。

完整读取器已在一次自有 SQLite 快照中，证明包含登记时间等于截止点的已登记持仓。它消费连续版本回执、来源变更及发布，核对确认当时的成员，并将重建末态与包含已关闭持仓的全部当前记录比较。批次和期初持仓保持独立。已落实用户批准规则：没有人工确认就不减仓；较晚登记的回溯卖出不改变此前仓位。没有确认的已证明登记账本，不代表完整券商账户。超过 256 项变更/成员或 8388608 字节已读取文本的历史仍返回 `HISTORY_LIMIT`；无限制生产恢复仍需后续检查点/来源证明路径。

## 已执行检查

- RED：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_inventory_evidence.py -q` — 新模块尚不存在，1 项收集错误。独立编写的集成测试在实现前也因相同的模块缺失而失败。
- GREEN：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_inventory_evidence.py -q --tb=short` — 49 通过。首次组合运行暴露了多余的派生数据类字段，以及测试时钟对仅接受上海时区的监控发布使用 UTC；实现已改用派生元组属性，测试仅对确认写入使用 UTC，保留覆盖而不改变生产写入方。
- 受影响回归：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_inventory_evidence.py tests/integration/test_inventory_evidence_roundtrip.py tests/integration/test_position_inventory_recovery_audit.py tests/integration/test_position_inventory_recovery_transactions.py tests/integration/test_position_inventory.py tests/integration/test_position_lot_history.py tests/unit/test_opening_balance_evidence.py tests/integration/test_opening_balance_evidence_roundtrip.py -q --tb=short` — 最初 300 通过；评审修复后 305 通过，1 项既有 Starlette/httpx 弃用警告，21.73 秒。最终包含 53 项新单元用例及 19 项新真实写入集成用例。
- 读取器 RED：在 `state/position_inventory_history.py` 存在前，独立编写的测试收集失败；在 `ix_position_lot_symbol` 存在前，索引测试失败。初次实现：27 通过 / 4 失败，暴露了严格原始整数校验前的 SQLAlchemy 布尔转换。将选出的确认标志转换为整数，同时保留 SQLite 存储类型校验后修复根因；首轮完整读取测试：31 通过。
- 完整读取相关回归：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_position_inventory_history.py tests/integration/test_inventory_history_boundaries.py tests/integration/test_lot_history_indexes.py tests/integration/test_sqlite_repositories.py tests/unit/test_inventory_evidence.py tests/integration/test_inventory_evidence_roundtrip.py tests/integration/test_position_inventory_recovery_audit.py tests/integration/test_position_inventory_recovery_transactions.py tests/integration/test_position_inventory.py tests/integration/test_position_lot_history.py tests/unit/test_opening_balance_evidence.py tests/integration/test_opening_balance_evidence_roundtrip.py -q --tb=short` — 465 通过，1 项既有 Starlette/httpx 警告，48.00 秒。包含 50 项新读取/边界用例：迟到登记、零账户持仓确认、同时间变更、关闭、回滚/重开、重复读取、并发写入、借用/分离会话、缺失/孤立证据、发布顺序改变、错误原始类型、256 项接受 / 257 项拒绝、累计字节耗尽，以及保留批次的索引降级/再升级。
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts` — 通过。
- `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` — 快照/类型为当前版本。
- `git diff --check` — 通过；仅有普通 Windows 行尾提示。

不声称本次重新运行全量/浏览器测试。`2026-09-22-opening-balance-decoding.md` 中记录的 4 项既有失败仍未解决，也未豁免。最终完整门禁仍须执行。

## 评审及剩余工作

独立的 `gpt-6-astra` / `xhigh` 契约评审指出迟到登记业务选择、历史批次保存不一致和恢复写入时间导致的风险不一致。发现已记录到成对运行恢复规格，处理状态见下文。独立测试工作使用 `gpt-6-astra` / `high`。另一项只读 `gpt-6-astra` / `xhigh` 实现审查发现两项须修复问题：JSON 转义后的孤立代理字符 ID 绕过原始字节检查，以及额外的 NUL 限制拒绝写入方允许的 ID。4 项单元 RED 用例和 1 项真实写入 RED 用例复现问题。解析 ID 后严格验证 UTF-8、移除额外 NUL 限制后，两项均已修复；有界复查未发现剩余必改问题。按用户要求继续跳过额外跨模型审查；本报告不证明父任务的模型/强度。

用户已明确迟到登记选择：数量仅在人工登记时改变，不因提醒或较早生效交易日期而改变。新的只读 `gpt-6-astra` / `xhigh` 审查未发现完整读取器存在须处理的正确性/安全问题；其建议补充的覆盖（实际 256/257 边界、未来关闭时间、错误原始类型及零持仓确认）已在上述最终回归前补齐。迟到登记不再有待定决策。

有界持仓读取及其时间/来源/发布/成员证明已实现。风险重建及真实评估事务集成仍未完成。不关闭 V1a–V1c、RR009 或 C2。下一验收结果仍是一次遗漏收盘恢复后重开不增加结果/意图，再扩展跨日/故障覆盖。历史评估须保存同一份已证明的批次输入，并将风险绑定来源有效时间；仅有读取器尚不能启用这条路径。

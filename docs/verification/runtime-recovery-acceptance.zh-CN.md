# 运行恢复：完整流程验收证据

> 第一阶段已按用户批准的离线进程重启标准于 2026-09-23 验收。第二阶段提醒安全、真实行情源验证、生产迁移及部署均未获批准。下文旧章节保留其当时的阶段状态；本结论取代其中“第一阶段未完成”的历史表述。

## 第一阶段进程重启验收 — 2026-09-23

`test_stopped_monitor_recovers_missed_close_once_after_process_restart` 使用三个独立启动的 Python 进程、同一份临时 SQLite 数据库和生产 `create_monitor_composition` 生命周期；只以确定性的离线数据替换外部 Tushare SDK。活动旧版计划在收盘前启动，第一个进程于 14:00 突然退出；此时没有当日正式日线或收盘结果。新进程于 16:00 启动，取得并存储当日 55.00 的正式收盘，恰好提交一条收盘结果与一条保持持久 `HOLD` 且没有渠道投递尝试的风险提醒，原计划仍活动，运行状态为 `RUNNING`、没有逐标的恢复问题，且已安排下一次唤醒。第三个进程于 16:01 启动，没有增加重复占用、结果或提醒。中断小于批准的 120 小时作废边界。本场景没有更早已提交的收盘；已有的单独检查点测试覆盖不重新评估旧决策的接续。

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

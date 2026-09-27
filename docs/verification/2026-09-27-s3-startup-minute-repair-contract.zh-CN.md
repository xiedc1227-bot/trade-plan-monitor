# S3 启动分钟修复契约

状态：**F1/F2/F3 design approved / implementation acceptance pending; F1 released for implementation; A07 OPEN**（F1/F2/F3 设计获批／实现待验收；F1 已放行实施；A07 未关闭）。

独立 Sol 评审已批准三个薄片的全部设计，包括 F1 正常带类型失效记账及 F2-04/05 最终 scoped 业务获取接口；已无设计阻塞。F1 已放行独立实施；F2/F3 待串行源码写入者交接、实现及验收，F3 依赖 F2。全部实现证明义务仍未关闭；仅 F1 GREEN 不能关闭 A07 或 S3-04。本次仅文档工作只更新并本地提交本契约及英文对应文档，不修改源码、测试或证据报告，不授权推送。较早代码观测基于 HEAD `4804207`；SDK 交接观测已在当前工作树复核。行号仅定位观测，不是稳定接口。

证据：作者运行 13 项，**3 failed、10 passed，15.08s**；独立运行 **3 failed、10 passed，14.90s**。两次运行独立记账，不相加。Ruff 通过，oracle P2 已关闭，证据报告一致。真实失败仍为两项空/部分启动 RUNTIME_RUNNER_FAILED，以及一项捕获截止点为 10:00 却写入 10:01 的冻结截止点失败。当前 progress 经 supervisor 换代后，于 10:05:12 合法生成 10:05 决策；这不能证明正常 scoped recovery 已接通。S3-04 保持 OPEN。

证据：[英文报告](2026-09-27-s3-startup-minute-coverage.md) · [中文报告](2026-09-27-s3-startup-minute-coverage.zh-CN.md)。

## A07-F1 — F1 — 保留 INCOMPLETE 并关联准确的原计划身份

### A07-F1-01 — 归属与接口

已放行的 F1 实现修改 `runtime/service.py` 和 `runtime/explicit_service.py`，定向覆盖 `tests/integration/test_ten_symbol_runtime.py`、`tests/integration/test_market_index_runtime.py`、`tests/integration/test_explicit_runtime_production.py` 及既有 A07 测试文件，不属于本次仅文档工作。增加内部不可变的 `PlanCycleOutcome`，携带原身份，以及真实 cycle result 或标明带类型提交前 guard 失败的封闭 `STALE` 状态，两者必须且只能出现其一。身份包含 consumer kind、symbol、plan_id/version/hash、activation_revision 和 target_bucket_end。在供应商/指数 await 前捕获有序候选身份；得知桶可用性后选择 due 子集，不重新捕获激活代次。过滤 outcome 前，将每个原 due 身份绑定到自身 coroutine。禁止对已过滤结果序列再配对，或从可选 facts 推断身份。

### A07-F1-02 — 兼容与失效结果

为生产协调器增加严格关联结果入口。保留 `run_intraday_batch` 和 `run_intraday_batch_from_minutes` 既有公开结果元组及失效过滤合约；共享求值实现，不共享已过滤结果。严格求值中的 `StaleActivationGenerationError` 或 `StaleExplicitDecisionError` 仅传播至该原计划的包装边界，在那里记录 `STALE` outcome。这些异常必须来自求值器提交前 guard。`StaleExplicitDecisionError` 覆盖 activation、inventory 和 manual-event-risk 变化，三者都是捕获工作正常失效的情形。转换边界只包围提交前求值，不能包围整个 `run_intraday_and_publish` 调用：发布阶段即使抛出同类型异常，也必须向上传播，不能变成 `STALE`。存储、发布、程序/协议异常以及取消仍为错误；不增加宽泛 `RuntimeError` 捕获。

协调器完整核对每个原 due 身份，包括 `STALE`，然后按原 due 顺序只返回真实 cycle result。全失效批次只有完成内部完整记账后，公开结果才能为空元组。真正遗漏的 outcome 仍为遗漏并拒绝，不能改标为 stale。失效兄弟不能取消其他合法计划 coroutine 或重写其身份。结果按计划关联，不是批次原子提交：健康兄弟可能已独立提交，后续关联错误不承诺将其回滚。

### A07-F1-03 — 两类消费者的精确校验

提取公开结果元组前，校验完整有序的预期身份集合、遗漏、重复和多余 outcome；不能以 symbol 字典覆盖重复项。存在 facts 或 evaluation_result 时，交叉核验实际 symbol、plan hash、目标及其中确有表达的计划/公式身份。legacy 缺失的字段仍由捕获和事务 guard 支持。`ExplicitEvaluationResult` 确实含有 `activation_revision`，必须与原身份及严格捕获的 revision 均一致，DUPLICATE 结果也不例外。相关 explicit 结果身份还须在持久化前验证；业务提交后才检查 envelope，不能约束错误激活代次。

当前 `RuntimeDeadlineCoordinator.run_deadline` 在 `service.py:2547` 附近捕获 revision 后等待获取，但 `explicit_service.py:223` 附近的 explicit `_capture` 调用 `_require_active(..., None)`。若同一计划在等待期间 deactivate/reactivate，旧 due 调用可能先重新接纳新 revision 再提交。沿 `run_intraday_and_publish`、`run_intraday` 和 `_capture` 增加可选内部参数 `expected_activation_revision: int | None = None`。生产始终传入 await 前捕获的 revision；严格 `_capture` 将其传给 `_require_active`，最终提交再次检查同一 revision。禁止换成新观测到的 active revision。`None` 默认值兼容既有独立调用者，但生产严格路径不得使用它。

### A07-F1-04 — 正常不完整与过渡 RED

legacy INCOMPLETE 保持为合法结果，facts=None，且没有 evaluation、claim 或 event。既有分钟和健康记录可正常持久化，但不得新增业务结果、风险、outbox、pending 或 head。遗漏或错配仍拒绝，不能 catch RuntimeError 或伪造 facts。F1 移除偶然的 supervisor 重启恢复后，既有 progress 用例可能转 RED；必须记录此过渡状态，完成 F3 后才能判断修复闭环。

### A07-F1-05 — 失效生命周期与必需竞争对照

`service.py:3483` 附近的 `RuntimeLifecycleService._execute_deadline` 只 await 自有工作并在 `finally` 释放，不吸收带类型的失效异常。正常重新激活若从此处逸出，会新增 `RUNTIME_RUNNER_FAILED` 路径。本设计选定 F1-02 的逐计划转换边界；生命周期收到完整记账且成功返回的 deadline，不收到 stale 异常，继续保留原行情游标并等待下一合格 deadline。不能在旧目标上重新求值替换后的激活、回退游标或丢弃真正遗漏的 outcome。explicit 可变安全事实失效同样记在原 due 身份下，不原地重试。非预期错误仍交监督器。

RED 必须包含协调器捕获至 explicit `_capture` 之间真实 composition/provider 等待：获取暂停时对同一计划 deactivate/reactivate，再释放获取。断言原身份产生专用带类型 stale outcome；被拒 scope 在旧、新 revision 下均为零新增业务写入（包括 explicit ledger/rule occurrence/outbox），既存业务行保持不变。断言没有 RUNTIME_RUNNER_FAILED、runtime generation 相同，且健康兄弟仍按自身捕获身份独立提交。推进下一合法 scheduler deadline，要求继续运行，不能为被拒调用发明新目标或回放它。另测 explicit 求值后、最终事务前改变 activation，覆盖 legacy typed-stale 路径，并证明非 stale 的 `RuntimeError` 及发布阶段的 stale 类型异常仍向上传播。遗漏/重复/多余/错误身份的 outcome 不得进入 stale 捕获。公开默认兼容和正常 INCOMPLETE 作为独立对照。这些真实 composition 断言是 F1 实现的必需验收门槛，不能推迟至 F3。

## A07-F2 — F2 — 冻结获取范围并约束每次提交

### A07-F2-01 — 文件、依赖与唯一写入者

使用 `runtime/recovery.py`、`runtime/recovery_targets.py`、`runtime/production.py`、`market_data/tushare.py`，并从 F2 开始纳入 `web/monitor_composition.py`；`runtime/service.py` 参与权限写入者审计及必要的 owner/取消接线。仅在最终约束需要时允许为 `state/unit_of_work.py` 增加最小 flush/commit 接口。已完成的 SDK 边界实现保护权限证明调用，而非 recovery 使用的普通业务获取。须通过 F2-04/05 的新 opt-in 复用该 resolver/最终入场机制，不能声称业务 guard 已存在。全部 `market_data/tushare.py` 及后续 SDK 边界改动在交接后只归指定的唯一写入者。F2 设计连同下述共享锁协议已获批准，实现仍须串行源码写入者交接及验收，不得并发编辑。

### A07-F2-02 — 不可变捕获与精确需求

复用 `derive_recovery_target`、`select_current_day_rows` 和 `check_minute_coverage`。每个不可变的 `RecoveryCapture` 携带 observed_at、由日历确定的 trade_date/completed cutoff、required_ends、精确计划身份和 activation revision、配置/来源/分钟语义版本及 runtime generation。排队或晚响应不能推进截止点，只有新尝试才能捕获更晚目标。legacy required_ends 是会话开始至捕获时已完成分钟的精确交易分钟前缀，排除午休，最多 240 个。

### A07-F2-03 — 已提交覆盖与安全写入

从真实已提交分钟身份求差集，不能仅用数量、最大时间或健康记录中的 gaps。获取前的 missing 集合仅用于决定是否获取。在最终自有事务中，重读捕获的 `required_ends`，重新计算 `missing_now`，并在暂存写入前立即与已验证响应行取交集。若等待期间另一合法写入者已补齐某分钟，不得再 upsert 该行、其 OHLC/volume/received_at 或其对 latest_quote 的贡献，即使响应时规范化给较早发起的获取赋予了更晚 received_at。空响应及最终空差集不写事实。分钟完整不能替代参考数据、历史官方收盘、库存、规则或新鲜度门槛。

### A07-F2-04 — 逐调用接口

为 `recover_scope` 增加可选逐调用持久化接口，例如 `persist_selected(rows)`，以及本次调用的 guard；既有构造器回调可作为兼容默认值。生产必须显式传入捕获闭包。禁止临时替换 `self._persist_minutes` 或其他共享回调。每次尝试的闭包只读取不可变捕获和自身取消 token。

为此 scoped 路径增加可选逐调用业务获取回调，沿 `_execute_joined` 传至 `_current_day_call`。回调绑定本次尝试的物理入场 guard，并调用具体 provider 的 `current_day_minutes(symbol, _physical_start=...)`；为该具体方法增加此可选关键字，原样传给 `_fetch_frame(_physical_start=...)`。通用 provider 协议及普通无 hook 调用保持 `current_day_minutes(symbol)`，不额外传关键字。未提供 scoped 回调时，recovery 保留原 provider 调用。禁止修改 provider/controller 级共享 hook，也不能以权限证明结果充当业务分钟行。这是内部获取接口，不是新业务政策或用户参数。

### A07-F2-05 — 捕获与物理 SDK 准入

在短的自有 UoW 中一致读取 active plan、activation、calendar 和 source binding，保留 owner 发布的 authority epoch/generation 及逐尝试线程安全取消 token。等待供应商时不持有数据库事务或权限锁。当前 `recovery.py:575` 附近的 `_current_day_call` 只在调用普通 `provider.current_day_minutes(symbol)` 前检查；`tushare.py:296` 尚无逐调用 hook。此前置检查无法约束 wrapper 准备 I/O。按 F2-04 接线后，`_fetch_frame` 先经既有 resolver 解析真实内部 SDK endpoint（包括 wrapper 准备），再执行逐尝试 `_physical_start`，最后调用 endpoint。在该最终 SDK 边界，仅检查线程安全的时钟/来源/代次/取消权限，位于供应商异常分类之外，并保留 `RequestNotStartedError`。保留 recovery 早期检查作为额外 guard，不能以它替代最终检查。worker 不得查数据库或读取 asyncio Task。入场后的编辑可能允许一次过时的只读获取，但最终事务必须拒绝其结果；准入检查并未消除此窗口。

### A07-F2-06 — 事务提交约束

响应后验证时钟、source binding 和行。在 owner loop 同步执行的持久化闭包开启全新自有事务，重读精确 active plan payload/hash/version、activation revision、交易日需求及所需分钟身份。只暂存 F2-03 的 `missing_now` 行；minute 和 latest_quote 变化归同一事务。在最终约束前完成外部文件校验及回调触发的失效发布。若 commit 还会触发暂存回调，须先在进入约束前 flush 暂存内容。

进入 baseline 权限 `RLock`，最终读取内存中的 revoked/epoch、generation、acceptance 和逐尝试取消状态，并用线程安全时钟重新检查时间/日期，然后同步 commit；中间不得 await 或调用应用回调。guard 不通过则离开临界段并回滚整个事务。锁内不得网络调用、重新载入文件、发送通知、join 物理 worker 或额外查询身份。尤其不能在锁内调用 `_decision_commit_current`：此辅助函数含配置/认证文件 I/O，且可能发布撤销。此类权限校验在锁外完成，随后以专用最终只读内存判断读取 owner 当前状态；此前缓存的布尔值不够。scope recovery 不能继续使用未受此约束的通用 `persist_minutes` 回调。该协议只约束 scoped 获取提交，不宣称已改造应用中其他所有业务事务。

### A07-F2-07 — 必须证明的权限假设

在 `_ProcessRuntimeBaseline` 增加一个 `threading.RLock`，由同进程 runtime state 及所有 scoped 持久化闭包共享。当前 `_revoke_configuration` 和 `_revoke_semantics` 在通知 loop 之前直接由 worker 执行 `Event.set()`（`monitor_composition.py:1178/1196`）；两者均须在同一锁内发布 revoked flag/authority epoch，释放锁后才通知 owner。只保证不 await，不能对这些 worker 写入排序。撤销先取得锁并发布，则提交失败；提交先取得锁，则可在被阻塞的撤销发布之前完成。commit 是线性化点，后续撤销不追溯删除它。

使用 `RLock` 而不是不可重入锁，因为校验可能同步调用撤销回调。此类校验必须在最终只读内存的判断之前执行，并在其后重查 revoked；检查至 commit 区间不能放入任意回调。当前 UoW commit 没有应用发布回调，须保留这一性质。撤销发布持锁时不得获取数据库连接，或等待 worker/owner。暂存阶段可以先取得 SQLite 写入权、再获取权限锁；撤销路径禁止反向的持权限锁再获取数据库的顺序。临界段只含有界内存检查和既有有界 SQLite commit，不含供应商工作。

runtime generation 赋值、acceptance/stop 及逐尝试取消 token 由 event loop 持有；正常修改不能与其同步闭包交错；取消先设置线程安全 token，再取消自有 task。实现写入者清单还必须覆盖最终 generation 替换、数据库资源就绪/释放，以及 `business_commit_admission_open` 的全部依赖：`_stopping`、`_cleanup_complete`、`_cleanup_failed` 和 `_liveness_failed`，包括心跳/存活失败及 cleanup 路径。最终内存判断必须保留这些依赖，不能只比较 generation。其他线程请求任一此类变更时，要么仅投递给 owner 而不直接修改权限，要么先通过同一锁发布变更再通知。若把 scoped 持久化移到 loop 外，却未将相关 setter 纳入协议，该证明失效。

另用真实应用引擎和双连接证明数据库约束：A 执行 explicit BEGIN 并读取 plan/activation 身份；B deactivate/reactivate 后 commit；A 再尝试 minute/latest_quote 写入。A 必须因旧 snapshot 无法升级而失败，回滚整个事务，B 的新激活保持完整。任何连接/session 重试都不得复用 A 的旧捕获。将已识别的存储竞争交 owner，后续尝试只能重新捕获。还须证明最终取锁前已发布撤销时零写入、提交先取得锁的顺序，以及重入撤销回调不会死锁。

### A07-F2-08 — 错误通道与取消

通过内部带类型状态，或仅在明确边界转换的专用异常，将 guard 失效/重新定目标与正常 INCOMPLETE、供应商故障、存储故障分开。收窄 recover_scope 中宽泛的 Exception-to-PERSISTENCE_FAILED 捕获：guard 变化按 F3-09 处理；已识别存储失败保留类型/cause 供 owner 处理；程序错误和取消向上传播。特别是数据库 snapshot 升级竞争不能进入通用旧捕获重试循环。不得将 guard 归为权限/cooldown 故障或静默无限重试。

### A07-F2-09 — 时钟与日历边界

跨日或 now 早于 captured_at 时，拒绝本次写入并重新捕获。日历未知时不能猜测交易日，也不能用当前日接口补历史。每个阶段检查回拨；检查点之间发生并完全恢复的回拨，若没有独立 clock epoch 能力就无法检测，该能力不在本片范围。

### A07-F2-10 — F3 前的启动接线

先将启动股票分钟获取替换为冻结 scope 路径，保留既有官方收盘恢复顺序与启动错误政策。每个 symbol 独立捕获；过渡期启动最多 10 个 symbol，每个最多 240 个所需分钟。F3 再将启动缩为最多一次股票获取，其余交调度。不新增数据库状态，业务恢复与权限探测语义保持区分。

## A07-F3 — F3 — 现有 owner 内有界自主恢复前缀

### A07-F3-01 — 调度接口与归属

使用 `runtime/production.py`、`runtime/scheduler.py`、`runtime/reconciliation.py`、`runtime/service.py` 和 `web/monitor_composition.py`。复用纯 `RecoverySchedule`，不另启 `RecoveryCoordinator` 后台循环。获批设计增加内部 `STOCK_RECOVERY` maintenance deadline 及 `next_stock_recovery_at` / `run_stock_recovery_unit` 接线，由既有 runtime `_execute_deadline` 持有。scheduler 的 next 回调只读内存时间，初始化及恢复/行情工作后同步有界需求。

使用股票专用 schedule 实例，独立指数 scope 及其权限 owner 保持原样。股票 owner 缓存下一 wake、需求和权限观测；在启动、行情/权限/恢复工作后以及维护轮询时更新这些有界本地观测；scheduler getter 不查数据库、不做权限探测、不修改状态。已有权限 owner 可通知 loop 重新同步，但不增加第二个循环或隐藏请求。

### A07-F3-02 — 有界工作、稳定重试与公平性

每次 maintenance wake 最多处理一个 symbol、一次当前日请求和 240 个已提交分钟身份。短读取最多枚举 10 个 active 身份，轮转选择可执行 scope，不做无界历史扫描。使用稳定键如 `stock-prefix:{symbol}`，revision 表示依赖身份、目标和 F3-10 定义的本地权限就绪 epoch。跨目标版本及晚完成保留 RecoverySchedule 的 RETRY deadline，避免每个新分钟绕过 cooldown。单 symbol 失败不得饿死其他可执行 symbol。所有调用仍共享既有 controller 节流及 HTTP 429 cooldown；指数 scope 独立不意味着可以绕过该共享限制。

沿用实际 live controller 既有的 `LIVE_TUSHARE_IN_CYCLE_RETRIES=0`。此前基于通用默认 `execute` 重试提出的疑虑不适用于此生产 composition，现已撤回；F3 不增加重试接口或新重试政策。

### A07-F3-03 — 重启、部分数据与重试时间

最终启动最多执行一次股票 scoped 获取，其余由真实 maintenance wake 执行。重启从 active plans 和已提交覆盖重建需求，无需 pending 表。既存完整前缀不重复生成业务记录；保留部分事实，仅修补缺失身份。空/部分响应是正常 incomplete scope：ticket 以完成时刻加既有 `MAINTENANCE_INTERVAL` 的 30 秒进入 RETRY，不能立即置 PENDING。本地轮询上限为 30 秒，但物理入场可能因行情预留、供应商 next_retry_at 或共享 cooldown 等待更久。这些上限不是恢复 SLA。存储/程序故障不得当作正常不完整。

### A07-F3-04 — 真实行情优先级与准入

maintenance 使用真实行情 deadline，同刻行情任务优先。复用 31.25 秒预留：now 加预留覆盖行情 deadline 时让位，给出明确下一 wake，不忙循环。排队后在真实 SDK 入场处重新检查冻结行情窗口。不得将维护任务自身运行状态误认为实时任务。超时/drain 仍由既有 runtime/controller 持有；预留不能证明任意供应商绝不超时。

只加 enum 和 dispatcher 分支不够。定义明确的生命周期 maintenance 分类，包含既有 `INDEX_PERMISSION` 和已批准的 `STOCK_RECOVERY`，并在两处共用：`service.py:3225` 的 `_advance_progress_deadline` 不得推进 `_last_deadline_at`；`service.py:3089` 的已过行情复查必须保留 `market_review_after`，不能换成 maintenance due_at。未另行评审前，既有 `INDEX_RECOVERY` 行为保持原样。若没有先前行情游标，保留该路径当前在执行前取得的观测时刻，不推导更早的启动游标。维护请求等待或超时返回后，既有有界复查只可处理恰好一项已过 REALTIME_MINUTE 职责，且原目标年龄仍为 0..90 秒。多项已过职责仍遵循既有不回放行为。

### A07-F3-05 — 启动预留政策与实质 C2 负控

既有 C2 于 10:00:59 进入 SDK，10:01:13 返回，处于 10:01:12 行情 deadline 前的 31.25 秒预留内。新预留 guard 仅适用于常规 maintenance，保留一次有界 startup 调用的准入并冻结截止点。当前 `service.py:3000` 附近的 `_start_sequence` 在恢复后调用 `next_deadline()`，该 scheduler 排除更早的 due time。并不存在可保留的启动后立即执行已过 deadline 路径。本设计不增加它：C2 启动完成后可进入下一未来行情职责。F3-04 的已过复查适用于调度维护结束后，不是启动回放。把预留扩至 startup 或增加启动立即追赶均需另审。C2 必须保留真实获准入场的 10:00:59→10:01:13 SDK 调用；禁止以未调用冒充截止点约束修复。

### A07-F3-06 — legacy 与 explicit 需求

legacy 需要完整当天分钟前缀。explicit 求值保留其实际 FiveMinuteBars 依赖：current-bar 条件、rolling-volume 的 window_bars+1 及合法交易邻接是不同需求。不能给所有 ExplicitTradePlan 强加 legacy 前缀就绪门槛。explicit 既有有界当天分钟预取可保留，但不能证明跨日 lookback 已恢复。保留既有 explicit 求值/依赖行为，新增按条件推导历史恢复需求需另审。

### A07-F3-07 — 决策新鲜度与既有生命周期合约

恢复仅持久化事实并重新校验覆盖，不回放错过的五分钟决策。仅通过合法实时工作或 F3-04 中既有的调度工作结束后有界已过复查求值，实际 evaluated_at 减 target 保持 0..90 秒。正常不完整及预期的逐 scope 失效不将全局置 DEGRADED，也不触发 runner 换代。保留 manual stop/edit/start、120h 存活准入以及官方收盘自主发现/幂等，不重写该链路。不增加新的业务/用户参数。

### A07-F3-08 — 取消、drain 与传播

stop 先撤销准入及本尝试取消 token，再取消自有任务。已物理开始的 worker 继续 shield/join，drain 前不释放请求槽位，也不提前关闭数据库。晚响应不能写入；晚供应商错误在完成 drain 时沿既有 controller 记录，最终重新抛出取消。正常路径错误交 owner，不得被新维护循环吞掉。

### A07-F3-09 — 封闭维护结果矩阵

下表是 `run_stock_recovery_unit` 处获批的处理契约，不是宽泛异常捕获，也不改变无关行情工作的错误政策。

| 观测结果 | scope/owner 处理 | 物理调用边界 |
|---|---|---|
| 精确已提交需求完整 | 本 revision 为 READY；后续目标变化可产生新 scope 尝试 | 不能仅为证明已提交覆盖再次获取 |
| 合法空/部分响应，仍有缺失身份 | 保留已验证的新事实；完成时刻 + 30 秒进入 RETRY | 重试前服从预留和 controller 准入 |
| 可重试供应商失败、限流或 cooldown | 保留带类型供应商分类；RETRY 不早于完成时刻 + 30 秒及供应商 next_retry_at 两者 | 跨目标版本/晚完成保留较晚期限；共享 429 节流仍有效 |
| BLOCKED_PERMISSION | BLOCKED，保留 operation 及阻断权限观测 | 业务恢复不得调用 `recheck_permission`、清除阻断或以业务成功代替证明；仅按 F3-10 重新 arm |
| 本地准入让位 / `RequestNotStartedError` | 区分预留让位与捕获失效；让至明确的下一行情安全 wake，或在后续有界 wake 重新捕获 | 物理尝试为零；不能伪造供应商失败/cooldown |
| Activation/target/date/clock guard 失效 | 丢弃旧闭包，重新同步精确需求并捕获；移除已停用 scope | 不重试旧捕获；若无权威日历/目标，不发当前日请求，保留有界本地复查 |
| Configuration/source/semantic 撤销或 NEEDS_RESTART | 发布 F2 撤销，交既有 runtime 阻断/重启处理 | 被撤销 baseline 下不重新 arm、不热加载、不发业务请求 |
| Runtime generation 已不当前或正在停止 | 终止该 owner 的工作；替换 generation 自行重建需求 | 旧 generation 内不循环重新定目标 |
| 存储错误，包括 SQLite 旧 snapshot 升级竞争；程序/协议错误 | 回滚，向既有 owner 传播带类型错误 | 不转换为空/部分/供应商失败，不自动重试旧捕获 |
| 取消 | 完成既有物理 worker drain/记账后重新抛出 | 不提交晚事实，不提前释放槽位/数据库 |

### A07-F3-10 — 显式重新 arm BLOCKED

`RecoverySchedule.claim` 跳过 BLOCKED，相同 requirement 不会自动重新 arm；而 `synchronize` 通常会把变更的非 RETRY requirement 重置成 PENDING。因此只要其权威 controller operation 仍阻断，股票 owner 就必须冻结该 BLOCKED schedule requirement revision，单纯时钟/目标变化不能重置它。最新所需目标单独保留在有界 owner 缓存中，不使其可执行。新发现的阻断 scope 可通过一次本地 ticket 完成成 BLOCKED，不发 SDK 请求。

在 F3-01 的 owner 同步点读取 `is_permission_blocked(operation)`。只有此前已观测阻断、随后权威 controller 转为 blocked→cleared，且 source/semantic binding 相同且未撤销时，才递增该 scope 的本地权限就绪 epoch。证明和解除阻断由另行评审的权限 owner 负责。使用 `synchronize`，以最新捕获依赖/目标及新 epoch 替换冻结 requirement；这一明确 revision 变化使 BLOCKED 重新成为 PENDING。物理入场前再次检查 controller 权限/cooldown。重试时间到达、新目标、供应商健康标签或普通业务响应均不是上述转换。专用权限 owner 若不能提供解除，scope 就保持 BLOCKED；F3 不自行发明恢复探测。轮询/通知更新下一 wake 缓存，scheduler getter 自身仍为只读。

## A07-VERIFY — 实施顺序与 RED 验证矩阵

### A07-VERIFY-01 — 薄片 A：结果关联

F1 设计已获准独立实施。先证明 facts=None 关联、遗漏/重复/多余结果、错误 symbol/hash/version/activation/target、带类型失效记账、混合消费者及输入顺序的 RED。纳入 F1-05 的真实 same-plan deactivate/reactivate await 竞争及最终事务竞争；断言原调用不提交新 revision 业务、合法兄弟独立成功、预期 stale 不引发 runner 故障/换代、非预期错误继续传播。补 explicit inventory/risk 失效、发布阶段 stale 类型异常传播及公开默认对照。记录过渡期 progress RED，不能放宽预期；仅 F1 GREEN 不能关闭 A07。

### A07-VERIFY-02 — 薄片 B：逐调用 scope 与冻结启动

F2 设计评审已完成；串行 source/SDK 写入职责交接后才实施，再满足验收门槛。保留 SSMC-C2 修复前 RED、修复后 GREEN，以及 SSMC-C1 排除未来行和 SSMC-C3 新捕获接纳行。覆盖空/部分/残存精确身份及并发捕获无回调串用。供应商等待期间另一合法写入的 minute 与 latest_quote，在旧响应返回后必须精确保留其值和时间戳。使用真实双连接及 explicit BEGIN 实施 A-read/B-reactivate-commit/A-write 竞争，证明整事务回滚且不重试旧捕获。测试 worker 在最终约束前发布配置/语义撤销、提交先行顺序、重入回调安全、全部相关权限写入者、stop/edit/restart、跨日和回拨。事后断言或仅检查无 await 的测试都不能证明跨线程保证。

用离线 fake 覆盖真实 provider/wrapper/resolver 路径：允许 wrapper 准备 I/O，随后在 resolver 返回前发布撤销，或推进至 maintenance 入场窗口之外。要求 scoped 业务 hook 在最终入场处拒绝，实际 SDK 调用为零；只在 adapter 入口放 fake 不够。另证并发捕获的 hook 隔离及普通无 hook 兼容。保留合法 startup C2 于 10:00:59→10:01:13 的 SDK 调用及其冻结截止点；maintenance 预留不得阻止该调用。

### A07-VERIFY-03 — 薄片 C：真实自主进展

F3 设计已获批准，但实现及验收仍待 F2 和串行源码写入者交接；使用真实 composition 和 scheduler wake。空/部分启动后恢复供应商历史，要求在测试有限期限内补原前缀，并于 10:05:12 生成合法 10:05 决策。把目前仅打印 generation 变化的观测升级为硬断言：首次启动后捕获的 generation 在恢复全过程和最终成功时均不变，且没有 RUNTIME_RUNNER_FAILED 边界。不得直接调用恢复/求值、强制 DEGRADED 或依赖 supervisor 换代。历史仍不可用时保留独立安全断言，并保留全部真实求值时间/来源前缀检查。

### A07-VERIFY-04 — 薄片 D：有界性与生命周期

验证十标的轮转公平性、单标的 cooldown 时其他标的前进、行情同刻优先及物理入场重查、目标推进不能绕 retry，以及 BLOCKED scope 仅在观测权威权限解除后重新 arm。维护调用排队跨行情 deadline 时，必须同时保留行情游标和复查起点，最多处理既有的一项新鲜已过职责，原目标及真实年龄保持 0..90 秒，并拒绝过时/多项已过回放。证明 startup 仍选择未来 deadline，C2 仍准入其跨界调用。覆盖 F3-09 每一行、完整事实无重复业务副作用、部分事实重启保留、独立指数 scope/共享 429 节流、worker 阻塞时 stop 不提前关库或释放槽位，以及晚响应零写入。

### A07-VERIFY-05 — 薄片 E：回归与证据记账

独立重跑原 A07 13 项，保留全部三项 oracle 对照。运行新增门槛和相邻 coordinator/recovery/scheduler/lifecycle 检查、既有四项官方收盘强杀重启用例，以及定向 120h/manual-admission 回归。作者与独立运行分别记录，不能将重叠套件数字相加。实质文档同步两种语言。三项真实失败及正常自主恢复均获证据关闭后，才能宣称完成。

## A07-SCOPE — 未批准扩展与残余权限边界

### A07-SCOPE-01 — 排除的架构与行为变更

本契约不批准持久恢复队列或数据库迁移、官方收盘重写、全业务 scope 通用 dispatcher、全局 DEGRADED 政策、自动修改计划/存活规则、历史决策回放或新新鲜度阈值。各片设计获批不授权这些扩展，也不授权本次仅文档工作修改源码；F2/F3 仍须串行源码写入者交接。

### A07-SCOPE-02 — 既存事实来源

canonical minute 表没有逐行来源/分钟语义版本。捕获约束可以限制新获取写入，不能追溯证明既存事实的语义来源。来源切换后的清理/重建及来源证明需独立设计，不能默认为已有保护。

### A07-SCOPE-03 — 其他恢复与权限政策

新增 explicit 历史 lookback 恢复、未知日历自主恢复、startup 预留/追赶政策变更及 clock epoch 能力均需单独界定评审。F2 对新 scoped 提交和已经发布的 runtime 撤销进行排序；不能使任意外部配置/语义文件写入与 SQLite 原子化，不能检测未观测的编辑，也不授权热加载。既存分钟来源仍受 F2-03 和 SCOPE-02 限制。数据库提交竞争与跨线程撤销保证仍是待证明义务，不是已实现事实。三个设计均已获批，实现验收仍待完成。F1 已独立放行，但不关闭 S3-04，也不掩盖过渡期 progress RED；F2/F3 待串行源码写入者交接，F3 依赖 F2。本次仅文档工作中，原 A07 三个证据文件保持既有内容且未提交。

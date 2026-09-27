# C1 统一权限调度契约

状态：**独立 Sol 评审后设计获批 / 尚未实现**。

两项评审 P2 已关闭：UPD-03/R05 区分 scope 仲裁与一次 DAILY_BARS 准备后冻结的实际候选；UPD-04/R02 区分纯时间 getter 与有界新鲜 B1 证据读取。S1–S5 可按下文源码交接和实现验收门槛推进。这不代表 C1 或 A07 完成。

## UPD-01 — 范围、依据与证据

本提案将已批准的 B1/B2 选择/预约契约和 SMWO 股票分钟 owner 接入 RUNNING 与 DEGRADED 共用的一条八 scope 权限维护路径，规定接线、时钟、错误归属与验收，不新增权限证明或交易政策。C1 保持 OPEN。本任务只新增本契约及英文对应文档，不修改源码、测试或既有文档，不提交。

只读观测基于 2026-09-27 的 HEAD `47a803b` 及共享工作树。股票分钟 execution 和 A07 F1 源码写入者正在工作，其未提交内容不是已验收证据。下文符号引用用于定位接线点，不是固定行号。自动启用 SMWO scope 前必须先完成其 execution 验收。本提案不实现设计已获批的 A07 F3。

依据：[runtime recovery 计划](../../tasks/runtime-recovery-plan.zh-CN.md)、[B1 选择](2026-09-26-b1-permission-candidate-selection.zh-CN.md)、[B2 预约确认](2026-09-26-b2-controller-reservation-ack.zh-CN.md)、[B2 轮转](2026-09-26-b2-permission-candidate-rotation.zh-CN.md)、[SMWO](2026-09-27-c1-stock-minute-permission-owner-contract.zh-CN.md)、[SDK 边界](2026-09-27-c1-sdk-call-boundary-contract.zh-CN.md)及 [A07 修复](2026-09-27-s3-startup-minute-repair-contract.zh-CN.md)。已批准的证明身份、边界和来源模式差异继续有效。复用已验收的 DAILY_LIMITS、DAILY_BARS 和 INDEX_DAILY owner，包括 DAILY_BARS 需求 receipt 与 O/F 交替；此处不重复或泛化这些证明。

不授权热重载、真实供应商/通知服务、用户数据库、迁移、推送或部署。未来测试使用临时 SQLite、fake SDK/transport、真实 wrapper/controller 及可控时钟。本设计文档不声称任何实现测试通过。

## UPD-02 — 完整 scope 清单与已确认缺口

注册顺序严格沿用 `_PERMISSION_SCOPES`；selector、廉价 getter 与 dispatcher 必须使用同一注册表。

| Scope | 精确 endpoint | 接线义务 |
|---|---|---|
| `TRADING_CALENDAR` | `trade_cal` | 用经过选择且持锁的 owner 替换 `_request` 内联复查；增加最终 SDK 入场 hook；保留精确已完成 SSE anchor，可为休市日 |
| `INDEX_HISTORICAL_MINUTES` | `idx_mins` | 旧 owner 接入共享锁、全局选择及持久预约确认；增加最终 SDK 入场 hook；保留完整已结束会话证明 |
| `INDEX_REALTIME_MINUTES` | `rt_idx_min_daily` | 接入共享锁、全局选择及持久预约确认；复用已评审最终 SDK 边界及既有指数证明 |
| `DAILY_LIMITS` | `stk_limit` | 接入已验收的日期范围 owner 及今日合格 legacy 需求 |
| `DAILY_BARS` | `daily` | 接入已验收的当前/历史 legacy 需求 receipt 及 O/F owner |
| `INDEX_DAILY` | `index_daily` | 接入已验收的独立指数 owner |
| `CURRENT_DAY_MINUTES` | `rt_min_daily` | SMWO execution 验收后接入，保留独立 symbol 游标 |
| `REALTIME_MINUTES` | `rt_min` | SMWO execution 验收后接入，保留独立 symbol 游标 |

当前 composition 的 `next_index_permission_at` 和 pipeline 的 `run_deadline(INDEX_PERMISSION)` 仅考虑两个指数分钟 scope。`_request(TRADING_CALENDAR, ...)` 可在全局仲裁外触发 `_maybe_recheck_calendar_permission`。旧指数 owner 没有共享 maintenance lock 或 `on_reserved` 回调。既有廉价 `next_permission_probe_due_at` 已只读八项 controller/local 时间而不查 SQLite；自动调度应使用它，不能继续使用会读取权限的旧指数 getter。

提交 `4804207` 未覆盖 calendar 或历史指数权限调用的最终 SDK 入场。calendar 缺少逐调用物理 hook；历史指数在 resolver 工作前的 adapter/worker 入口检查。补这两处接口及 owner guard 是待实现工作，不能继承其他六个 scope 的证据。

## UPD-03 — 最小接口与串行选择

增加一个 pipeline 入口 `async run_permission_maintenance_unit() -> PermissionMaintenanceResult`，持有既有 `_permission_maintenance_lock`，最多分派一个所选 scope。保留 `PermissionMaintenanceResult` 的 `SKIPPED`、`DEFERRED`、`PROBED`、`FAILED`，无需更改公开状态/API 版本。

将 scope 实现整理为私有持锁函数体。单一私有 dispatcher 接受可选 `requested_operation` 兼容包装调用：直接调用 `_maybe_recheck_*_permission` 时也获取同一锁，仅当该 scope 赢得全局选择才可执行。不得重复获取不可重入 asyncio 锁，不得循环调用八个公开持锁方法，也不能让按名称调用绕过公平性。生产自动调用只走共用入口。

锁内读取当前 due/controller 状态及既有有界候选证据，按 UPD-04 设置已到期但不可用项的本地检查，再按原始预约及轮转同刻顺序选到期 scope/rank。保留 DAILY_BARS 准备层既有的 synthetic own-scope rank，包括缺少 broad DAILY_BARS anchor 的情况；全局仲裁不能在需求准备前就把最终执行绑定到 broad symbol/day 提示。对所选 scope 恰好做一次既有的新鲜准备。DAILY_BARS 的这一次准备先检查 scope rank，再做有界需求工作：最多读取一页历史并校验 10 个需求 receipt，随后从 `valid_symbols` 形成真实 O/F 候选。到此才冻结真实候选、匹配 receipt 及本次调用捕获。因此，A 的 broad 提示没有需求时，可合法产出拥有有效 receipt 的 B。其他 scope 保留既有身份校验规则。

选择提示不是可保留的执行权限。不能先准备一次挑 winner、再在执行函数体重新准备，不能消费外部旧准备，不能对已准备 DAILY_BARS receipt 再翻页，也不能在执行/响应校验时替换已冻结的真实候选。准备转 UNKNOWN/让位就结束本 unit，不能在同一 unit 再尝试其他 SDK scope。

预约前立即重查 due/权限，并从当前状态预计算一个不可变游标替换值，只以 `on_reserved` 传给既有 controller。controller 成功持久预约是唯一且仅一次的游标确认点；选择、物理开始、响应或成功均不确认。maintenance lock 覆盖 owner 准备/预约/结果校验；SQLite 事务不能跨供应商 await。取消时释放该锁，由 controller 保留并 drain 物理槽位。每个 unit 最多新建一次预约、最多一次物理调用，预约后失败的 unit 也不例外。

## UPD-04 — 纯 getter、固定本地检查与进展

每个阻断 operation 使用 `effective_due = max(raw_due, local_defer, shared_429)`，只在当前可执行候选中按 raw due 加轮转选择。pacing 与 work-key backoff 仍由 controller 决定；unit 返回的明确 controller retry floor 保留为该 scope 的本地最早时间。共享 cooldown 不得覆盖 raw 排序。保留全局 scope 游标、DAILY_BARS O/F 状态和两个分钟 symbol 游标。

`next_permission_probe_due_at` 和 composition 调度适配层只读有界内存 controller/local 时间。重复调用不做 SQL、认证/配置 I/O、翻页、预约、探测、游标更新或 `now + 30s` 赋值。候选存在性检查不放进此 getter。它包括当前缺需求或 anchor 的阻断 scope，以便重新检查本地条件。

零 I/O 契约只约束 timing getter 及其调度适配层，不约束 B1 的 `permission_probe_candidates` 或 `select_due_permission_probe`。这些有界候选/选择 peek 可按既有契约读取 SQLite 证据及认证/配置权限，但不预约、不调用 SDK、不写游标。不能强迫其使用陈旧缓存，也不能把它们用作 scheduler timing getter。其证据读取也不授权第二次 DAILY_BARS 需求准备。

只有真实到期维护检查，才能为缺 consumer、anchor 或暂不可用 scope 权限的阻断项记录固定 `checked_at + 30s` 本地复查。覆盖全部此类到期 scope，不能仅处理 B1 较窄的 missing-anchor 清单，否则缺 consumer 会让 getter 永久过期。固定时间前重复 peek/进入不滑动期限。已知合法会话开启时刻沿用该 scope 的既有 earliest-start；明确行情阻挡沿用 blocker deadline 加一微秒。每个已检查但不可用的 scope 或所选未启动结果，必须获得有依据的未来本地时间，或确认该项已不阻断。未被选中的可执行兄弟可继续到期，等待下一串行 unit。禁止零延迟 SKIPPED 循环。

一次有界检查可更新多个不可用 scope 的本地期限，但只能预约/探测一个。所选准备期间失效的候选得到自己的 defer，另一个就绪 scope 可在 owner 下一轮获选。本地检查不移动 scope 游标。稳定、合格且 raw due 相同的集合在重复前应全部获得预约机会；一般进展仍依赖权限、行情空隙和 controller 准入，不是固定恢复 SLA。

没有安全 pipeline 时，composition getter 返回 `None`，权限执行跳过且不自行创建 pipeline。DEGRADED 仍等待既有完整 startup deadline；缺失不能转为立即重试。全局撤销或 NEEDS_RESTART 走既有阻断/显式 stop 路径，不在已撤销 baseline 下无限本地轮询。持久日历 anchor 未知不能授权盲探日历或按星期推断。

## UPD-05 — Calendar 与历史指数最终入场

仅为 `probe_trading_calendar_permission` 及其私有 calendar 路径，以及经既有指数 SDK-call helper 的 `probe_historical_minutes_permission` 增加可选逐调用 `_physical_start=None`。先构造全部普通参数，使用 `resolve_permission_endpoint` 完成 wrapper 检查及内部 callable 解析，再紧邻已解析 SDK callable 调用之前执行最终 owner hook。普通无 hook calendar/index 获取保留 kwargs、解析、缓存及错误行为。禁止把私有 hook 传给 Tushare、替换共享回调或跨调用复用已准备 endpoint。

沿用 SCB 顺序：权限 I/O 全部完成后只采样一次 S，再检查原 scope 的同日/无回拨、`captured_at <= S <= captured_at + 15s`、原模式有效期、generation/stop、source/provider/factory 身份、calendar epoch/Event、取消及冻结的 31.25 秒行情窗口，随后直接调用。worker 不查 SQL、不读 Task。缺 scheduler-window 权限应本地让位，不能无限制放行。保留供应商 sanitizer 之外的同一个 `RequestNotStartedError`；未知 worker 故障仍为 controller `ERROR`，不能伪造权限拒绝。

Calendar 与历史指数 owner 在预约前，以及通过捕获 session factory 开启的一次新鲜自有 explicit-BEGIN 响应 snapshot 中，重验精确原始持久 anchor、冻结来源及 calendar token，另一合法日期不能替代。calendar 可保留已完成休市日 anchor，历史指数仍需已完成 SSE 工作日开市 anchor。calendar 重新 arm 遵循 SMWO 的 epoch 加 Event 比较及新 Event 安装，不清除旧 token。冻结原 owner Task 及取消 Event，在已请求取消时拒绝解除阻断。保留各自既有 proof parser 及 scope 专属响应时间规则，不把股票分钟行分类强加给指数历史，也不新增通用认证过期政策。证明响应不写 calendar、市场历史或缓存。

## UPD-06 — RUNNING 接线与行情优先

复用 `DeadlineKind.INDEX_PERMISSION` 作为八 scope 共用的既有内部权限维护调度槽位。历史名称不限制注册表；不增加第二个 permission kind/loop，不改外部状态名。composition 的 `next_index_permission_at` 变成廉价八 scope getter 的薄适配层；pipeline 对应 deadline 分支调用 `run_permission_maintenance_unit`，不再比较两个指数期限。移除 `_request` 中的 calendar 复查：普通 calendar 请求被阻断时必须保持阻断，由共用维护路径按自身时钟修复权限。

scheduler 保留到期相同时真实行情优先，准备和排队后的最终物理入场处均保留既有 31.25 秒预留。使用 `permission_market_window` 的真实已知/可能行情职责，不用常量假 next deadline。不能把维护任务自身当成正在运行的行情。队列优先级、单 worker、1.25 秒启动间隔及既有 15 秒 timeout 仍由 controller 持有，均不能证明强制中断 SDK。

在 `_advance_progress_deadline` 和 `market_review_after` 分支共用生命周期 maintenance 分类。权限工作既不能推进 `_last_deadline_at`，也不能替换原已过行情复查起点。A07 F3 后续实现 `STOCK_RECOVERY` 时加入同一分类，本任务不实现它。无关 `INDEX_RECOVERY` 行为保持原样。调度维护后复用既有有界复查，最多执行一项原目标年龄为 0..90 秒的新鲜已过 REALTIME_MINUTE 职责；不回放多项/过时职责，不新增 startup catch-up。权限工作必须在普通 reference/evaluation/delivery 分派之前返回，包括 index-only composition。解除权限阻断不代表 READY 或业务执行权限。

## UPD-07 — 既有 owner 中的 DEGRADED 双时钟

为生命周期增加可选内部 `next_permission_maintenance_at` 回调，既有独立调用者默认无期限。生产接入 RUNNING 使用的同一廉价 composition getter。到期权限维护 deadline 经既有 `_execute_deadline` 自有工作路径和共用 pipeline dispatcher 执行；DEGRADED 时不调用普通行情工作、不设置 `_accepting_work=True`、不另启后台 coordinator。

分别维护内部 `startup_due`/`startup_attempt` 及权限时间。进入一次 degraded retry 阶段时，按既有 30/60/120/300 秒递进及已发布 controller floor，只计算一次下一完整 startup deadline。可中断地等待该固定期限与 permission due 中较早者。权限检查/结果只能更新权限时间及共享 controller 状态，不重置 attempt、不把 startup 重算成 `now + delay`、不缩短其 floor、不调用 `_recheck_degraded_startup`。后续共享 429 或相关 controller floor 可延后 startup 最早时间，不得提前。既有公开 retry 字段仍表示完整 startup retry，不增加状态字段。

两个时钟同时到期时，先执行恰好一次合法完整 startup retry。若正常失败，只递增一次 startup attempt，并按该次完成时刻及 controller floor 固定下一 startup deadline，再重新判断 permission due，最多运行一个安全权限 unit 后重新等待。startup 成功则进入既有 RUNNING 路径及行情优先规则。因此固定同刻顺序不会因重复选择已消费 startup deadline 而饿死权限工作。权限工作跨过 startup deadline 时，完成后最多执行一次已到期 startup attempt，不回放错过的 retry，也不重叠调用。

当前 `probe_capabilities` 已复用仍合法的 pipeline，须保留：同 generation 下反复 startup 失败不能丢掉其锁、raw/controller 状态、local defer、全局游标、O/F 状态及分钟 symbol 游标。首次合法本地 bootstrap 可安装 pipeline；maintenance 不能反复重建或重装来源语义。既有冻结权限丢失须沿当前 NEEDS_RESTART 路径，不能以重建重置状态。进程重启可重置内存游标，但按 UPD-10 保留持久准入 floor。

当前 `generation_current` 组合数据库 READY、`business_commit_admission_open` 和 generation 相等；该 admission 属性检查 stop/cleanup/liveness，不检查 `_accepting_work`。保留这些绑定及 baseline 撤销，它们已允许合法 DEGRADED owner 执行只读权限证明；不新增宽松 capability，不放宽存活、数据库、配置或语义门禁。权限成功本身不能退出 DEGRADED 或触发业务求值，只有既有完整 startup recheck 可确立 RUNNING。

## UPD-08 — 时钟/动作矩阵

| 观测 | 必需下一动作 | 禁止影响 |
|---|---|---|
| RUNNING 行情与权限同刻到期 | 先行情，随后重验权限窗口 | 权限结果消费行情游标 |
| DEGRADED 权限早于固定 startup due | 一个安全权限 unit，保留 startup 期限及 attempt | 立即完整 startup retry 或放行业务工作 |
| DEGRADED 两者均到期 | 先一个 startup attempt，正常失败后固定其下一期限，再判断一个权限 unit | 反复选择 startup 而不给合格权限工作机会 |
| 到期检查缺 candidate/consumer/anchor | 固定 30 秒本地复查或既有已知会话边界 | 滑动 getter 期限、预约或推测性网络证明 |
| 共享 cooldown 或更晚 controller floor | 服从更晚的最早时间，保留 raw 公平顺序 | 新目标/scope 唤醒绕过 300 秒或共享 429 |
| 队列/resolver 跨过 latest start 或行情预留 | SDK 启动为零，保留已有预约/ack，设置明确本地 defer | 同一排队尝试内重新捕获 |
| 跨日或时钟早于捕获 | 捕获失效，后续 owner 有界新检查 | 复用旧日期/anchor 或回放定时器 |
| pipeline 缺失，合法本地 owner 仍 DEGRADED | 权限 getter `None`，保留既有 startup 等待 | 安装新 owner 或零延迟维护循环 |
| NEEDS_RESTART、stop、liveness/cleanup 失败 | 通过既有生命周期撤销/终止 | 维护恢复来源或业务权限 |

## UPD-09 — 封闭结果、错误与副作用

| 结果/错误 | 维护边界行为 | 记账 |
|---|---|---|
| 未阻断/未到期 | `SKIPPED`，刷新廉价时间 | 不变更预约/游标/SDK |
| 缺本地前提或 `RequestNotStartedError` | `DEFERRED`，固定/明确下一检查时间 | 预约前无变更；预约后保留 floor 及仅一次 ack；sentinel 不新增供应商失败 |
| 合法证明且最终 owner 校验通过 | `PROBED`，controller 只解除本 operation，删除其自身 local defer | 无业务行、health READY、求值、告警或投递 |
| 已知 permission/429/transient/timeout/invalid response | `FAILED`，保留阻断及相应 retry/cooldown 时间 | 保留持久预约及 controller timeout/late-failure 记账 |
| `ERROR`、`CLOSED`、`QUEUE_FULL`、SQL/storage/checkpoint/callback 或程序/协议失败 | 传播至既有 lifecycle/supervision，不映射普通 `FAILED` | 不伪造供应商分类或自动权限 retry loop |
| `CancelledError` | 标记本调用取消后重抛，沿既有 owner stop/drain | 不晚解除权限，保留预约和物理槽位 |

必要时收窄旧的宽泛 `RequestControlError` 捕获，使八个 owner 全部服从同一矩阵。统一 dispatcher 不捕获任意异常。两个模式中的预期供应商失败均作为 scoped maintenance outcome 消化，不单独将 RUNNING 全局改为 DEGRADED、不重置 startup 时钟、不触发 supervisor 换代。真实无关行情/startup 错误保持原政策。未知 worker 错误可继续由 controller 包装成 `ERROR`，不承诺保留原异常类型。

## UPD-10 — 停止、持久预约与跨进程边界

复用既有 work-task owner、owner Task 取消检查、逐调用 Event 和 controller shield/drain。stop 先关闭准入再取消；已物理启动的工作保留槽位直到 join，随后才释放存储/owner。取消后晚响应不能解除阻断或复活新调用。不能仅为 join 已取消 worker 而持有 maintenance lock。晚 sentinel 不抹去已记录 timeout。既有 live controller 使用 `LIVE_TUSHARE_IN_CYCLE_RETRIES=0`，本提案不新增 retry 政策。

持久 300 秒预约先 commit，再确认游标及入队。队列 veto、取消、timeout、无效响应及预约后 guard 拒绝均保留它。worker-start floor 延伸不再次确认。旧 owner 成功关闭后，才由新进程重开临时数据库，证明同 operation 在存储 floor 前不得再预约，包括共享 429 cooldown。轮转及本地检查保留为进程本地；预约 commit 与确认之间崩溃可丢一次游标推进，但不能抹去已提交预约。

`ProviderRecoveryRepository` 只有进程本地 owner registry，并保存有界 checkpoint snapshot，不是跨进程 lease 或 compare-and-swap scheduler。runtime-recovery 计划假设每数据库一个合法 owner，要求旧进程退出后再启动。承诺此条件下跨重启 floor 保留，不承诺并发手动启动进程间全局恰好一次探测。本片不增加 OS 锁、预约 schema、迁移或跨进程互斥承诺。controller 的 worker-start floor 也不是与最终内部 SDK 入场原子的数据库事务。

## UPD-11 — 有序实现薄片与文件归属

下列是后续分工提案，不授权现在编辑。源码交接串行进行：当前股票分钟 writer 持有 `runtime/production.py`；A07 F1 持有 `runtime/service.py` 和 `runtime/explicit_service.py`。等待释放并复核接口变化。两个 provider 文件只由指定 provider writer 修改，SDK 边界不得并发编辑。

| 薄片 | 文件与依赖 | 验收检查点 |
|---|---|---|
| UPD-S1 | `market_data/tushare.py`、`market_index/tushare.py`、定向 provider boundary 测试；provider 交接后 | Calendar/history 最终 hook RED→GREEN，普通无 hook 兼容；不启用 owner/scheduler |
| UPD-S2 | `runtime/production.py`、calendar 和两个 index-owner 测试；S1 及 production 交接后 | 共享持锁函数体、原 anchor/cancel guard、全局选择/ack、封闭错误矩阵；仅直接内部调用 |
| UPD-S3 | `runtime/production.py`、candidate selection/rotation 及新 unified-dispatch 集成测试；S2 和 SMWO execution 验收后 | 一个八 scope 共用 unit、纯 getter、全部无候选固定检查、保留 O/F/symbol 公平性；不再有 calendar 内联旁路 |
| UPD-S4 | `runtime/scheduler.py`、`runtime/service.py`、`web/monitor_composition.py`、定向 runtime/scheduler 测试；S3 及 F1 交接后 | RUNNING 真实 composition、行情优先、两个游标位置共用 maintenance 分类；不实现 A07 F3 |
| UPD-S5 | `runtime/service.py`、`web/monitor_composition.py`、定向 dual-clock 和 lifecycle 测试；S4 后 | DEGRADED 双时钟、pipeline/状态保留、同 generation 恢复及 stop/drain；无业务权限捷径 |

每片运行定向 RED→GREEN 及相邻回归；S2/S3 后独立评审变更的权限/时钟边界，S5 后独立验收连接的 RUNNING/DEGRADED 场景。不能重复未变 proof 矩阵来替代新 scheduler 测试。薄片若超出有界可审范围，串行拆分测试/实现，不启用接线不完整的默认路径。单个 helper 或本契约获批均不能关闭 C1。

## UPD-12 — 精确 RED 验收门槛

| ID | 必需离线失败用例及最终验收 |
|---|---|
| UPD-R01 | 八个 scope 均阻断且 raw due 相同，真实共用 dispatcher 每 unit 只预约/探测一个，覆盖全部合格 scope 且只解除所选阻断。不同 raw 日期与共享 429 必须保留 raw 排序。 |
| UPD-R02 | due 前后重复调用 `next_permission_probe_due_at` 及调度适配层，零 SQL/文件 I/O/预约/SDK/游标写入。单独证明 `permission_probe_candidates` 和 `select_due_permission_probe` 保留有界新鲜证据/权限读取，且零预约/SDK/游标写入；不对其施加 timing getter 的零 I/O 限制。缺 consumer、缺 anchor、scope 权限暂缺分别由实际维护形成固定 30 秒复查，不滑动、不忙循环。 |
| UPD-R03 | 首分钟/会话 earliest start、休市/未知日、午夜重新准备保留既有 scope 规则。缺 consumer/anchor 即使其他 scope 前进也零预约。 |
| UPD-R04 | 真实 controller save 失败不推进游标；commit 后 queue veto 只推进一次；合并 waiter 与 worker-start 延伸不重复确认。其他 scope 预约不破坏 O/F 及两个 symbol 游标。 |
| UPD-R05 | 按名称入口与共用入口并发时串行，无死锁、无旧预计算 callback 覆盖；未获全局选择的命名 scope 不能绕仲裁。每 unit 最多一次预约和一次物理调用。DAILY_BARS 的 broad 提示 A 无需求、B 有有效 receipt：全局仲裁先选 scope/rank，恰好一次新鲜准备选定并冻结 B，执行使用同一候选/receipt。断言一次准备、最多一页历史和最多 10 次 receipt 点查，禁止先 prepare-to-select 再 prepare-to-execute 的重复准备或捕获后替换。 |
| UPD-R06 | 真实 calendar/历史指数 provider 加认证 wrapper：adapter 进入后 wrapper/resolver I/O 耗时或撤销权限，最终 hook 拒绝，内部 SDK 零调用。测试合法入场、相等/迟到启动、同一 sentinel、无私有 kwargs、无 worker SQL、普通无 hook 行为。 |
| UPD-R07 | calendar 休市日证明仍合法；原 calendar/historical anchor 改变而另一个合法日期仍存在时，不替换/解除。交错 epoch 修正、calendar 写失败及新 Event 安装不能复活旧调用权限。 |
| UPD-R08 | 普通 calendar 请求即使权限阻断已到期，也不内联复查；仅后续全局所选 maintenance unit 探测。startup 失败不能在自身时钟外隐式探测。 |
| UPD-R09 | 真实 RUNNING composition 同刻先行情；准备时安全的权限调用排队进入 31.25 秒预留时，真实 SDK 入场拒绝且保留预约。权限工作不能把自身 running flag 当作行情工作。 |
| UPD-R10 | maintenance 完成跨行情 deadline，原游标及 elapsed-review 起点均保留；仅一项原目标可在真实年龄 0..90 秒内执行，无过时/多项回放。权限分支自身不接投递或求值。 |
| UPD-R11 | DEGRADED startup attempt 从各次完成时刻按 30/60/120/300 秒递进，更晚 controller floor 可延长。期限前多次权限唤醒/成功/失败均不重置 attempt、不提前或滑动延后期限。 |
| UPD-R12 | degraded 两时钟均到期，先一次 startup；正常失败后在再次等待前给一个合格权限 unit，无饥饿。权限超时越过期限最多产生一次已到期 startup attempt，无并行物理调用或回放。 |
| UPD-R13 | 同 generation startup 失败重查复用合法 pipeline，保留 fixed defer/global/O-F/symbol 游标。缺 pipeline 仅等 startup；首次合法创建不复活旧捕获。已撤销 baseline 保持 NEEDS_RESTART。 |
| UPD-R14 | 真实 DEGRADED 绑定允许合法只读证明，不改变 `_accepting_work`、业务行或 runtime generation。证明成功本身仍 DEGRADED，后续到期完整 startup 成功恢复既有调度，无 supervisor 换代。 |
| UPD-R15 | 每类 owner 覆盖 UPD-09 所有错误分类：预期失败保持 scoped，严重 controller/storage/callback/programming 错误交 owner。不能宽泛捕获而掩盖 `ERROR`、`CLOSED` 或 `QUEUE_FULL`。 |
| UPD-R16 | queue/entry 前取消、外层 catch 前已请求取消、SDK 内取消后晚成功均不解除阻断；drain 前无第二物理调用/DB 释放。两模式中的 stop/cleanup/liveness/configuration 撤销均终止维护。 |
| UPD-R17 | 串行独立进程重开临时 SQLite 保留 permission/429 floor；floor 前零预约，等于 floor 仅允许其他条件合法的尝试；游标重置不改变存储时间。不把同时运行进程模拟成受支持情形。 |
| UPD-R18 | calendar、两个指数 endpoint、三个 daily scope 和两个股票分钟 scope 均通过真实 RUNNING/DEGRADED wake 正向前进，而非直接私有调用；断言物理次数、仅本 scope 解除、同 generation 及权限路径零业务写入。 |

保留 `test_permission_candidate_selection.py`、`test_permission_candidate_rotation.py`、`test_permission_reservation_ack.py`、既有 scope-owner/proof 套件、`test_runtime_lifecycle.py`、`test_production_a06_process_scheduler.py` 及定向 A07 cursor/freshness/stop 相邻回归。使用 fixture 合法的真实本地 ownership，不能绕过 liveness 或伪造 health。命令/结果记入后续双语验证证据，作者与独立运行分开；本提案未运行这些测试。

## UPD-13 — 评审问题与完成边界

未识别新的用户业务选择：阈值、交易规则、证明语义和重启政策均沿用既有决定。独立 Sol 评审须检查持锁 dispatch/refactor 边界、无候选不滑动期限、startup-first 同刻公平性、未放宽 DEGRADED 准入绑定、两个真实 SDK 接口及两个维护游标位置。工作树变化可能要求实施前重新核对接口，不能降低验收标准。

本提案获批仅代表设计批准。实现验收需要全部八条连接路径、双时钟进展及上述失败/stop/restart 门槛。完整 runtime recovery、A07、真实供应商验收、live migration 和部署仍分别跟踪；不新增后台 owner 或通用恢复时限保证。

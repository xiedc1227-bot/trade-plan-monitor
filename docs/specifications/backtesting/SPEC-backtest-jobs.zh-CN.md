# 规格：backtest-jobs

> 中文审阅版。英文权威版为 `SPEC-backtest-jobs.md`；两份文档必须保持语义一致。

## 目标

通过一个持久化本地 worker 槽异步运行 `DATA_SYNC`、`DATASET_VERIFY` 和 `BACKTEST_RUN`，提供持久化进度、原子幂等、协作取消、基于 lease 的崩溃恢复，并且不在 HTTP 请求处理器内执行阻塞工作。

## 关系与范围

`backtest-jobs` 编排 `backtest-data`、`backtest-engine` 和 `backtest-results`。它负责持久化操作 identity、worker claim generation、队列准入、worker 所有权、进度、取消、恢复、终态诊断和结果/任务原子发布。它不负责供应商映射、策略/成交公式、规范已完成结果、HTTP Schema、Vue 状态、实时监控或通知。

任务与结果记录共享 `backtest-results.sqlite3`，但使用自己的表和前缀；不增加第三个回测数据库。首版只有一个进程内协调器和一个持久化执行槽。同步供应商/回放工作与 operation 线程进度持久化在一个专用有界 `ThreadPoolExecutor(max_workers=1)` 中执行；面向事件循环、可能阻塞的 SQLite 协调调用则在协调器拥有的第二个 `ThreadPoolExecutor(max_workers=1)` 中执行。两者都不是默认 executor，也不会嵌套另一个 executor；仓储 executor 不得把持久化操作并发提升到一以上。子进程、分布式 worker、逻辑自动重试和持久化操作并发大于一都不在首版范围。

## 命令

首版不公开新的直接 worker 命令。生产 FastAPI lifespan 启停一个明确注入的协调器及其拥有的两个 executor。协调、轮询、lease 恢复和 heartbeat 决策保留在事件循环；对应面向事件循环的同步 SQLite 调用只在自有仓储 executor 中运行，operation 进度从 operation executor 持久化，执行接收跨线程安全取消 Token。关闭时停止新 claim、请求取消、关闭排队 Future，并在有界供应商/SQLite/安全边界契约后释放两个 executor；后台 Task 失败时也必须释放。禁止 `asyncio.to_thread`、默认 executor 和未跟踪请求 Task。移除回测 CLI 适配器及命令专用的独立协调器；Web/API lifespan 负责执行任务。共用维护事务保留为内部领域能力；本次移除不新增自动清理调度器或替代的公开命令。

## 任务模型

任务类型是 `DATA_SYNC`、`DATASET_VERIFY` 和 `BACKTEST_RUN`。公开状态闭合为：

```text
QUEUED
RUNNING
CANCEL_REQUESTED
COMPLETED
FAILED
CANCELLED
```

合法迁移是 `QUEUED -> RUNNING`、`QUEUED -> CANCELLED`、`RUNNING -> CANCEL_REQUESTED`、`RUNNING -> COMPLETED`、`RUNNING -> FAILED` 和 `CANCEL_REQUESTED -> CANCELLED`。终态绝不迁移。已经 materialized 的相同运行可以直接插入一个 `COMPLETED` 且 reused 的 receipt，而不占用 worker 槽。

`job_id` 标识一次持久化提交/操作。`attempt=0` 表示任务尚未被 worker claim，包括排队、排队后取消和立即复用完成任务。首次 claim 设为 `attempt=1`；每次 lease 恢复递增且不改变 `job_id`，总共最多三个 claim generation。`run_id` 标识确定性已完成研究输出。重新提交终态失败/取消的 `BACKTEST_RUN` 会创建新的 `job_id`，但保留相同 `run_id`。

## 公共契约

`BacktestJobView` 包含 `jobId`、`kind`、`status`、`requestHash`、可选 `runId`/`datasetHash`、结构化 `phase`、`completedUnits`、可选 `totalUnits`、`attempt`、`revision`、`createdAt`、`startedAt`、`updatedAt`、`finishedAt`、`cancelRequestedAt`、`reused` 和脱敏 `errorCode`/`errorMessage`。每个持久化/公开的生命周期、授权、幂等、claim/lease、heartbeat 和截止日期时间都使用精确 `YYYY-MM-DDTHH:MM:SS.ffffff+08:00` 形式的带时区 `Asia/Shanghai` RFC 3339 文本；拒绝 `Z`、无偏移值、超精度和其他偏移。耗时调度可以使用注入的单调时钟，但不得把单调值作为墙上时间戳持久化或公开。

应用操作包括 `submit(request, idempotency_key)`、`get(job_id)`、`list(filters, limit, cursor)` 和 `request_cancel(job_id, idempotency_key)`。提交与取消在同一个 Unit of Work 中，把 key 原子绑定到其规范请求 hash 和规范响应，并同时完成资源/状态变更。新的公开运行 intent 解析还使用原子 `claim_run_submission`、可续租 `renew_run_submission`、generation-fenced finalize/release 以及同一个由任务拥有的维护事务。内部 worker 操作包括 `claim_next`、`heartbeat`、`update_progress`、`complete`、`fail`、`acknowledge_cancel`、`recover_expired` 和 `prune_jobs`。

规范请求 payload 最多 256 KiB，并且只包含类型化资源值。运行提交保存不可变已校验计划快照和规范化 `BacktestInitialLotInput`；绝不保存计划/报告/数据库路径。`DATA_SYNC` 请求把字面量 `allowNetwork: true` 持久化到规范请求 JSON 和 `requestHash`，并保存服务端生成的 `networkAuthorizedAt` 与提交 `requestId`。该授权只适用于此任务恢复；不持久化凭据，新任务必须重新明确授权。公开错误文本最多 512 个字符。Claim Token 和原始诊断上下文绝不公开。

## 幂等与准入

`Idempotency-Key` 使用 1–128 个白名单字符。提交在唯一约束下原子插入或重放；禁止先查询再插入。

- 相同 key 和相同规范请求哈希返回同一任务/receipt。
- 相同 key 和不同哈希以 `IDEMPOTENCY_CONFLICT` 失败，并且新增零个任务。
- 相同活动操作哈希返回现有活动操作。
- 不同 key 可以重新提交已完成同步/校验，以再次检查当前不可变 head。
- 相同已完成运行返回立即完成的 `reused=true` 任务并关联现有 materialized `run_id`，不执行回放。
- 失败/取消重试要求新 key 和 `job_id`；确定性校验/供应商失败绝不自动重试。

相同 key 的提交/取消重放保证在任务非终态期间持续有效，并在 `finishedAt` 后保留 14 天，与终态任务/幂等记录保留一致。即使后续 worker 进度改变当前任务表示，取消重放仍返回原始规范取消响应；客户端随后读取权威任务资源。过期后，该 key 可以表示新意图；确定性已完成运行复用仍会防止重复研究结果。

解析新的公开运行 intent 时，在唯一一次实时计划快照读取之前原子预留其 key。未解析预留使用可续租的 30 秒 lease，并由 owner 每 10 秒 heartbeat。其他请求可以观察并轮询预留，但不能仅因截止时间已过就删除或接管。过期未解析预留只能由任务拥有的维护事务在共享 `<=1,000` 行预算内删除；清理完成后，下一个请求才能 claim。Finalize 和 release 由原始 claim generation 隔离，因此一个新 intent 最多持久化一份不可变计划快照并创建一个任务。

最多允许 100 个 `QUEUED` 任务。超过该边界的准入以稳定队列已满条件失败。任何时刻 `RUNNING` 加 `CANCEL_REQUESTED` 的任务数量最多为一个。

## Worker Lease 与恢复

单一活动槽由原子数据库 claim 和不透明 Claim Token 保护。Lease 时长 30 秒；活动 worker 至少每 10 秒 heartbeat。过期 claim 不能更新进度、完成、取消或发布结果。除阶段和终态迁移外，进度最多每秒持久化一次；同一 attempt 内必须单调，只能在 `attempt` 增加时重置。

过期 `RUNNING` claim 在 `attempt < 3` 时以新 Token 重新认领并使 `attempt + 1`；在 `attempt=3` 时过期则以 `WORKER_RECOVERY_EXHAUSTED` 进入 `FAILED`。过期 `CANCEL_REQUESTED` 任务变为 `CANCELLED`。恢复同步只在已持久化 `allowNetwork: true` 授权仍存在时通过不可变 head 去重复用进度；校验可以复用已发布数据集，策略回放从冻结起点重跑。策略事件游标继续延后。

## 取消与发布竞态

排队任务取消在一个事务中变为 `CANCELLED`。运行任务取消立即变为 `CANCEL_REQUESTED`，并继续占用活动槽，直到 worker 确认或 lease 恢复。

同步观察到取消后不得启动新的供应商调用；一项已在途且校验通过的响应可以作为可复用缓存提交。校验在股票交易日批次之间和 manifest 发布前检查。回放在一个逻辑分钟迭代内及结果交付前检查。取消绝不暴露部分运行结果。

对于 `BACKTEST_RUN`，`backtest-jobs` 负责共享 Unit of Work。完成事务校验状态为 `RUNNING` 且 Claim Token 仍有效，消费有界 `backtest-results` 发布参与者，在同一个 `backtest-results.sqlite3` `BEGIN IMMEDIATE` 事务中设置 `materialized=1`、把任务标为 `COMPLETED` 并释放活动槽。如果取消先提交，发布被拒绝且任务最终为 `CANCELLED`；如果发布先提交，取消会观察到 `COMPLETED` 并保持不变。

## 安全与可观测性

信任边界包括浏览器/API 请求、已持久化规范请求 JSON、Worker Claim Token、供应商/引擎失败和进程重启。需要保护的资产包括本地可用性、不可变结果 identity、供应商凭据、计划内容和实时零副作用保证。

- 只持久化运行所需的有界规范结构化计划快照；任务中绝不持久化自然语言原文或提取证据。绝不记录密钥、供应商响应、堆栈、SQL、客户端提供的数据库路径、计划内容或 Claim Token。
- 把持久化 `allowNetwork: true` 视为任务限定的已审计授权事实。执行时只从当前服务端配置解析凭据；取消/终态绝不把授权转移给重新提交。
- 使用参数化 SQL、唯一约束、revision/claim 校验和稳定脱敏错误代码。
- 结构化事件覆盖提交、重放、claim、阶段/进度、heartbeat 丢失、取消、恢复、完成、失败和清理；每个事件携带有界 `requestId`、`jobId` 和可选 `runId` 关联。
- 运维健康暴露队列深度、活动类型/阶段、最老排队年龄、恢复次数和最近一次脱敏失败。指标标签绝不包含 job/run/request ID。

值守人员要回答的问题是：正在运行什么、已经多久？任务为何阻断/失败？取消是否先于发布生效？重启恢复是否重复了供应商事实或结果行？

## 性能预算

- 精确一个活动执行槽，最多 100 个排队任务。
- 任务 payload 最多 256 KiB；除阶段/终态迁移外，进度最多每秒写一次。
- 公开列表页面大小为 `1..100`；任务请求/诊断元数据保留 14 天。
- 本模块负责唯一维护 Unit of Work，在一个协调预算内最多删除 1,000 条符合条件的任务/stage/详情行，并只把剩余预算传给 `backtest-results`。
- HTTP 提交/状态/取消不执行供应商调用或回放，并在持久化事务完成后返回。
- 实施时记录队列年龄、claim 延迟、任务耗时、worker 峰值内存、数据库/WAL 增长和取消延迟；但在获批实施计划明确夹具规模、机器/节流条件、样本数和数值通过上限前，这些记录不能关闭 `BC01`。

## 项目结构

任务值、Repository、协调器、专用单线程 executor、跨线程取消 Token、维护 Unit of Work 和生命周期组合放在 `src/trade_plan_monitor/backtest/`；如果获批实施计划证明合理，可以使用聚焦的 `backtest/jobs/` 子包。任务可以依赖结果事务/清理参与者；结果不能反向导入协调器。FastAPI Router 继续只是 `src/trade_plan_monitor/web/` 下的适配器；模块导入时不得启动线程或打开 SQLite。

## 代码风格

使用冻结严格请求/视图值、显式迁移函数、参数化 SQL、短 `BEGIN IMMEDIATE` 事务、单调进度校验、注入时钟/worker 函数、结构化稳定错误代码和穷尽式状态/类型处理。不要为一个本地槽引入通用队列、事件总线或分布式抽象。

## 测试策略

使用确定性假操作和时钟。覆盖二十个并发相同提交、key/payload 冲突及 14 天过期、规范 `Asia/Shanghai`/`+08:00` 生命周期/截止时间持久化及拒绝其他日期时间形式、活动操作去重、`attempt=0` 排队/复用任务、两个 worker 对象之间总共三个 claim generation、过期 Token 隔离、单调进度、排队/运行取消、取消/发布事务两个顺序、队列容量、每个安全边界后的重启、持久化同步授权/零凭据/重新提交再授权、零重复事实/manifest/成交/详情、复用已完成运行、失败/取消后使用同一 `run_id` 重跑、可续租运行 intent 预留隔离及在唯一 1,000 行维护预算内清理孤儿、成功/超时/后台失败后三种情况下两个专用 executor/lifespan 清理、阻塞同步假操作不阻塞 HTTP 轮询/heartbeat，以及请求处理器零回放/供应商工作。

## 边界

- 始终：确认提交前持久化、原子 claim/状态迁移、隔离过期 worker，并在模块安全边界检查取消。
- 始终：保持一个槽、一个结果数据库、类型化有界 payload，以及实时状态/通知零副作用。
- 先询问：更改并发、30 秒 lease、10 秒 heartbeat、总共三个 claim generation、100 任务队列、14 天保留/幂等窗口，或增加逻辑重试、子进程、分布式 worker、实时状态访问。
- 禁止：在 HTTP 处理器/事件循环/默认 executor 中运行任务、为每个请求生成未跟踪 Task、允许两个活动任务、让过期 worker 发布、暴露 Claim Token/密钥/路径、跨任务继承联网授权，或把取消当成已完成研究结果。

## 验收标准

- 二十个并发相同提交只创建一个任务且只执行一次。
- 两个 worker 只产生一个有效活动 claim；过期 Token 成功写入次数为零。
- 始终满足 `RUNNING + CANCEL_REQUESTED <= 1`。
- 取消/发布竞态只产生一个终态，且部分结果可见数为零。
- 崩溃恢复不产生重复供应商事实、数据集、成交或详情。
- 取消/失败运行之后使用同一 `run_id` 和新 `job_id` 完成。
- 提交、轮询和取消绝不在请求处理器内执行供应商/回放工作。
- 每个持久化/公开任务日期时间都使用 `Asia/Shanghai`/`+08:00`；lease/heartbeat 耗时行为保持精确且不依赖主机时区。
- 实时数据库状态和通知计数保持精确不变。

## 已确认的首版决策

已确认的首版决策是：`DATASET_VERIFY` 继续异步；使用一个进程内协调器、一个单线程操作 executor、一个单线程仓储 executor 和一个持久化操作槽；总共最多允许三个 worker claim generation；策略回放从冻结起点恢复。子进程隔离、事件游标恢复和逻辑自动重试继续延后。

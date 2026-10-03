# ADR 0001：隔离持久化回测任务与确定性结果

> 中文审阅版。英文权威版为 `0001-isolate-backtest-jobs-from-results.md`；两份文档必须保持语义一致。

- 状态：`Accepted`
- 日期：`2026-08-26`
- 项目：`backtest`
- 模块：`backtest-engine`、`backtest-results`、`backtest-jobs`、`backtest-api`、`backtest-web`

## 背景

历史同步、数据集校验和多日回放可能超过一个 HTTP 请求的生命周期，并且必须在本地进程重启后恢复。同时，同一研究输入无论被提交、取消、中断或重试多少次，都必须保留唯一的确定性 identity。

项目已经把 `backtest-market.sqlite3`、`backtest-results.sqlite3` 和实时监控数据库相互隔离。增加第三个队列数据库，或把失败尝试当成不可变研究结果，都会增加协调风险，并可能阻止被取消的确定性输入以后成功完成。

## 决策

1. `backtest-engine` 负责精确版本化 `run_id` preimage。空的规范化初始持仓列表保留逐字节相同的 `backtest-run-v1` preimage；非空公共初始持仓列表选择 `backtest-run-v2`，并使用带稳定 `lotKey` 的规范化 `BacktestInitialLotInput` 值。`planVersionId` 是查找/审计元数据，不参与任一 identity。
2. `job_id` 标识一次持久化提交操作。`attempt` 标识同一任务内的一次 worker claim generation，并在 lease 恢复时递增而不改变 `job_id`。重新提交终态失败或取消任务会创建新的 `job_id`；研究输入不变时继续保留同一个 `run_id`。
3. 新的 `backtest_run` 写入路径只发布 materialized 的 `COMPLETED` 结果。失败和取消尝试保留为有界诊断任务记录，且不占用 `run_id`。
4. 持久化任务记录保存在 `backtest-results.sqlite3`，不增加第三个数据库。一个本地协调器在 `DATA_SYNC`、`DATASET_VERIFY` 和 `BACKTEST_RUN` 之间只拥有一个活动执行槽。阻塞的供应商、SQLite 和回放工作只能在专用有界 `ThreadPoolExecutor(max_workers=1)` 中运行，绝不能进入事件循环或默认 executor；协调、轮询、lease 恢复和 heartbeat 保留在事件循环。
5. `backtest-jobs` 负责共享结果数据库 Unit of Work。它校验当前任务 claim，并调用有界 `backtest-results` 事务参与者；`backtest-results` 绝不反向导入任务协调器。结果 materialization、所属 `BACKTEST_RUN` 任务转换为 `COMPLETED` 及活动槽释放必须在同一个短结果数据库事务中原子完成。行情缓存进度继续独立幂等；不存在跨数据库事务。
6. `backtest-jobs` 还负责唯一生产维护 Unit of Work，以及 job、stage 和结果详情行共享的一个 `batchSize <= 1000` 总清理预算。它只把剩余预算传给 `backtest-results` 参与者；后者绝不清理任务行，也不启动另一份预算。
7. Web 运行提交可以在一个只读实时存储事务中读取恰好一个不可变计划版本。系统会校验并在响应前持久化规范计划快照，对实时存储执行零写入，并且 durable 边界之后的 worker/回放不具备实时存储读写能力。直接 CLI 运行接收显式 `--plan` 文件。
8. 其他 HTTP handler 只校验并入队。首个 Web 版本通过有界 REST 轮询观察持久化任务状态，不增加回测 WebSocket 事件。
9. `DATA_SYNC` 请求把字面量 `allowNetwork: true` 持久化到规范请求和 `requestHash` 中，并保存服务端生成的 `networkAuthorizedAt` 与 `requestId`，作为任务限定的已审计授权事实。执行时只从当前服务端配置解析凭据，绝不持久化凭据；新任务需要重新明确授权。
10. 持久化请求只包含规范资源 identity 和已校验计划快照，绝不包含凭据、任意文件路径、原始供应商响应、堆栈或 worker claim token。
11. 启用仅完成结果发布前，迁移 preflight 要求旧 `backtest_run` 中 `FAILED` 或 `CANCELLED` 行数为零。任何非零数量都会在 Schema 变更前以 `LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION` 失败关闭；转换为任务诊断需要另行批准离线迁移。
12. 崩溃恢复从冻结数据起点重新回放不可变输入，并依靠内容寻址/幂等写入。策略事件游标恢复继续作为延后验收工作。

## 已考虑的替代方案

### 在 CLI 或 HTTP 请求内执行

Web 路径拒绝此方案，因为跨请求生命周期无法保证取消、重启恢复、有界并发和可靠进度。CLI 继续作为相同领域能力的兼容适配器。

### 使用 `run_id` 作为任务 identity

拒绝此方案，因为失败或取消任务要么阻止以后成功重新提交，要么要求修改不可变结果 identity。

### 增加第三个队列数据库

拒绝此方案，因为任务/结果发布会增加另一个协调边界，却不能改善单主机首个版本。

### 复用监控 WebSocket

首个版本拒绝此方案，因为 REST 轮询可以在刷新或休眠后恢复权威状态，无需扩展实时监控事件契约。以后可单独提出事件提示。

### 现在支持投资组合/共享现金回放

首个版本拒绝此方案。一次运行继续表示一个经审核计划版本和一只股票；一个数据集仍可缓存 1–10 只股票的事实。

## 后果

- 取消和运维失败与有效研究输出保持可区分。
- 同一确定性输入可以在失败、取消或 claim 回收后完成，而不重复产生结果。
- 一个执行槽以吞吐量换取可预测的本地资源使用；投资组合和分布式 worker 需要新的决策。
- 专用 `ThreadPoolExecutor(max_workers=1)` 使阻塞工作不进入 HTTP 轮询和 heartbeat 路径，同时让生命周期关闭成为明确责任。
- API 与 Vue 契约必须分别暴露任务状态和已完成结果可用性。
- 恢复可能重复确定性 CPU 工作，但不依赖尚未实现的事件游标，也不得重复供应商事实、成交或详情。
- 现有可读取的 `BacktestRunStatus.FAILED` 与 `BacktestRunStatus.CANCELLED` 保留为仅兼容值，不属于新的写入路径；包含此类行的数据库未经批准迁移不能采用仅完成结果发布。
- 任务限定的联网授权可以跨进程恢复，而无需保存或转移凭据。

## 安全与运维影响

任务边界是不可信命令边界。提交使用有界类型输入、幂等 claim、固定脱敏错误、持久化的任务限定同步联网授权和依赖注入服务。计划解析事务只读；durable 提交后 worker 不能访问实时状态、通知、券商或调用方提供的数据库路径。绝不持久化凭据。日志和指标使用有界 identity，绝不暴露密钥或原始供应商内容。

## 回退与迁移

实现前若否决，只需修订拟议规格和本 ADR。仅完成结果迁移必须先通过旧终态零行闸门；`LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION` 会阻止 Schema 变更，直至另行批准离线转换。实现后若改变 `backtest-run-v1`/`backtest-run-v2` preimage、并发、存储位置、传输或结果状态语义，必须新增替代 ADR，并提供迁移以保留现有 `run_id`、导出、已保留结果和任务审计记录。回滚可以停止 worker 并隐藏新 API/Web 入口，但不能删除不可变行情数据或已完成结果。

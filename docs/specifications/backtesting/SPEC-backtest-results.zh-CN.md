# 规格：backtest-results

> 中文审阅版。英文权威版为 `SPEC-backtest-results.md`；两份文档必须保持语义一致。

## 目标

把不可变的已完成研究结果持久化到 `backtest-results.sqlite3`，只暴露已验证的 materialized 记录，长期保留摘要和模拟成交，有界保留诊断详情，并提供完整性校验的分页、导出、置顶、保留和重建。

## 关系与范围

`backtest-results` 消费 `backtest-engine` 的规范输出。它负责已完成运行输入/结果、materialized 运行使用的计划快照、发布完整性、查询投影、导出、可变置顶元数据和有界保留。它不负责历史 K 线、供应商调用、回放、任务执行、HTTP 路由、Vue、实时持仓或通知。

`run_id` 是确定性研究输出 identity；`job_id` 是一次持久化提交操作，任务的 `attempt` 统计 worker claim generation。新写入只持久化完整 materialized 运行。失败和取消任务属于 `backtest-jobs`，因此之后的任务仍可完成同一个 `run_id`。现有 `BacktestRunStatus.FAILED` 和 `BacktestRunStatus.CANCELLED` 继续作为旧序列化数据的代码级兼容值；首个任务 Schema 迁移必须证明没有此类数据库行占用 `run_id`，新数据库写入路径也不能创建此类行。

## 命令

保留 CLI 兼容界面：

```powershell
python -m trade_plan_monitor backtest list --limit 20 --offset 0
python -m trade_plan_monitor backtest prune --batch-size 1000
```

CLI 文件继续是本地投影。Web 导出通过 `backtest-api` 流式返回已验证内容，绝不暴露本地报告路径。

## 公共契约

保留 `BacktestRunSummary`、`BacktestFillRecord`、`BacktestDetailRecord`、`BacktestDetailKind`、`BacktestResultStatistics`、`RetentionPruneResult`、规范集合哈希、报告持久化、摘要 JSON 和成交 CSV 投影。

提供有界应用契约：

- `get_run(run_id)` 返回一个 materialized 运行或 `NOT_FOUND`；
- `list_runs(filters, limit, cursor)` 使用 `1..100` 的 `limit` 和不透明有界 cursor；
- `list_fills(run_id, limit, cursor)` 按 `(filledAt, fillId)` 排序；
- `list_details(run_id, kind, limit, cursor)` 按 `(eventAt, detailId)` 排序，并要求声明公开详情类型；
- `get_equity_series(run_id)` 返回最多 2,000 个有序每日点；
- `set_pinned(run_id, pinned, expected_revision, idempotency_key)` 参与应用 Unit of Work，并且只修改可变保留元数据；
- `iter_export_summary(run_id, cancelled)` 和 `iter_export_fills(run_id, cancelled)` 通过有界增量迭代重建稳定且经过验证的投影，无需重放，也绝不在内存中构造完整导出；
- `prune_result_rows(as_of, remaining_budget)` 是内部维护参与者，只删除符合条件的结果 stage/detail 行并报告精确预算使用；`backtest-jobs` 负责唯一生产 `prune(as_of, batchSize <= 1000)` Unit of Work，并在 job/stage/detail 行之间共享预算。

页面暴露 `items`、`limit`、`nextCursor` 和 `hasMore`。公开详情和权益可用性明确为 `AVAILABLE`、`EXPIRED` 或 `NOT_RECORDED`。不可变发布账本按详情 kind 保存原始计数，并保存原始权益点数量。可变保留元数据在删除物理行前原子记录每个 kind/权益序列的过期标记：原始计数为零表示 `NOT_RECORDED`；正数且没有过期标记表示 `AVAILABLE`；存在标记表示 `EXPIRED`，即使有界物理清理仍在继续。首个 Web 版本不公开 `DEBUG_TRACE`。

## 存储与发布契约

`backtest-results.sqlite3` 负责已完成运行使用的去重规范计划快照、不可变运行输入/假设、materialized 摘要、成交、有界详情、发布元数据、导出重建事实、置顶 revision 和保留元数据。它引用 `dataset_hash`，绝不复制行情 K 线。

发布会按规范内容哈希幂等 staged 摘要、成交和详情行。每次 stage 变更都原子递增 `stageRevision`；普通 list/get/fill/detail/statistics/export 读取看不到 staged 数据。随后用稳定 WAL 读快照一次最多扫描 1,000 个 staged 行，在不占用写者且不使用 `fetchall` 的情况下重新校验每个 SQL identity/payload 哈希，并计算精确规范 `(identity, contentHash)` 集合哈希。关闭快照后，短 `BEGIN IMMEDIATE` 事务重新检查未变化的 `stageRevision`、预期/已存行数和集合哈希。详情类型过滤只能在完整性校验后应用，不能隐藏损坏行。

同一发布校验会从已持久化规范计划快照重新计算 `plan_sha256`，从已持久化 `BacktestRunInput` 派生精确版本化 `run_id`，并匹配报告公式版本、计划哈希/版本/股票、`dataset_hash`、日期范围、初始状态和假设。只用于查找的 `planVersionId` 不能替代此内容校验。

对于 `BACKTEST_RUN` 任务，`backtest-jobs` 负责共享结果数据库 Unit of Work。完成全部有界结果校验后，它校验当前任务状态/claim、调用 `backtest-results` 事务参与者、设置 `materialized=1`、把任务迁移为 `COMPLETED` 并在同一个短事务中释放执行槽。`backtest-results` 绝不反向导入任务模块。如果取消先提交，发布失败且不会暴露部分运行；如果发布先提交，后续取消会观察到已完成终态。

启用仅完成任务发布前，迁移 preflight 会统计旧数据库中 status 为 `FAILED` 或 `CANCELLED` 的 `backtest_run` 行。当前本地尚未提交基线的预期数量为零。任何非零数量都会在 Schema 变更前以 `LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION` 中止迁移；绝不覆盖或静默删除，并且必须另行批准离线导出/转换为任务诊断。只有零行断言通过后才安装仅完成约束。

缺少规范计划快照或 `BacktestRunInput` 的旧 `COMPLETED` 行继续可以通过兼容投影读取和导出，但不能被新任务路径作为已验证的完成运行复用。匹配的新提交会以经过脱敏的冲突封闭失败，直到另行批准的采纳迁移提供可独立验证的输入；实现绝不猜测、重写或删除旧行。

本地尚未提交的 MVP 还写入了 UTC 规范化的 `backtest-run-summary-v1`、`backtest-fill-record-v1`、`backtest-detail-record-v1`、内容集合、摘要 JSON 和成交 CSV 投影。即使其计划/运行输入在其他方面已知，这些 v1 字节仍保持为不可变兼容 artifact。活动中国时间路径写入新的显式 v2 结果/内容集合 Domain，以及 `backtest-report-summary-v2` 和 `backtest-simulated-fills-v2` 导出。它保留现有 `run_id`、`dataset_hash` 和 `backtest-report-v1` 语义 identity，但在另行批准的采纳迁移校验并记录 v2 内容前，绝不通过新 API 发布或复用 UTC v1 投影。

置顶状态和置顶 revision 位于规范摘要/报告 identity 之外。修改置顶的操作必须幂等、要求 `expectedRevision`，并在应用负责的 14 天置顶幂等窗口内原子记录规范请求/响应。

## 结果与导出契约

已完成摘要暴露闭合类型化覆盖、假设、公式版本、最终指标、成本、限制 Token、计划/数据集/运行 identity、时间戳和计数。每个活动持久化、查询、绑定 Cursor、发布和导出的日期时间都是精确采用 `YYYY-MM-DDTHH:MM:SS.ffffff+08:00` 形式的规范带时区 `Asia/Shanghai` RFC 3339 文本；持久化/发布前拒绝 `Z`、无偏移值、超过 6 位小数秒和其他偏移。任意 `dict[str, object]` payload 绝不作为公开 API 契约。

有界详情过期后，原始完整 `reportHash` 继续作为审计 identity。稳定的活动 `backtest-report-summary-v2` JSON 和 `backtest-simulated-fills-v2` CSV 可以根据已验证长期 v2 摘要/成交行增量重建，无需访问供应商、策略重放、新增数据库行或完整内存导出。不可变 UTC 规范化 v1 artifact 只能通过明确标识的离线兼容工具访问，绝不静默作为活动导出版本发出。迭代器使用有界读取，在批次之间观察调用方取消，并由 `backtest-api` 发出不超过 64 KiB 的块。已过期的判断、信号、outcome 和权益详情继续过期，不能重建。导出绝不包含数据库/报告路径、实时状态、凭据或原始供应商响应。

## 保留契约

| 记录类别 | 默认保留 |
|---|---|
| materialized 运行摘要、规范输入哈希/快照、假设、最终指标和成交账本 | 长期 |
| 成功判断/信号/outcome/每日权益详情 | 最新 100 次运行且最多 90 天；先达到哪个边界就执行哪个 |
| 失败/取消任务诊断和明确启用的 debug trace | 14 天 |
| 废弃的未 materialized、未置顶 staged 摘要/成交/详情 | 14 天 |
| 置顶运行详情 | 取消置顶前豁免 |
| 被保留运行引用的数据集/行情修订 | 由 `backtest-data` 保留 |

清理必须带索引且有界。`backtest-jobs` 提供一个最多 1,000 行的总预算，并以单向依赖调用结果清理；结果模块不能开始第二个预算或清理任务行。监控或回测活动期间绝不运行大型 `VACUUM`。WAL checkpoint 只在安全/静止边界被动执行；`VACUUM` 继续是显式离线维护操作。

## 安全与可观测性

信任边界包括规范引擎输出、磁盘 staged 内容、API 查询过滤/cursor、置顶命令和导出请求。所有 SQL 必须参数化；cursor 是限长、带签名或完整性保护的不透明值，并绑定已声明排序。

结构化事件覆盖 stage 开始、stage 冲突、materialization、重建、置顶变更、清理、损坏阻断和失败。字段使用白名单并由 `jobId`/`runId` 关联；不得记录完整计划文档、初始持仓 payload、SQL、路径、密钥、原始异常或报告正文。损坏属于 error 级不变量破坏；正常过期不是错误。

## 性能预算

- 公开页面大小为 `1..100`；任何 Web 读取都不能返回无界运行/成交/详情集合。
- 权益保存每日而非分钟账户点，最多 2,000 个点。
- Stage 写入、发布校验读取和一次协调 prune 调用每批/每预算最多处理 1,000 行。
- 查询使用与稳定运行完成、成交 `(run_id, filled_at, fill_id)`、详情 `(run_id, kind, event_at, detail_id)` 和保留排序相匹配的索引。
- 最大页面 JSON 必须低于共享 4 MiB 响应边界。
- 每个 materialized 公开 item（包括完整 `BacktestDecisionView`）都在发布前序列化；超过 32 KiB 时拒绝发布，绝不截断已参与哈希的证据。
- 在固定多日夹具上验收 p50/p95 查询耗时、峰值内存、数据库/WAL 增长和重复运行行增长，再考虑优化。

## 项目结构

结果值、存储、发布参与者、保留、完整性检查和报告投影保留在 `src/trade_plan_monitor/backtest/`。任务 Unit of Work 可以调用结果事务参与者，但本模块绝不导入任务协调器。HTTP Schema 和流式响应属于 `backtest-api`；Vue 格式化属于 `backtest-web`。生成报告目录是运行时产物，继续排除在 Git 外。

## 代码风格

使用冻结严格值、精确规范 JSON、显式 Schema 版本、参数化 SQL、不可变内容行、确定性排序、不透明有界 cursor、类型化可判别详情变体和短事务。可变元数据必须与哈希内容明确分离。

## 测试策略

覆盖 staged 不可见、1,000 行读快照校验与短写事务 revision 隔离、精确数量/集合哈希发布、从持久化输入重新计算 v1/v2 `run_id`、计划/数据集/范围不匹配、规范 `Asia/Shanghai`/`+08:00` 持久化/查询/导出往返及拒绝其他日期时间形式、不可变 UTC v1 兼容夹具及已验证 v2 采纳冲突、相同持久化无操作、冲突内容、任务完成/取消竞态两个顺序、损坏 SQL identity/payload、植入旧终态行时迁移拒绝、运行限定详情 identity、静态集合上的 cursor 分页无重复/缺口、置顶 revision 冲突、原始计数/过期可用性及部分物理清理、全部保留类别、唯一共享 prune 预算、重开/WAL、逐字节稳定版本化导出、无需重放的重建、已过期详情不可重建，以及文件恢复时零新增行。

## 边界

- 始终：只暴露 materialized、哈希已校验、类型化结果，并保留长期摘要/成交审计事实。
- 始终：让保留/索引有界，并区分 `AVAILABLE`、`EXPIRED` 和 `NOT_RECORDED`。
- 先询问：更改结果/导出 Schema、状态语义、保留默认值、分页上限、置顶行为、破坏性运行删除或在线 `VACUUM`。
- 禁止：暴露 staged/部分数据、复制 K 线、重建已过期详情、返回无界集合、通过过滤隐藏损坏、修改规范已完成内容，或泄露路径/密钥/供应商响应。

## 验收标准

- 在精确 materialization 成功前，staged 运行贡献零条公开记录。
- 相同持久化是无操作；冲突 identity/内容失败关闭。
- 任务完成和结果可见性相对于取消保持原子。
- 静态有序结果集的 cursor 页面无重复或缺口。
- 摘要/成交导出逐字节稳定并可在不重放时重建；已过期详情继续不可用。
- 所有活动持久化、分页和导出的日期时间都使用 `Asia/Shanghai`/`+08:00`；现有 `run_id`/`dataset_hash`/`reportHash` identity 保持不变，UTC v1 结果/导出字节保持为不可变兼容 artifact，活动 v2 结果/导出金样逐字节稳定。
- 相同重复运行不增长长期行，详情/任务保留继续有界。
- 置顶/取消置顶使用显式 revision，正确改变保留资格且不改变 `reportHash`。

## 开放问题

破坏性删除已完成运行和服务端比较导出继续延后。首版只需逐运行 JSON/CSV 导出、分页详情，以及在客户端比较明确选中的摘要。

## 审核状态

六模块能力地图、有界保留方向和本详细规格已于 2026-08-26 获用户批准。随后已在中英文中补充无法验证的旧完成行、应用负责的置顶幂等、增量导出和 32 KiB 发布闸门兼容说明。用户已于 2026-08-26 确认这些修正、统一 `Asia/Shanghai`/`+08:00` 持久化/发布契约及其余修正规格集合。双语实施计划第 15 节已于 2026-08-26 获批。该批准仅授权生成双语 `BT009`～`BT050` 任务清单。生成后的任务清单仍需单独明确批准；迁移、实现、提交、推送、依赖安装和任何联网访问仍未获授权。现有 `BT007` 存储/报告逻辑是实现基线；仅完成结果的新发布路径、公开分页、原子任务完成、置顶 API 和资源证据继续开放。

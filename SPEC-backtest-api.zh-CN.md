# 规格：backtest-api

> `SPEC-backtest-api.md` 是面向 Agent 的英文权威版；`SPEC-backtest-api.zh-CN.md` 是中文审阅版；两份文档必须保持语义一致。

## 目标

为回测数据集、持久化任务、已完成运行、分页结果、取消、置顶和安全导出提供增量、类型化、仅回环 FastAPI 资源，并且不在 HTTP 请求处理器中执行供应商或回放工作。

## 关系与范围

`backtest-api` 是 `backtest-data`、`backtest-jobs`、`backtest-results`、不可变 `plan-domain` 版本和共享 `local-web` 错误/Origin/OpenAPI 边界之上的契约优先适配器。它不实现策略规则、SQL Repository、Worker 循环、供应商映射、Vue 结果格式化、新认证系统或新 WebSocket。

当前已提交 OpenAPI 精确包含 24 条实时监控路径。本规格新增 13 条资源路径；实现并重新生成后，权威文档必须精确包含 37 条路径。在实现通过验收前，`openapi.json` 继续保持 24 路径基线，任何占位 Router 都不能计作完成。

## 命令

契约生成继续使用：

```powershell
python scripts/generate_frontend_types.py
python scripts/generate_frontend_types.py --check
```

`create_app(...)` 继续是唯一无副作用 OpenAPI 来源。生成会逐字节同时更新 `openapi.json` 和 `web/src/api/generated.ts`。本规格不授权联网同步；实现后，只有获接纳且明确包含 `allowNetwork: true` 的 `POST /api/v1/backtest-data-syncs` 命令可以入队联网任务。

## REST 资源

全部路径位于 `/api/v1`：

| 方法 | 路径 | 成功契约 |
|---|---|---|
| `GET` | `/backtest-jobs` | `200 BacktestJobPage` |
| `GET` | `/backtest-jobs/{job_id}` | `200 BacktestJobView` |
| `POST` | `/backtest-job-cancellations` | 根据取消矩阵返回 `200 BacktestJobView` 或 `202 BacktestJobView` |
| `POST` | `/backtest-data-syncs` | `202 BacktestJobReceipt` |
| `POST` | `/backtest-dataset-verifications` | `202 BacktestJobReceipt` |
| `GET` | `/backtest-datasets` | `200 BacktestDatasetPage` |
| `GET` | `/backtest-datasets/{dataset_hash}` | `200 BacktestDatasetView` |
| `GET`、`POST` | `/backtest-runs` | `200 BacktestRunPage`、`202 BacktestJobReceipt` |
| `GET`、`PATCH` | `/backtest-runs/{run_id}` | `200 BacktestRunView` |
| `GET` | `/backtest-runs/{run_id}/fills` | `200 BacktestFillPage` |
| `GET` | `/backtest-runs/{run_id}/details` | 由必填 `kind` 选择的 `200 BacktestDetailPage` |
| `GET` | `/backtest-runs/{run_id}/equity-series` | `200 BacktestEquitySeries` |
| `GET` | `/backtest-runs/{run_id}/exports/{export_kind}` | 流式 `200 SUMMARY_JSON` 或 `200 FILLS_CSV` |

`GET /plan-versions` 以增量兼容方式增加可选 `symbol`、`status` 和 `canActivate` 过滤，使浏览器绝不会加载一个不完整页面后把客户端过滤误当完整结果。

## 输入契约

所有请求对象都严格且闭合。`JavaScriptSafeInteger` 是 `0..9007199254740991` 范围内的 JSON 整数；正整数字段还排除 `0`。公开分值输入字段使用 `JavaScriptSafeInteger`。公开分值输出字段使用 `FenText`：不含 `+`、指数、空白或前导零（字面值 `0` 除外）的规范带符号十进制字符串。`DecimalText` 是有限、规范、非指数十进制字符串。费率是 `0..1` 范围内的 `DecimalText`；滑点基点是 `0..<10000` 范围内的 `DecimalText`。每个精确十进制字段都拒绝二进制 JSON 浮点数。

`BacktestDatasetScopeInput` 精确包含 `symbols`、`start`、`end`、`warmupStart`、`historicalProfile` 和 `adjustmentPolicy`。它包含 1–10 个不重复规范 `.SH`/`.SZ` 股票代码、ISO 日期、`start` 至 `end` 最多五个日历年、`warmupStart` 至 `start` 最多两个日历年、字面值 `historicalProfile=TUSHARE_STK_MINS_241_END_V1` 和字面值 `adjustmentPolicy=NONE`。这些边界以及拒绝 `end >= today` 的历史数据规则由服务端权威判定。

`BacktestDataSyncCommand` 精确包含 `scope`、`refresh` 和必填字面值 `allowNetwork: true`。它不接受 Token、供应商 URL、数据库路径、计划路径、报告路径或任意文件路径。`BacktestDatasetVerificationCommand` 精确包含 `scope`，并且完全本地执行。

`BacktestExecutionConfigInput` 精确包含以下六个必填且无默认值的字段：`commissionRate`、`minimumCommissionFen`、`stampDutyRate`、`transferFeeRate`、`buySlippageBps` 和 `sellSlippageBps`。三个费率字段使用 `0..1`；两个滑点字段使用 `0..<10000`；`minimumCommissionFen` 是 `JavaScriptSafeInteger`。

`BacktestInitialLotInput` 精确包含 `lotKey`、`bucket`、`acquiredTradeDate`、`quantity` 和 `costBasisFen`。`lotKey` 由调用方稳定提供，在命令内唯一，长度 1–64 个字符，并匹配 `[A-Za-z0-9][A-Za-z0-9._-]*`。`bucket` 为 `CORE|TACTICAL`；`quantity` 是可被 100 整除的正 `JavaScriptSafeInteger`；`costBasisFen` 是正 `JavaScriptSafeInteger`，表示整批持仓的剩余总成本。当 `lotKey` 不同时，多批持仓可以共享 `(bucket, acquiredTradeDate)`。规范化按 `(bucket, acquiredTradeDate, lotKey)` 排序，绝不暴露或接受内部 `PositionLot` identity。

`BacktestRunCommand` 精确包含 `planVersionId`、`datasetHash`、`initialCashFen`、`initialLots`、`executionConfig` 和 `eventRiskAssumption`。`planVersionId` 是 RFC 4122 UUID，序列化为规范的小写连字符文本，并且只作为查找/审计元数据；`datasetHash` 是 64 字符小写 SHA-256；`initialCashFen` 为正；`initialLots` 最多包含 200 个 `BacktestInitialLotInput`；`eventRiskAssumption` 为 `NO_EVENT_RISK|MANUAL_EVENT_RISK`。数据集必须已冻结且已校验，包含计划股票，并覆盖计划事件范围和所需预热。每个 `acquiredTradeDate <= dataset.start`；各分桶数量和总数量都不能超过已校验计划上限；并且 `initialCashFen + sum(costBasisFen) <= 9007199254740991`。在计算 `requestHash` 和确定性运行 identity 之前完成规范化。空 `initialLots` 选择 `backtest-run-v1`；非空 `initialLots` 选择 `backtest-run-v2`，并把每个 `lotKey` 纳入 identity preimage。

`BacktestJobCancellationCommand` 精确包含 `jobId`。`BacktestRunPinCommand` 精确包含 `pinned` 和非负 `expectedRevision`。每个 `POST` 和 `PATCH` 还要求下文描述的 `Idempotency-Key` Header；该 Header 不复制进 JSON Body。

对于新运行提交，应用服务对不可变实时计划版本执行一次只读查找，重新校验其规范 `planJson`、重新计算的 `planHash`、股票、确定性校验和 `canActivate=true`，并把有界规范计划快照随任务持久化。计划不必处于激活状态。相同 key 的 receipt 重放从任务存储解析，不重复该查找。Worker、恢复、策略回放、结果复用、轮询和导出对实时数据库执行零读写。

## 输出契约

所有 JSON Schema 都严格、闭合、使用 camelCase，并使用 `UPPER_SNAKE` 枚举值。禁止把任意 Mapping、已存请求 JSON、原始供应商 payload 或无界证据作为公开契约。每个回测日期时间输入和输出，包括任务/审计/发布元数据及嵌套判断/结果时间，都使用带时区的 `Asia/Shanghai`。输入只接受携带 `+08:00` 及 0～6 位小数秒的 RFC 3339 文本，并在请求哈希、Cursor 编码、比较或持久化前规范化；输出精确采用 `YYYY-MM-DDTHH:MM:SS.ffffff+08:00`。`Z`、无偏移值、超过 6 位小数秒和其他偏移均校验失败；仅日期字段继续使用中国市场日历。计数/Revision 使用非负 `JavaScriptSafeInteger`；SHA-256 值为 64 字符小写十六进制。

### 任务 Schema

`BacktestJobKind` 为 `DATA_SYNC|DATASET_VERIFY|BACKTEST_RUN`。`BacktestJobStatus` 为 `QUEUED|RUNNING|CANCEL_REQUESTED|COMPLETED|FAILED|CANCELLED`。`BacktestJobPhase` 为 `QUEUED|VALIDATING_INPUT|SYNCING_DATA|VERIFYING_DATASET|REPLAYING|MATERIALIZING_RESULTS|FINALIZING|TERMINAL`。`BacktestProgressUnit` 为 `ITEMS|SYMBOL_DAYS|EVENTS|ROWS`。

| Schema | 精确字段与不变量 |
|---|---|
| `BacktestJobReceipt` | `jobId`、`kind`、`status`、可空 `runId`、可空 `datasetHash`、`attempt`、`revision`、`reused`、`submittedAt`。每个提交响应都是 `202`，包括 `status=COMPLETED`、`attempt=0`、`revision=0` 且 `reused=true` 的立即确定性复用。 |
| `BacktestJobProgressView` | `phase`、`completedUnits`、可空 `totalUnits`、`unit`、`updatedAt`。如果存在 `totalUnits`，则 `completedUnits <= totalUnits`；同一 claim generation 的进度单调。 |
| `BacktestJobView` | `jobId`、`kind`、`status`、`requestHash`、可空 `runId`、可空 `datasetHash`、`progress`、可空 `result`、`attempt`、`revision`、`createdAt`、可空 `startedAt`、`updatedAt`、可空 `finishedAt`、可空 `cancelRequestedAt`、`reused`、可空 `errorCode`、可空 `errorMessage`。`attempt` 为 `0..3`；错误文字经过脱敏且最多 512 个字符。 |

`BacktestJobResultView` 是以 `kind` 为判别字段的 Union，并且只在 `status=COMPLETED` 时存在：

| 变体 | 精确字段 |
|---|---|
| `BacktestDataSyncJobResultView` | `kind=DATA_SYNC`、`calendarRows`、`minuteDays`、`dailyLimitRows`、`dailyBarRows`、`networkCalls` |
| `BacktestDatasetVerificationJobResultView` | `kind=DATASET_VERIFY`、`ready`、可空 `datasetHash`、`coverage`、`blockers` |
| `BacktestRunJobResultView` | `kind=BACKTEST_RUN`、`runId`、`reportHash`、`reused` |

`errorCode` 和 `errorMessage` 仅在 `FAILED|CANCELLED` 时同时存在，其他状态下都为空。它们是唯一公开的失败/取消诊断，并只保留在任务资源；绝不出现在已完成运行、运行详情页面、权益序列或导出中。`result` 仅在 `COMPLETED` 时非空。终态任务具有 `phase=TERMINAL` 和非空 `finishedAt`。

`BACKTEST_RUN` receipt/job 始终具有非空且相互一致的 `runId` 和 `datasetHash`；其已完成结果具有相同 `runId`。`DATA_SYNC|DATASET_VERIFY` 始终具有 `runId=null`。`DATA_SYNC` 具有 `datasetHash=null`；`DATASET_VERIFY` 在成功 ready 前可以保持为空，此后任务值与结果值一致。外层 `kind`、结果判别字段、进度阶段、状态、时间、错误对及结果是否存在作为一个闭合 Union 统一校验，不能各自独立校验。

### 数据集 Schema

| Schema | 精确字段 |
|---|---|
| `BacktestDatasetScopeView` | `symbols`、`start`、`end`、`warmupStart`、`historicalProfile`、`adjustmentPolicy` |
| `BacktestDatasetCoverageView` | `symbolCount`、`tradingDayCount`、`calendarRowCount`、`minuteDayCount`、`minuteBarCount`、`dailyLimitRowCount`、`dailyBarRowCount`、`blockers` |
| `BacktestDatasetView` | `datasetHash`、`schemaVersion=backtest-dataset-v1`、`scope`、`coverage`、`createdAt`、`verifiedAt` |

`blockers` 是最多 100 个稳定 `UPPER_SNAKE` Code 的有序、不重复列表。完整数据集 membership、Artifact 行、供应商 Body 和本地路径绝不序列化。

### 已完成运行 Schema

`BacktestArtifactAvailability` 为 `AVAILABLE|EXPIRED|NOT_RECORDED`。`BacktestResultAvailabilityView` 精确包含 `decisionDetails`、`signalDetails`、`executionOutcomeDetails` 和 `equitySeries`，每个字段都是 `BacktestArtifactAvailability` 值。

| Schema | 精确字段 |
|---|---|
| `BacktestRunSummaryView` | `runId`、`reportHash`、可空 `planVersionId`、`planHash`、`datasetHash`、`symbol`、`status=COMPLETED`、`eventStart`、`eventEnd`、`completedAt`、`pinned`、`revision`、`fillCount`、`metrics`、`availability` |
| `BacktestRunView` | `BacktestRunSummaryView` 的全部字段，加上 `initialCashFen`、`coverage`、`assumptions`、`formulaVersions` 和 `limitations` |
| `BacktestRunCoverageView` | `eventStart`、`eventEnd`、`tradingDayCount`、`decisionCount`、`signalCount`、`orderCount`、`fillCount`、`outcomeCount`、`equityPointCount` |
| `BacktestMetricsView` | `initialCashFen`、`initialEquityFen`、`finalCashFen`、`finalEquityFen`、`totalReturn`、`maximumDrawdown`、`tradeCount`、`winningSellCount`、`winRate`、`turnoverFen`、`totalCostFen`、`realizedPnlFen`、`unrealizedPnlFen`、`blockedCount`、`skippedCount` |
| `BacktestExecutionConfigView` | `commissionRate`、`minimumCommissionFen`、`stampDutyRate`、`transferFeeRate`、`buySlippageBps`、`sellSlippageBps` |
| `BacktestAssumptionsView` | `eventRiskAssumption`、`executionConfig`、`executionConfigHash`、`priceAdjustmentPolicy`、`historicalProfile` |
| `BacktestFormulaVersionsView` | `runFormulaVersion`、`reportSchemaVersion`、`executionFormulaVersion`、`metricFormulaVersion` |

`BacktestRunView.coverage` 是 `BacktestRunCoverageView`，而数据集/任务校验 coverage 是 `BacktestDatasetCoverageView`。`BacktestAssumptionsView.executionConfig` 是 `BacktestExecutionConfigView`。上述每个 `*Fen` 输出都是 `FenText`；`totalReturn`、`maximumDrawdown`、`winRate`、费率和滑点是其 Domain 范围内的规范 `DecimalText`，绝不是 JSON Number。`limitations` 是最多 32 个稳定 Token 的有序、不重复列表，每项最多 128 个字符。`planVersionId` 可空，因为来自 CLI 的已完成结果可能没有实时计划行；`planVersionId` 过滤只匹配相同非空审计引用并排除空值行。只有原子发布已完成结果后才存在运行资源；不存在部分或失败的 `BacktestRunView`。

### 结果 Schema

| Schema | 精确字段 |
|---|---|
| `BacktestFeeBreakdownView` | `commissionFen`、`stampDutyFen`、`transferFeeFen`、`totalFen` |
| `BacktestFillView` | `fillId`、`orderId`、`signalId`、`runId`、`planHash`、`datasetHash`、`resultHash`、`configHash`、`sourceBarId`、`side`、`symbol`、`bucket`、可空 `targetLotId`、`filledAt`、`requestedQuantity`、`quantity`、`priceFen`、`notionalFen`、`fees`、`cashDeltaFen`、`costBasisReleasedFen`、可空 `realizedPnlFen` |
| `BacktestDecisionView` | `kind=DECISION`、`detailId`、`runId`、`eventAt`、`resultHash`、`decision`，其中 `decision` 是仅供回测使用的闭合 `BacktestAuthoritativeDecisionView` 投影 |
| `BacktestSignalView` | `kind=SIGNAL`、`detailId`、`runId`、`eventAt`、`signalId`、`resultHash`、`signalType`、`symbol`、可空 `quantity`、可空 `bucket`、可空 `targetLotId`、`causeId` |
| `BacktestExecutionOutcomeView` | `kind=EXECUTION_OUTCOME`、`detailId`、`runId`、`eventAt`、`outcomeId`、`signalId`、可空 `orderId`、可空 `sourceBarId`、`status`、可空 `reason`、可空 `fillId` |
| `BacktestEquityPointView` | `snapshotId`、`runId`、`symbol`、`markedAt`、`markPriceFen`、`cashFen`、`positionQuantity`、`marketValueFen`、`costBasisFen`、`realizedPnlFen`、`unrealizedPnlFen`、`totalCostFen`、`equityFen` |

所有结果 `*Fen` 字段都是 `FenText`。`BacktestAuthoritativeDecisionView` 与现有闭合实时 `AuthoritativeDecisionView` 逐字段、逐语义等价，包括枚举、证据 identity、顺序和边界；唯一例外是每个名称以 `Fen` 结尾的嵌套字段都序列化为 `FenText`。它既不修改，也不替换现有 24 条路径使用的实时投影。完整编码后的 `BacktestDecisionView` 必须在结果发布时满足 32 KiB item 上限；证据过大时发布失败，绝不截断。`BacktestDetailPage.kind` 必填且仅限 `DECISION|SIGNAL|EXECUTION_OUTCOME`；它的 item 变体携带相同字面量判别字段。失败/取消 `DIAGNOSTIC` 和内部 `DEBUG_TRACE` 不是运行详情。`BacktestDetailPage` 包含 `kind`、`availability`、`filters`、`items`、`limit`、`nextCursor`、`hasMore` 和 `highWatermark`；`filters` 回显包含相同必填 `kind` 的规范化对象。当可用性不是 `AVAILABLE` 时，`items` 为空、`nextCursor` 为空且 `hasMore=false`；`EXPIRED` 绝不表示为 `NOT_RECORDED`。

`BacktestEquitySeries` 精确包含 `availability` 和 `items`。它按 `(markedAt, snapshotId)` 排序，最多包含 2,000 个每日点。当可用性不是 `AVAILABLE` 时，`items` 为空。`BacktestJobPage.items` 为 `BacktestJobView[]`；`BacktestDatasetPage.items` 为 `BacktestDatasetView[]`；`BacktestRunPage.items` 为 `BacktestRunSummaryView[]`；`BacktestFillPage.items` 为 `BacktestFillView[]`；`BacktestDetailPage.items` 为与判别字段匹配的详情变体。成交行长期保留，因此不使用详情可用性状态。

## 分页与排序

`limit` 默认为 20，范围为 `1..100`。首次请求的 `cursor` 可省略；它是 `CursorToken`：最多 512 个字符的 ASCII Token。精确 Wire 形式是 `<payload_b64url>.<mac_b64url>`，使用无 Padding 的 base64url Segment。规范 payload 包含 `v=cursor-v1`、Route identity、规范化过滤 SHA-256、精确 Order identity、首页高水位 Tuple 和最后已见 Tuple。MAC 是对 payload Segment 使用 HMAC-SHA-256 计算的结果，密钥是安装级本地 256-bit Secret，以限制性本地权限生成并持久化。密钥轮换/缺失、非法编码/MAC/版本、Route/过滤/排序不匹配或畸形 Tuple 都返回相同 `422 VALIDATION_ERROR`，不提供可作 Oracle 的具体原因。

首页 membership 由签名高水位 Tuple 冻结；之后插入的行不能进入本次遍历。每个 Cursor 页面精确返回 `filters`、`items`、`limit`、`nextCursor`、`hasMore` 和 `highWatermark`；`filters` 是服务端规范化的闭合过滤对象，可空 `nextCursor` 是 `CursorToken`，非空 `highWatermark` 是本次遍历保持不变的签名 `CursorToken` 锚点。精确排序 Tuple 为：

| 资源 | 排序 |
|---|---|
| 任务 | `(createdAt DESC, jobId DESC)` |
| 数据集 | `(createdAt DESC, datasetHash DESC)` |
| 运行 | `(completedAt DESC, runId DESC)` |
| 成交 | `(filledAt ASC, fillId ASC)` |
| 判断/信号/结果 | `(eventAt ASC, detailId ASC)` |

任务过滤为 `kind`、`status`、`runId`、`datasetHash`、`createdFrom` 和 `createdTo`。数据集过滤为 `symbol`、`startOnOrAfter`、`endOnOrBefore`、`historicalProfile` 和 `adjustmentPolicy`。运行过滤为 `symbol`、`planVersionId`、`datasetHash`、`completedFrom`、`completedTo` 和 `pinned`。成交过滤是闭合空对象；详情过滤只包含必填 `kind`。过滤使用 AND 语义；重复枚举值规范化为排序后的不重复 Set；Cursor 绑定完整的规范化过滤对象。

任务 Cursor 还绑定独立的任务列表 `membershipRevision`。只有状态迁移改变带状态过滤的遍历 membership 时才递增该值；普通进度/Heartbeat 更新不递增。如果后续页面请求前已绑定 Revision 发生变化，该页面返回 `409 CONFLICT`，客户端从首页重新开始。不包含可变 `status` 过滤的遍历继续锚定不可变 `(createdAt, jobId)`，不会因为进度或状态展示值变化而失败。

每个编码后的 item 最多 32 KiB，每页最多 100 项，包含信封开销的完整 UTF-8 JSON 响应严格低于 `4 * 1024 * 1024` Bytes。在提交 Header 之前检查投影和响应大小不变量；服务端绝不静默截断 item 或页面。导出不使用 JSON 分页。

## 幂等、Revision 与错误

每个 `POST` 和 `PATCH` 都要求 1–128 个字符且匹配 `[A-Za-z0-9][A-Za-z0-9._:-]*` 的 `Idempotency-Key`。应用服务用规范请求哈希原子认领 key；禁止 check-then-insert。

- 相同 key 和相同 hash 返回同一规范响应与资源 identity。提交端点始终返回 `202 BacktestJobReceipt`，无论任务处于活动、终态，还是立即复用已完成运行。
- 相同 key 和不同 hash 返回 `409 CONFLICT`，不创建资源或副作用。
- 提交与取消的重放保证在所引用任务非终态期间持续有效，并在 `finishedAt` 后持续 14 天。置顶操作的幂等记录在其内部审计 `recordedAt` 后保留 14 天；该时间不是公开运行字段。过期后 key 可以表示新的意图，但当前 Revision 校验和确定性已完成运行复用仍会阻止陈旧变更或重复结果。
- 不同 key 的相同活动 operation identity 共享一个活动任务。相同已完成运行输入创建立即完成的 `reused=true` 任务，关联已有 `runId` 且不执行回放。

取消和置顶都是应用/Unit of Work 变更，会原子认领幂等 key、规范请求 hash、状态迁移、审计记录和规范响应；Router 适配器绝不自行实现重放。`PATCH /backtest-runs/{run_id}` 只修改 `pinned` 并要求 `expectedRevision`；过期 Revision 返回 `409 CONFLICT`。成功 no-op 和状态变更重放都返回同一 `200 BacktestRunView`。

取消使用以下精确矩阵：

| 当前状态 | 响应 | 结果 |
|---|---|---|
| `QUEUED` | `200 BacktestJobView` | 原子变为 `CANCELLED` |
| `RUNNING` | `202 BacktestJobView` | 原子变为 `CANCEL_REQUESTED` |
| `CANCEL_REQUESTED` | `202 BacktestJobView` | 幂等重放当前状态 |
| `CANCELLED` | `200 BacktestJobView` | 幂等终态重放 |
| `COMPLETED` | `409 CONFLICT` | 不修改 |
| `FAILED` | `409 CONFLICT` | 不修改 |

队列耗尽返回带 `Retry-After` 的 `429 RATE_LIMITED`；缺少服务/Worker/配置返回 `503 SERVICE_UNAVAILABLE`。资源缺失返回 `404 NOT_FOUND`。每个错误使用现有闭合 `ErrorResponse` 信封和固定 `ApiErrorCode`；公开消息固定且经过脱敏。每个请求获得服务端生成的 32 字符小写十六进制请求 ID，并位于 `X-Request-ID`；忽略客户端提供的 ID。每个提交 `202` 包含 `Location: /api/v1/backtest-jobs/{job_id}`。非终态 `202` 还包含 `Retry-After: 2`；立即复用的 `COMPLETED` Receipt 省略 `Retry-After`。运行中/已请求取消的取消 `202` 包含两个 Header。

## 应用与安全边界

`create_app(backtest_read_service=..., backtest_operation_service=...)` 注入 Protocol 适配器，不构造数据库、SDK、线程、Timer、Worker 或 Task。导入/OpenAPI 生成继续无 I/O。`create_production_app(...)` 必须明确组合真实回测服务和协调器生命周期；缺少服务的 Router 返回 `SERVICE_UNAVAILABLE`，不能算产品完成。

现有精确回环监听、同源保护、生产无 CORS、CSP/安全 Header 和 4 MiB 请求体上限保持不变。所有输入由服务端校验；SQL 参数化；Vue 校验绝不是安全边界。任何 API 都不返回凭据、供应商文本、本地路径、完整异常、staged 数据、原始持久化 payload 或实时状态修改。回测信号继续是研究结果，绝不发布到实时 WebSocket/outbox。

导出只接受路径 `run_id` 和 `export_kind=SUMMARY_JSON|FILLS_CSV`，并从经过校验的长期活动 v2 已完成结果行重建。`SUMMARY_JSON` 发出 `backtest-report-summary-v2`，使用 `application/json` 和文件名 `backtest-<runId>-summary.json`；`FILLS_CSV` 发出 `backtest-simulated-fills-v2`，使用 `text/csv; charset=utf-8` 和文件名 `backtest-<runId>-fills.csv`。两者只包含规范 `Asia/Shanghai` 时间戳，并使用带该白名单 ASCII 文件名的 `Content-Disposition: attachment`、`Cache-Control: no-store` 和 `X-Content-Type-Options: nosniff`。不可变 UTC v1 artifact 在另行批准采纳前排除于本公开路由。导出不缓冲完整文件，每个 Chunk 不超过 64 KiB，在 Chunk 之间检查客户端断连，并在断连后立即中止重建/迭代。它绝不创建报告文件或暴露文件路径。

## 可观测性与性能

HTTP RED 证据以有界 Label 记录 Route Template 速率、错误类别和延迟。结构化日志携带 `requestId`、可选 `jobId`/`runId`、Route Template、状态类别和脱敏错误 Code；绝不记录完整 Body 或 Secret。获批准的健康投影公开有界队列/Worker 事实，不增加未经审阅的遥测依赖。

本规格只设置结构闸门：处理器不执行供应商/回放工作；列表遵守 100 项、32 KiB/item 和低于 4 MiB 响应限制；导出 Chunk 最多 64 KiB 且断连即停止；应用适配器使用有界增量读取。实现计划必须在性能实现开始前定义固定数据库 Fixture、环境、重复次数、百分位延迟、峰值内存/WAL 和导出吞吐验收数字。本规格未批准任何经验阈值。

## 项目结构

严格 Schema 位于 `src/trade_plan_monitor/web/schemas.py` 或聚焦回测 Schema 模块；Route Adapter 位于 `src/trade_plan_monitor/web/routers/`；Service Protocol 继续作为应用边界。Cursor 签名/校验和有界导出 Helper 是共享后端基础设施，不能按 Route 复制。`openapi.json` 和 `web/src/api/generated.ts` 一起生成。前端请求编排位于 `web/src/api/backtests.ts`，不能无界扩张 Generic Client。

## 代码风格

使用类型化 FastAPI Dependency、严格冻结 Pydantic 输入/输出 Model、显式响应/状态声明、复数名词资源、camelCase JSON Alias、穷尽枚举、有界 Array/Text、参数化应用服务和一个共享错误信封。序列化前校验服务输出，并让 Transport Adapter 不包含 Domain 决策。

## 测试策略

契约测试覆盖每个 Method/Path/Status/Schema；所有字段与跨字段约束；JavaScript-safe 分值输入和 `FenText` 输出；统一 `Asia/Shanghai`/`+08:00` 日期时间往返、0～6 位输入到固定六位规范化，以及拒绝 `Z`、无偏移、超精度和其他偏移；费率/滑点边界；200 个初始持仓和 `lotKey` 规范化；计划快照校验及 Worker/回放对实时数据库零访问；任务进度/结果 Union；数据集/运行 View；过滤；精确 Cursor 格式、签名、高水位遍历、密钥轮换、篡改和过滤不匹配；100 项、32 KiB/item 和低于 4 MiB 响应闸门；全部可用性状态；14 天幂等与竞态；`202` 下立即完成复用；置顶 Revision；完整取消矩阵；队列满重试；缺少服务；Origin/Body/安全 Header；脱敏；v1 排除、v2 64 KiB 流式导出和断连中止；请求 ID；以及请求处理器零工作。

OpenAPI 测试固定精确 37 条路径，重新生成 TypeScript 并拒绝 Schema/Status 漂移。生产组合测试证明真实服务和生命周期可达，而不是默认落入 `DEGRADED`/`SERVICE_UNAVAILABLE`。性能测试及其实测阈值在获批准的实现计划中定义，不能在规格实现期间临时发明。

## 边界

- 始终：契约优先、严格类型化 Schema、边界校验、原子幂等、有界签名 Cursor 分页、同源回环安全、生成 TypeScript 和服务输出重新校验。
- 始终：每个长操作提交都返回 `202`，提交时持久化计划快照，并让持久任务/结果存储在此后保持权威。
- 先询问：修改 API Path/Field/Status、错误语义、分页/响应限制、Origin/CORS/认证、公开新详情/导出或增加 WebSocket Transport。
- 禁止：接受路径/Token/供应商 URL、在 Route 中执行工作、公开 staged/raw/任意 payload、把策略逻辑复制到 Transport、让 Worker/回放读取实时状态、修改实时状态或把回测信号发布为实时提醒。

## 验收标准

- 权威 OpenAPI 从精确 24 条扩展到精确 37 条声明路径，并且生成 TypeScript 逐字节匹配。
- 每个长操作都返回持久化 `202` Receipt，包括确定性已完成复用，处理器内无供应商/回放工作。
- 相同 key 的 Receipt 重放在 14 天窗口内有保证；冲突复用失败；相同运行输入只执行一次。
- 列表/详情保持稳定、有界、有签名且绑定过滤，每页最多 100 项、每项最多 32 KiB、每个 JSON 页面低于 4 MiB。
- 公开分值输入为 JavaScript-safe，所有分值输出为 `FenText`；所有费率/滑点和初始持仓 identity 都精确。
- 所有日期时间输入、输出、筛选、Cursor 键和导出都使用规范 `Asia/Shanghai`/`+08:00`；不接受主机/浏览器转换或其他偏移。
- 提交时持久化计划快照；Worker、恢复、幂等重放和策略回放对实时数据库零访问。
- 取消、置顶、权益/详情可用性、导出和仅属于任务的失败/取消诊断都由闭合类型化契约表示。
- 真实生产组合在现有回环安全边界下提供这些资源。

## 开放问题

首个契约提案没有阻断问题。WebSocket 任务事件、远程认证、破坏性运行删除、Debug Trace 公开、组合运行、服务端比较和经验性能预算继续延期，并根据适用情况要求单独批准或获批准的实现计划。

## 审核状态

用户于 2026-08-26 确认六模块地图、增量本地 REST 方向和本详细规格集合。随后通过双语一致性审计把 `BacktestRunCommand.planVersionId` 修正为现有 RFC 4122 UUID/string identity；增加仅供回测使用的 `FenText` 判断投影且不改变实时 24 路径契约；闭合任务判别不变量；并明确应用负责的取消/置顶幂等。用户已于 2026-08-26 明确否决临时 UTC 提案、确认每个回测时间统一使用 `Asia/Shanghai`/`+08:00` 契约，并确认全部其余修正条款。双语实施计划第 15 节已于 2026-08-26 获批。该批准仅授权生成双语 `BT009`～`BT050` 任务清单。生成后的任务清单仍需单独明确批准；实现、重新生成已提交的 24 路径快照、提交、推送、依赖安装和任何联网访问仍未获授权。

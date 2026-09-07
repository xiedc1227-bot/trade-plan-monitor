# 规格：strategy-state（策略状态与持久化）

> 中文审阅版。英文权威版为 `SPEC-strategy-state.md`；两份文档必须保持语义一致。

## 目标

使用一个 SQLite WAL 数据库持久化单用户监控状态：计划版本、活动计划、人工持仓批次、T+1、低吸事件、风险状态、判断幂等记录、行情与参考数据、健康状态和审计记录。

程序重启后不能丢失状态或重复提醒。提醒确认不等于成交，仓位只能通过人工成交/减仓操作改变。

## 技术栈

- Python 3.14.x（`>=3.14,<3.15`）
- SQLite WAL：唯一数据库
- SQLAlchemy 2 与 Alembic
- Pydantic 2：仓储 DTO
- SQLite 在线备份 API 与完整性校验

不引入 PostgreSQL、Redis、Parquet、分布式锁、主从或高可用组件。

## 命令

```powershell
python -m pytest tests/unit/test_strategy_state.py -q
python -m pytest tests/integration/test_sqlite_repositories.py -q
python -m pytest tests/integration/test_sqlite_backup.py -q
python -m ruff check src/trade_plan_monitor/state tests/unit/test_strategy_state.py tests/integration
```

## 项目结构

```text
src/trade_plan_monitor/state/
├── database.py       # Engine、Session 与 WAL 配置
├── events.py         # 强类型全局监控事件账本
├── models.py         # SQLAlchemy 持久化模型
├── repositories.py   # 窄接口仓储和查询
├── unit_of_work.py   # 短事务边界
├── migrations/       # Alembic 迁移
└── backup.py         # 在线备份、校验和保留策略
tests/unit/
└── test_strategy_state.py
tests/integration/
├── test_sqlite_repositories.py
└── test_sqlite_backup.py
```

## 状态模型

核心逻辑表：

```text
plan_source(id, source_text, source_hash, created_at)
plan_version(id, plan_id, version, symbol, plan_hash, status, payload_json, source_id, revision, created_at)
plan_version_review(plan_version_id PRIMARY KEY, review_issues_json)
plan_activation_state(symbol PRIMARY KEY, plan_version_id NULL, revision, changed_at)
active_plan(symbol PRIMARY KEY, plan_version_id UNIQUE, activated_at, revision)
position_lot(id, symbol, bucket, quantity, remaining_qty, acquired_trade_date, cost_fen, related_alert_id, closed_at)
zone_episode(id, plan_hash, symbol, zone, started_at, episode_low_fen, bars_since_low, status, alerted_signal, last_processed_bucket_end)
risk_state(symbol PRIMARY KEY, plan_hash, status, breach_trade_date, prior_close_fen, revision, updated_at)
evaluation_ledger(plan_hash, symbol, evaluation_kind, target_value, formula_version, result_hash, evaluated_at, PRIMARY KEY(plan_hash, symbol, evaluation_kind, target_value, formula_version))
ai_provider_configuration(id, display_name, provider_type, base_url, model_name, key_ref, environment_variable, timeout_seconds, max_retries, max_input_chars, max_output_tokens, temperature_milli, prompt_version, enabled, revision, created_at, updated_at)
provider_health(capability PRIMARY KEY, status, checked_at, latency_ms, error_code, next_retry_at)
symbol_health(symbol PRIMARY KEY, status, latest_bar_end, data_age_seconds, gap_json, error_streak, revision)
audit_log(id, action, entity_type, entity_id, before_hash, after_hash, details_json, created_at)
minute_bar(symbol, bar_end, ohlc_fen, volume_shares, amount_yuan, received_at, PRIMARY KEY(symbol, bar_end))
five_minute_bar(symbol, bar_end, ohlc_fen, volume_shares, amount_yuan, formula_version, PRIMARY KEY(symbol, bar_end, formula_version))
daily_bar(symbol, trade_date, ohlc_fen, volume_shares, amount_yuan, is_official, received_at, PRIMARY KEY(symbol, trade_date, is_official))
trading_calendar(exchange, cal_date, is_open, previous_trade_date, PRIMARY KEY(exchange, cal_date))
daily_price_limit(symbol, trade_date, up_limit_fen, down_limit_fen, received_at, PRIMARY KEY(symbol, trade_date))
```

基线迁移还会创建已批准的跨模块支撑表：

```text
request_idempotency(idempotency_key PRIMARY KEY, request_hash, status, response_code, response_json, created_at, updated_at)
latest_quote(symbol PRIMARY KEY, price_fen, bar_end, received_at)
alert_event(id PRIMARY KEY, sequence UNIQUE, dedup_key UNIQUE, payload_json, message_text, created_at, acknowledged_at)
monitor_event(id PRIMARY KEY, sequence UNIQUE, event_type, schema_version, aggregate_id, payload_json, occurred_at)
monitor_sequence(singleton_id PRIMARY KEY CHECK(singleton_id = 1), last_sequence CHECK(last_sequence >= 0))
delivery_attempt(id PRIMARY KEY, event_id, channel, attempt, status, response_code, next_retry_at, delivered_at, error_code, UNIQUE(event_id, channel, attempt))
```

`ai_provider_configuration` 只包含有界非敏感设置和查找引用，绝不保存 API Key 值或派生的 Authorization Header；是否已配置及脱敏状态由密钥边界动态生成。

提醒行为由 `notification-outbox` 负责，但其表使用同一事务单元。逻辑字段 `ohlc_fen` 在物理表中展开为 `open_fen`、`high_fen`、`low_fen` 和 `close_fen`。价格使用整数分；精确的十进制元金额保存为规范化十进制文本，以避免 SQLite 二进制浮点损失；日期使用 ISO 日历值；来源/接收时间戳使用带时区的规范化 ISO 8601 文本。

### 持仓批次

```python
class PositionLot(BaseModel):
    lot_id: UUID
    symbol: str
    bucket: Literal["CORE", "TACTICAL"]
    acquired_trade_date: date
    quantity: int
    remaining_quantity: int
    cost_fen: int
    related_alert_id: UUID | None
```

可卖数量根据交易日历和买入交易日计算。人工登记买入时必须指定底仓/机动仓和数量；从提醒进入登记界面时可以预填，但不能自动提交。

### 乐观锁与幂等

- 可变记录携带整数 `revision`。
- REST 写操作携带预期修订号和 `Idempotency-Key`。
- 幂等键与请求哈希原子占用；相同键对应不同请求时返回 422。
- 修订号冲突返回 `409 CONFLICT` 和当前版本。
- 计划激活、状态迁移、判断记录、审计和提醒入队在需要时使用同一短事务。

在 T038 Web 边界中，建仓和减仓继续作为该仓储之上的明确应用服务命令。HTTP 适配器要求一个有界幂等键和预期持仓修订；应用服务解析活动计划的 100 股手数与最大数量，串行化写入，应用 T+1/剩余数量检查，并原子插入持仓审计。新批次修订为 `0`；后续持久修订按 `(quantity - remaining_qty) / 100` 推导。减仓回执把应用数量和交易日绑定到精确的操作前/后剩余数量，因此修订检查无需推测或虚构存储字段。可选 `related_alert_id` 仅用于 provenance：它可以预填明确命令，但不能提交该命令。提醒确认使用独立 Outbox 事务，将未确认/已确认状态映射为修订 `0`/`1`，并让已确认修订 `1` 保持为 no-op；它不能调用任何持仓操作。诊断判断不应用仓储迁移、不认领判断账本、不入队提醒，也不修改持仓；只允许写入明确报告的可选诊断审计。

从 T032 开始，`evaluation_ledger` 使用无损主键 `(plan_hash, symbol, evaluation_kind, target_value, formula_version)`。`INTRADAY` 在 `target_value` 中存储规范上海时区五分钟时间戳；`OFFICIAL_CLOSE` 只存储 ISO 交易日期，因此盘中 15:00 目标不会与同日官方收盘标识冲突。迁移 `0005_evaluation_kind` 将所有早期行回填为 `INTRADAY`，保留结果与判断事实，并在存在任何官方收盘标识时拒绝降级。仓储要求显式 kind 和且仅一个强类型目标，并暴露互斥的 `bucket_end` / `official_trade_date` 字段。

`EvaluationRepository.has_claim(...)` 针对相同五个主键字段执行精确 identity 只读查询。T033 只用它在已提交官方收盘日期上短路供应商和判断工作；它既不比较结果哈希，也不把 `EvaluationIdentityConflictError` 转换为重复结果。

### 计划仓储与工作单元契约

- `save_draft` 接受类型化 `TradePlan`，重新执行跨字段保存校验，并在同一事务中保存源文本、规范 JSON、内容哈希、不可变版本、有界审核问题和 `PLAN_DRAFT_SAVED` 审计。股票尚不存在状态时，它还会创建 revision 为 `0` 的非活动 `plan_activation_state`。已有 `(plan_id, version)` 绝不覆盖。基版本保存会验证不可变计划/股票 identity，并且只有幂等占用已串行化 SQLite 写者后才取得该 `plan_id` 的下一版本；后继计划由应用服务而非浏览器构造后再保存。Web 边界把计划版本和返回 revision 限制在 JavaScript 安全整数上限内，并在提交前拒绝不安全的导入文档或耗尽的后继序列；这不会收窄或改写持久化 Schema v1 领域。版本详情读取会连接精确原文和审核记录，稳定分页集合读取则返回从这些已验证记录派生的轻量摘要，因此保存、查询与 JSON/YAML 导入 provenance 可跨重启保留，而无需在一页中返回每个大型文档。
- 激活要求 `PlanValidationResult.can_activate` 成功，包括每个已持久化审核问题。不存在启用状态时逻辑 revision 为 `0`；首次激活要求 `expected_revision=0` 并创建 revision `1`，此后每次激活或停用都要求精确匹配当前 `plan_activation_state.revision` 并只递增一次。激活会同步可空持久状态与 `active_plan` 指针；停用则移除活动指针，保留带新 revision 的非活动状态，把此前活动的不可变版本标为 `SUPERSEDED`，并在同一事务中追加审计和 `plan.deactivated` 事件。SQLite 写者在启用状态读取前串行化，条件写入与数据库键共同保证每只股票仅有一个活动版本。
- 新幂等键创建 `PENDING`。相同键和哈希在待处理时产生 `IDEMPOTENCY_IN_PROGRESS`；进入 `COMPLETED` 后重放已保存的规范响应。相同键对应不同 SHA-256 请求哈希时始终产生 `IDEMPOTENCY_KEY_REUSED`。已保存规范响应限制为 4 MiB，使完整计划版本响应可以重放，同时不形成无界持久化表面。
- 仓储失败暴露稳定错误码，例如 `PLAN_VERSION_EXISTS`、`PLAN_SAVE_BLOCKED`、`PLAN_ACTIVATION_BLOCKED`、`PLAN_VERSION_NOT_FOUND`、`CONFLICT`、`IDEMPOTENCY_KEY_REUSED`、`IDEMPOTENCY_IN_PROGRESS` 和 `IDEMPOTENCY_CLAIM_NOT_FOUND`；后续传输适配器将其映射为 HTTP，但不暴露 SQL 或原始 Session 细节。
- `UnitOfWork` 拥有一个显式短事务。调用方必须调用 `commit()` 才能持久化；退出上下文时未提交则回滚。其公共协议只暴露仓储及 `commit()`/`rollback()`，绝不暴露 SQLAlchemy Session。
- `UnitOfWork.events` 暴露绑定 Session 的 `MonitorEventLog`，`UnitOfWork.alerts` 则在相同日志与 Session 上暴露 `AlertOutbox`。计划激活、持仓变更、股票/供应商健康变更、判断快照、提醒创建、确认审计及其对应事件因此共同提交或回滚。封闭业务词表为 `symbol.snapshot.updated`、`symbol.health.updated`、`alert.created`、`alert.acknowledged`、`plan.extraction.updated`、`plan.activated`、`plan.deactivated`、`position.updated`、`ai.provider.updated`、`system.health.updated` 和已批准的 `market.index.updated`。负责提取、停用或 AI 供应商持久化的注入式应用服务必须在所属变更事务中追加对应事件；持久化边界不虚构这些服务。
- 追加迁移 `0006_monitor_event` 紧随 `0005_evaluation_kind`，用唯一的 `monitor_sequence` 替换 `alert_sequence`，并以相同 UUID 和序号把每条历史 `alert_event` 回填为 `alert.created`。既有提醒序号因此保持稳定，后续提醒行在全局序号域中可以稀疏。在任何 DDL 前，由 revision 本地拥有的冻结 v1 校验器会拒绝不符合迁移原始契约、因而无法安全规范转换的任何历史提醒行：它校验精确载荷/对象形状、UUID/dedup/symbol/信号动作 identity、封闭条件/证据/事实类型、三值证据分区、节点/事实/数值预算、动作/区间/next-step 语义、精确上海时区时间差、有界且无控制字符的文本、确定性中文渲染及旧序号高水位。该 revision 完全自包含，绝不导入持续演进的应用 `AlertPayload`、`AlertEvent` 或 renderer；正常 `AlertOutbox` 读取会独立重校验当前完整规范事件。只有全部监控行都是与提醒 identity 匹配的 `alert.created` 时才允许降级；存在其他或不匹配事件时会在数据丢失前封闭失败。
- 追加迁移 `0007_plan_web_state` 紧随 `0006_monitor_event`。它只新增 `plan_version_review` 和可空 `plan_activation_state`，为既有计划版本回填 `[]` 审核问题，把既有活动指针、revision 和启用时间复制到启用状态投影，并使用各股票最早的版本创建时间为其余仅有草稿的股票建立 revision `0` 的非活动状态。只有每条审核仍是可重建的规范 `[]`，且每条启用状态精确匹配旧活动指针或 revision `0` 的最早版本回填时才允许降级；任何已审核或已停用状态都会在 DDL 前封闭失败。它不重写 `plan_version.payload_json`、计划哈希、Schema v1 计划、历史回测结果或任何既有事件 identity。
- `MonitorEventLog` 在 identity 读取前串行化 SQLite 写者，分配正数全局序号，保存规范、有界载荷 JSON，并只 flush 而不提交。相同 UUID 的精确重放幂等，语义冲突则拒绝。高水位不受事件保留删除影响；回放会按 7 天截止时间校验完整请求范围，再返回最多 1,000 个连续事件。提醒确认仍只修改 `alert_event.acknowledged_at`，追加一条 `ALERT_ACKNOWLEDGED` 审计和一条 `alert.acknowledged` 监控事件，绝不改变持仓，也不记录投递成功。
- WEBF11 只新增位于 `0007_plan_web_state` 之后的追加迁移 `0008_market_index_monitor_event`。它预检 `event_type`，复制现有七列，并在替换原表前校验行数，再使用允许 `market.index.updated` 的 CHECK 约束。若存在任何 `market.index.updated` 行，因旧契约无法无损表示该事件，降级必须在 DDL 前拒绝。既有行、全局序号、UUID identity 以及冻结的 `0006_monitor_event` 数据保持不变；该事件通过同一个全局游标持久化和回放，而不是使用并行序号。

### 低吸事件游标与仓储契约

- `last_processed_bucket_end` 必须保存为规范 `Asia/Shanghai` ISO 8601 文本，并表示交易时段内完整 5 分钟边界。它不得早于 `five_minute_bucket_end(started_at)`，且必须进入重载 DTO、事件审计详情和规范事件审计哈希。
- 事件判断只消费 `(last_processed_bucket_end, target.bucket_end]`。仓储修订拒绝游标倒退以及同游标上的任何状态变化；同游标且状态完全一致是幂等无操作。更晚游标可以应用严格创新低清零、有界进度、饱和、提醒或关闭。
- 持久化生命周期只能向前：`ACTIVE` 可以保持 `ACTIVE` 或变为 `ALERTED`/`CLOSED`；`ALERTED` 可以保持 `ALERTED` 或变为 `CLOSED`；`CLOSED` 是终态。`ALERTED` 必须携带 `BUY_CORE_READY`/`BUY_TACTICAL_READY`，`ACTIVE` 禁止携带；提醒信号之后不能清除或替换。已提醒事件关闭后保留原信号。
- 重放字节等价的初始 `start` 无害；持久化进度推进后重放原始 start 会返回当前记录而不倒退。在记录仍为初始状态时，冲突的 `episode_low_fen` 或游标会抛出 `EPISODE_IDENTITY_CONFLICT`，而不是掩盖确定性分歧。
- 追加迁移 `0003_episode_cursor` 紧随 `0002_ai_provider_configuration`，新增 `VARCHAR(40) NOT NULL`。全新数据库或事件表为空的 `0002` 数据库可正常升级。由于旧游标无法无损推断，任何已有数据的 `0002` `zone_episode` 都必须在 DDL 前被发现并使升级原子失败，其 revision、结构和数据行保持不变；操作人员必须先备份，并明确清理/重建事件状态后再重试。

### 行情历史与参考数据仓储契约

- `MarketHistoryRepository` 持久化规范化分钟、日线值和确定性 5 分钟 K 线；`MarketReferenceRepository` 持久化交易日历与实际涨跌停值。两个仓储都不执行供应商调用、单位缩放、聚合、指标计算或收盘核对。
- 精确 identity 分别为分钟 `(symbol, bar_end)`、5 分钟 `(symbol, bar_end, formula_version)`、日线 `(symbol, trade_date, is_official)`、日历 `(exchange, cal_date)`、涨跌停 `(symbol, trade_date)` 和最新价 `symbol`。
- 分钟、日线和涨跌停行使用 `received_at` 确定修正顺序：较新事实覆盖，较旧事实忽略，相同重复无害，同回执冲突抛出 `MARKET_DATA_IDENTITY_CONFLICT`。由于 Schema 没有日历回执版本，后续权威日历调用会覆盖相同日历 identity。
- 5 分钟 identity 不可变，并拒绝冲突事实；仓储在持久化前校验交易时段内的 5 分钟边界。
- 每个规范化写批次都是最多 1,000 行的可重复 list/tuple。历史读取必须提供明确的闭区间日期/时间范围；所有历史/参考数据读取在返回行数超过 10,000 时失败关闭。
- 持久化分钟和推进 `latest_quote` 在调用方拥有的同一事务中完成。更新的 K 线优先；修正同一 K 线时必须具有更新的回执。`latest_quote` 始终是可替换投影，不是第二套报价历史。
- 判断上下文组装必须使用明确的闭区间边界读取 `minute_bar`，范围从当前交易日首个规范分钟结束时间到判断周期结束时间；超过 240 行或序列不精确时拒绝。不可变结果作为 `current_day_minutes` 提供。`latest_quote` 无法提供周期内穿越所需的此前观测，也无法提供触价 provenance 所需的历史。不得新增第二张报价历史表。
- 连续盘中临时日线聚合与 15:00 临时收盘共享现有 `(symbol, trade_date, is_official=False)` identity，并且仅在 `received_at` 更新时推进；官方行保留独立的 `is_official=True` identity。不得新增压力状态表。T023 在纯编排期间从 `current_day_minutes` 临时推导 `pressure_touch_at`。
- T018 暴露这些 Session 绑定仓储用于确定性持久化测试。应用 `UnitOfWork` 接线延后到负责原子运行时事务流的 T032；任何调用方都不得在数据库事务内执行 Tushare 请求。

## 代码风格

```python
class UnitOfWork(Protocol):
    plans: PlanRepository
    idempotency: IdempotencyRepository
    positions: PositionRepository
    episodes: EpisodeRepository
    risk: RiskRepository
    evaluations: EvaluationRepository
    health: HealthRepository
    events: MonitorEventLog
    alerts: AlertOutbox

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

仓储暴露领域操作而不是原始 Session。数据库事务中不得包含 Tushare、AI 或 Webhook 网络调用。

## 测试策略

- 测试空数据库和历史版本迁移。
- 验证单活动计划、判断标识、提醒标识和幂等键的唯一约束。
- 覆盖持仓批次、部分卖出、底仓/机动仓、T+1、低吸事件、风险状态、健康和审计。
- 覆盖事件游标 start/reload/revise/restart、精确审计哈希链、单向生命周期、同游标重放、冲突初始 start 和游标倒退。
- 覆盖 `0003_episode_cursor` 从全新及空 `0002` 数据库升级，以及对已有事件状态的 `0002` 数据库在 DDL 前原子拒绝。
- 模拟崩溃/重启，确认已提交事务可恢复、未提交事务回滚。
- 在计划保存、后继版本分配、查询、JSON/YAML 导入、启用与停用之间分别重启；验证审核问题、明确的导入股票绑定、幂等回放、不可变版本状态、可空活动 identity 和启用 revision 均被保留。
- 并发激活和更新必须稳定返回 409 冲突。
- 测试重复行情和延迟恢复的幂等写入。
- 覆盖精确、有缺口、超限和仅有最新报价的判断历史读取，以及临时/官方日线 identity 分离。
- 覆盖 `0008_market_index_monitor_event` 升级/降级：事件类型预检、七列复制、行数校验、既有序号与 identity 保留、`market.index.updated` 的持久化/回放，以及存在板块指数事件时在 DDL 前拒绝有损降级。
- 在 WAL 写入期间执行在线备份、`PRAGMA integrity_check`、恢复冒烟测试，并只保留最近 30 个成功备份。

## 边界

- 始终：每次打开数据库连接时启用外键和 WAL。busy timeout 默认为 5,000 毫秒，显式覆盖值限定为 1–60,000 毫秒。
- 始终：使用显式 SQLAlchemy 事务控制，使迁移 DDL 与应用写入原子提交或回滚；事务保持短小。
- 始终：参数化查询，领域使用前校验 JSON。
- 始终：审计计划激活、AI 配置元数据、持仓和提醒确认。
- 先确认：破坏性迁移、缩短保留期或改用 SQLite 之外的存储。
- 禁止：直接复制正在使用的 WAL 数据库文件作为备份。
- 禁止：把 `config/app.yaml` 中的供应商凭证复制到 SQLite。
- 禁止：因为提醒产生或确认而修改仓位。
- 禁止：在数据库事务内调用网络。

## 验收标准

- 重启后已保存/导入计划版本、审核问题、活动或非活动启用状态、持仓、事件、风险和提醒去重状态完整保留。
- 每只股票不可能存在两个活动计划版本。
- 同一完整 5 分钟判断不能插入第二条记录。
- 人工成交遵守手数、最大仓位、仓位类型、剩余数量和 T+1。
- 在线备份通过校验并可恢复成可读取数据库。
- 数据库事务不跨越外部接口调用。

## 待确认事项

无阻断事项。数据保留期作为应用配置，并提供安全默认值。

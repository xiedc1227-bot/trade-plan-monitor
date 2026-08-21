# 规格：strategy-state（策略状态与持久化）

> 中文审阅版。英文权威版为 `SPEC-strategy-state.md`；两份文档必须保持语义一致。

## 目标

使用一个 SQLite WAL 数据库持久化单用户监控状态：计划版本、活动计划、人工持仓批次、T+1、低吸事件、风险状态、判断幂等记录、行情与参考数据、健康状态和审计记录。

程序重启后不能丢失状态或重复提醒。提醒确认不等于成交，仓位只能通过人工成交/减仓操作改变。

## 技术栈

- Python 3.11+
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
active_plan(symbol PRIMARY KEY, plan_version_id UNIQUE, activated_at, revision)
position_lot(id, symbol, bucket, quantity, remaining_qty, acquired_trade_date, cost_fen, related_alert_id, closed_at)
zone_episode(id, plan_hash, symbol, zone, started_at, episode_low_fen, bars_since_low, status, alerted_signal)
risk_state(symbol PRIMARY KEY, plan_hash, status, breach_trade_date, prior_close_fen, revision, updated_at)
evaluation_ledger(plan_hash, symbol, bucket_end, formula_version, result_hash, evaluated_at, UNIQUE(...))
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

### 计划仓储与工作单元契约

- `save_draft` 接受类型化 `TradePlan`，重新执行跨字段保存校验，并在同一事务中保存源文本、规范 JSON、内容哈希、不可变版本和 `PLAN_DRAFT_SAVED` 审计。已有 `(plan_id, version)` 绝不覆盖。
- 激活要求 `PlanValidationResult.can_activate` 成功。不存在活动记录时逻辑 revision 为 `0`；首次激活要求 `expected_revision=0` 并创建 revision `1`，此后每次激活都要求精确匹配当前 revision 并只递增一次。SQLite 写者在激活读取前串行化，条件 upsert 与数据库键共同保证每只股票仅有一个活动版本。
- 新幂等键创建 `PENDING`。相同键和哈希在待处理时产生 `IDEMPOTENCY_IN_PROGRESS`；进入 `COMPLETED` 后重放已保存的规范响应。相同键对应不同 SHA-256 请求哈希时始终产生 `IDEMPOTENCY_KEY_REUSED`。
- 仓储失败暴露稳定错误码，例如 `PLAN_VERSION_EXISTS`、`PLAN_SAVE_BLOCKED`、`PLAN_ACTIVATION_BLOCKED`、`PLAN_VERSION_NOT_FOUND`、`CONFLICT`、`IDEMPOTENCY_KEY_REUSED`、`IDEMPOTENCY_IN_PROGRESS` 和 `IDEMPOTENCY_CLAIM_NOT_FOUND`；后续传输适配器将其映射为 HTTP，但不暴露 SQL 或原始 Session 细节。
- `UnitOfWork` 拥有一个显式短事务。调用方必须调用 `commit()` 才能持久化；退出上下文时未提交则回滚。其公共协议只暴露仓储及 `commit()`/`rollback()`，绝不暴露 SQLAlchemy Session。

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

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

仓储暴露领域操作而不是原始 Session。数据库事务中不得包含 Tushare、AI 或 Webhook 网络调用。

## 测试策略

- 测试空数据库和历史版本迁移。
- 验证单活动计划、判断标识、提醒标识和幂等键的唯一约束。
- 覆盖持仓批次、部分卖出、底仓/机动仓、T+1、低吸事件、风险状态、健康和审计。
- 模拟崩溃/重启，确认已提交事务可恢复、未提交事务回滚。
- 并发激活和更新必须稳定返回 409 冲突。
- 测试重复行情和延迟恢复的幂等写入。
- 在 WAL 写入期间执行在线备份、`PRAGMA integrity_check`、恢复冒烟测试，并只保留最近 30 个成功备份。

## 边界

- 始终：每次打开数据库连接时启用外键和 WAL。busy timeout 默认为 5,000 毫秒，显式覆盖值限定为 1–60,000 毫秒。
- 始终：使用显式 SQLAlchemy 事务控制，使迁移 DDL 与应用写入原子提交或回滚；事务保持短小。
- 始终：参数化查询，领域使用前校验 JSON。
- 始终：审计计划激活、AI 配置元数据、持仓和提醒确认。
- 先确认：破坏性迁移、缩短保留期或改用 SQLite 之外的存储。
- 禁止：直接复制正在使用的 WAL 数据库文件作为备份。
- 禁止：在 SQLite 中保存 AI Key 或 `TUSHARE_TOKEN`。
- 禁止：因为提醒产生或确认而修改仓位。
- 禁止：在数据库事务内调用网络。

## 验收标准

- 重启后活动计划、持仓、事件、风险和提醒去重状态完整保留。
- 每只股票不可能存在两个活动计划版本。
- 同一完整 5 分钟判断不能插入第二条记录。
- 人工成交遵守手数、最大仓位、仓位类型、剩余数量和 T+1。
- 在线备份通过校验并可恢复成可读取数据库。
- 数据库事务不跨越外部接口调用。

## 待确认事项

无阻断事项。数据保留期作为应用配置，并提供安全默认值。

# Spec: strategy-state (Strategy State and Persistence)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-strategy-state.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Persist single-user monitoring state in one SQLite WAL database: plan versions, active plans, manual position lots, T+1, low-zone episodes, risk state, evaluation idempotency, market/reference data, health, and audit records.

Restart must not lose state or duplicate alerts. Alert acknowledgement is not a fill; positions change only through explicit manual fill or reduction operations.

## Tech Stack

- Python 3.14.x (`>=3.14,<3.15`)
- SQLite WAL as the only database
- SQLAlchemy 2 and Alembic
- Pydantic 2 repository DTOs
- SQLite online backup API and integrity checks

Do not introduce PostgreSQL, Redis, Parquet, distributed locks, primary/replica, or high-availability components.

## Commands

```powershell
python -m pytest tests/unit/test_strategy_state.py -q
python -m pytest tests/integration/test_sqlite_repositories.py -q
python -m pytest tests/integration/test_sqlite_backup.py -q
python -m ruff check src/trade_plan_monitor/state tests/unit/test_strategy_state.py tests/integration
```

## Project Structure

```text
src/trade_plan_monitor/state/
├── database.py       # Engine, Session, and WAL configuration
├── events.py         # Typed global monitor-event ledger
├── models.py         # SQLAlchemy persistence models
├── repositories.py   # Narrow repository interfaces and queries
├── unit_of_work.py   # Short transaction boundaries
├── migrations/       # Alembic migrations
└── backup.py         # Online backup, verification, and retention
tests/unit/
└── test_strategy_state.py
tests/integration/
├── test_sqlite_repositories.py
└── test_sqlite_backup.py
```

## State Model

Core logical tables:

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

The baseline migration also creates the approved cross-module support tables:

```text
request_idempotency(idempotency_key PRIMARY KEY, request_hash, status, response_code, response_json, created_at, updated_at)
latest_quote(symbol PRIMARY KEY, price_fen, bar_end, received_at)
alert_event(id PRIMARY KEY, sequence UNIQUE, dedup_key UNIQUE, payload_json, message_text, created_at, acknowledged_at)
monitor_event(id PRIMARY KEY, sequence UNIQUE, event_type, schema_version, aggregate_id, payload_json, occurred_at)
monitor_sequence(singleton_id PRIMARY KEY CHECK(singleton_id = 1), last_sequence CHECK(last_sequence >= 0))
delivery_attempt(id PRIMARY KEY, event_id, channel, attempt, status, response_code, next_retry_at, delivered_at, error_code, UNIQUE(event_id, channel, attempt))
```

`ai_provider_configuration` contains only bounded non-secret settings and lookup references. It never stores an API-key value or derived authorization header; configured/masked status is derived from the secret boundary.

`notification-outbox` owns alert behavior, but its tables use the same unit of work. Logical `ohlc_fen` expands to `open_fen`, `high_fen`, `low_fen`, and `close_fen`. Prices are integer fen, exact decimal yuan values are stored as canonical decimal text to avoid SQLite binary-float loss, dates use ISO calendar values, and source/receipt timestamps use canonical timezone-aware ISO 8601 text.

### Position Lots

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

Sellable quantity derives from the trading calendar and acquisition date. Manual buy recording requires a core/tactical bucket and quantity. Entering from an alert may prefill the form but cannot submit automatically.

### Optimistic Concurrency and Idempotency

- Mutable records carry an integer `revision`.
- REST writes carry an expected revision and `Idempotency-Key`.
- The idempotency key and request hash are claimed atomically; the same key with a different request returns 422.
- A revision conflict returns `409 CONFLICT` and the current version.
- Plan activation, state transition, evaluation ledger, audit, and alert enqueue use one short transaction when required.

For the T038 Web boundary, position creation and reduction remain explicit application-service commands over this repository. The HTTP adapter requires one bounded idempotency key and expected position revision, while the application service resolves the active plan's 100-share board lot and maximum quantity, serializes the write, applies T+1/remaining-quantity checks, and inserts the position audit atomically. A new lot has revision `0`; its later durable revision is derived as `(quantity - remaining_qty) / 100`. A closure receipt binds applied quantity and trade date to the exact before/after remaining quantities, so revision checks need no inferred or invented storage field. An optional `related_alert_id` is provenance only: it may prefill an explicit command but cannot submit it. Alert acknowledgement uses its separate outbox transaction, maps unacknowledged/acknowledged state to revisions `0`/`1`, and keeps an already acknowledged revision `1` as a no-op; it cannot call any position operation. A diagnostic evaluation applies no repository transition, evaluation-ledger claim, alert enqueue, or position change; only an explicitly reported diagnostic audit is permitted.

From T032, `evaluation_ledger` uses the lossless primary key `(plan_hash, symbol, evaluation_kind, target_value, formula_version)`. `INTRADAY` stores a canonical Shanghai five-minute timestamp in `target_value`; `OFFICIAL_CLOSE` stores only its ISO trade date, so the intraday 15:00 target cannot collide with that date's official-close identity. Migration `0005_evaluation_kind` backfills every earlier row as `INTRADAY`, preserves result/evaluation facts, and refuses downgrade while any official-close identity exists. The repository requires an explicit kind plus exactly one typed target and exposes mutually exclusive `bucket_end` / `official_trade_date` fields.

`EvaluationRepository.has_claim(...)` is a read-only exact-identity lookup over the same five key fields. T033 uses it only to short-circuit provider and decision work for an already committed official-close date; it neither compares result hashes nor converts an `EvaluationIdentityConflictError` into a duplicate.

### Plan Repository and Unit-of-Work Contract

- `save_draft` accepts a typed `TradePlan`, reruns cross-field save validation, and stores the source, canonical JSON, content hash, immutable version, bounded review issues, and `PLAN_DRAFT_SAVED` audit in one transaction. It also creates the symbol's inactive `plan_activation_state` at revision `0` when that state does not yet exist. An existing `(plan_id, version)` is never overwritten. A base-version save verifies immutable plan/symbol identity and obtains the next version for that `plan_id` only after the idempotency claim has serialized the SQLite writer; the application service, not the browser, constructs the successor before saving it. The Web boundary caps plan versions and returned revisions at JavaScript's safe-integer maximum and rejects an unsafe imported document or exhausted successor before commit; this does not narrow or rewrite the persisted Schema v1 domain. Version-detail reads join the exact source and review record, while stable paginated collection reads return lightweight summaries derived from those validated records, so save, query, and JSON/YAML import provenance survives restart without returning every large document in a page.
- Activation requires a successful `PlanValidationResult.can_activate`, including every persisted review issue. An absent activation state has logical revision `0`; the first activation requires `expected_revision=0` and creates revision `1`, while every later activation or deactivation requires the exact current `plan_activation_state.revision` and increments it once. Activation synchronizes the nullable durable state with the `active_plan` pointer; deactivation removes that active pointer, retains the inactive state with its new revision, marks the formerly active immutable version `SUPERSEDED`, and appends its audit and `plan.deactivated` event in the same transaction. SQLite writers are serialized before activation-state reads, and the conditional writes plus database keys keep one active version per symbol.
- A new idempotency key creates `PENDING`. The same key and hash while pending produces `IDEMPOTENCY_IN_PROGRESS`; after `COMPLETED`, it replays the canonical stored response. The same key with a different SHA-256 request hash always produces `IDEMPOTENCY_KEY_REUSED`. Stored canonical responses are bounded to 4 MiB so a complete plan-version response can be replayed without creating an unbounded persistence surface.
- Repository failures expose stable codes such as `PLAN_VERSION_EXISTS`, `PLAN_SAVE_BLOCKED`, `PLAN_ACTIVATION_BLOCKED`, `PLAN_VERSION_NOT_FOUND`, `CONFLICT`, `IDEMPOTENCY_KEY_REUSED`, `IDEMPOTENCY_IN_PROGRESS`, and `IDEMPOTENCY_CLAIM_NOT_FOUND`; later transport adapters map them to HTTP without exposing SQL or raw Session details.
- `UnitOfWork` owns one explicit short transaction. Callers must invoke `commit()` for durability; leaving the context without a commit rolls back. Its public protocol exposes repositories plus `commit()`/`rollback()`, never the SQLAlchemy Session.
- `UnitOfWork.events` exposes the session-bound `MonitorEventLog`, while `UnitOfWork.alerts` exposes `AlertOutbox` over that same log and Session. Plan activation, position mutation, symbol/provider health mutation, evaluation snapshot, alert creation, acknowledgement audit, and their corresponding events therefore commit or roll back together. The closed business vocabulary is `symbol.snapshot.updated`, `symbol.health.updated`, `alert.created`, `alert.acknowledged`, `plan.extraction.updated`, `plan.activated`, `plan.deactivated`, `position.updated`, `ai.provider.updated`, `system.health.updated`, and the approved `market.index.updated`. Injected application services that own extraction, deactivation, or AI-provider persistence must append their listed event in the owning mutation transaction; the persistence boundary does not invent those services.
- Append-only migration `0006_monitor_event` follows `0005_evaluation_kind`, replaces `alert_sequence` with the sole `monitor_sequence`, and backfills every historical `alert_event` as `alert.created` with the same UUID and sequence. Existing alert sequences therefore remain stable while later alert rows may be sparse within the global domain. Before any DDL, one revision-local frozen v1 validator rejects any historical alert row that is not safe and canonical under the migration's original contract: it verifies exact payload/object shapes, UUID/dedup/symbol/signal-action identity, closed condition/evidence/fact types, three-valued evidence partitions, node/fact/numeric budgets, action/zone/next-step semantics, exact Shanghai timestamp arithmetic, bounded control-safe text, deterministic Chinese rendering, and the old sequence high-water. The revision is self-contained and never imports the evolving application `AlertPayload`, `AlertEvent`, or renderer; normal `AlertOutbox` reads independently revalidate the current complete canonical event. Downgrade is allowed only when every monitor row is an identity-matched `alert.created`; any other or unmatched event fails closed before data loss.
- Append-only migration `0007_plan_web_state` follows `0006_monitor_event`. It adds only `plan_version_review` and nullable `plan_activation_state`, backfills `[]` review issues for existing plan versions, copies existing active pointers, revisions, and activation times into the activation-state projection, and creates inactive revision `0` state for every remaining draft-only symbol using its earliest version creation time. Downgrade is allowed only when every review is still the reconstructible canonical `[]` and every activation state exactly matches either the old active pointer or the revision-`0` earliest-version backfill; any reviewed or deactivated state fails closed before DDL. It does not rewrite `plan_version.payload_json`, plan hashes, Schema v1 plans, historical backtest results, or any existing event identity.
- `MonitorEventLog` serializes SQLite writers before identity reads, allocates positive global sequences, stores canonical bounded payload JSON, and flushes without committing. Exact UUID replay is idempotent; conflicting semantics are rejected. The high-water mark survives event retention, and replay validates the entire requested range against its seven-day cutoff before returning an at-most-1,000-event contiguous page. Alert acknowledgement still changes only `alert_event.acknowledged_at`, appends one `ALERT_ACKNOWLEDGED` audit plus one `alert.acknowledged` monitor event, and never changes a position or records delivery success.
- WEBF11 adds only append-only migration `0008_market_index_monitor_event` after `0007_plan_web_state`. It prechecks `event_type`, copies all seven existing columns, and verifies row count before replacing the original table with the approved `market.index.updated` CHECK value. If any `market.index.updated` row exists, downgrade is refused before DDL because the prior contract cannot represent it losslessly. Existing rows, global sequences, UUID identities, and frozen `0006_monitor_event` data remain unchanged; the event is stored and replayed through the same global cursor rather than a parallel sequence.

### Low-Zone Episode Cursor and Repository Contract

- `last_processed_bucket_end` is required canonical `Asia/Shanghai` ISO 8601 text for a complete session-contained 5-minute boundary. It cannot precede `five_minute_bucket_end(started_at)` and participates in reload DTOs, episode audit details, and the canonical episode audit hash.
- Episode evaluation consumes only `(last_processed_bucket_end, target.bucket_end]`. Repository revision rejects cursor regression and any state change at the same cursor; an exact same-cursor state is an idempotent no-op. A later cursor may apply a strict-lower reset, bounded progress, saturation, alerting, or closure.
- The durable lifecycle is forward-only: `ACTIVE` may remain `ACTIVE` or become `ALERTED`/`CLOSED`; `ALERTED` may remain `ALERTED` or become `CLOSED`; `CLOSED` is terminal. `BUY_CORE_READY`/`BUY_TACTICAL_READY` is required for `ALERTED`, forbidden for `ACTIVE`, and cannot later be cleared or replaced. A closed alerted episode retains its original signal.
- Replaying a byte-equivalent initial `start` is harmless, and replaying the original start after durable progress returns the current record without rewinding it. While the record is still initial, a conflicting `episode_low_fen` or cursor raises `EPISODE_IDENTITY_CONFLICT` instead of hiding deterministic divergence.
- Append-only migration `0003_episode_cursor` follows `0002_ai_provider_configuration` and adds `VARCHAR(40) NOT NULL`. A fresh database or an empty `0002` episode table upgrades normally. Because a legacy cursor cannot be inferred losslessly, any populated `0002` `zone_episode` is detected before DDL and the upgrade fails atomically with its revision, schema, and rows unchanged; operators must back up and explicitly clear/rebuild episode state before retrying.

### Market History and Reference Repository Contract

- `MarketHistoryRepository` persists normalized minute and daily values plus deterministic 5-minute bars. `MarketReferenceRepository` persists trading-calendar and actual daily-limit values. Neither repository performs provider calls, scaling, aggregation, indicator calculation, or close reconciliation.
- Exact identities are minute `(symbol, bar_end)`, 5-minute `(symbol, bar_end, formula_version)`, daily `(symbol, trade_date, is_official)`, calendar `(exchange, cal_date)`, daily limit `(symbol, trade_date)`, and latest quote `symbol`.
- Minute, daily, and daily-limit rows use `received_at` as their correction order: newer facts replace, older facts are ignored, identical duplicates are harmless, and equal-receipt conflicts raise `MARKET_DATA_IDENTITY_CONFLICT`. A later authoritative calendar call replaces the same calendar identity because the schema has no calendar receipt version.
- Five-minute identities are immutable and reject conflicting facts. The repository validates a session-contained 5-minute boundary before persistence.
- Each normalized write batch is a repeatable list/tuple of at most 1,000 rows. History reads require an explicit inclusive date/time range and every history/reference read fails closed above 10,000 returned rows.
- Persisting a minute and advancing `latest_quote` occur in the same caller-owned transaction. A newer bar wins; a correction for the same bar requires a newer receipt. `latest_quote` remains a replaceable projection, not a second quote-history stream.
- Decision-context assembly reads `minute_bar` with explicit inclusive bounds from the first canonical minute end of the current trading date through the evaluation bucket end and rejects more than 240 rows or any non-exact sequence. The immutable result is supplied as `current_day_minutes`. `latest_quote` cannot supply the prior observations required for in-bucket crossing or the history required for touch provenance. No second quote-history table is added.
- Successive intraday provisional daily aggregates and the 15:00 provisional close share the existing `(symbol, trade_date, is_official=False)` identity and advance only on a newer `received_at`; the official row keeps the separate `is_official=True` identity. No pressure-state table is added. T023 derives `pressure_touch_at` transiently from `current_day_minutes` during pure orchestration.
- T018 exposes these session-bound repositories for deterministic persistence tests. Application `UnitOfWork` wiring is deferred to T032, which owns the atomic runtime transaction flow; no caller may perform a Tushare request inside the database transaction.

## Code Style

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

Repositories expose domain operations rather than raw Session access. A database transaction never contains a Tushare, AI, or webhook network call.

## Testing Strategy

- Test migration from an empty database and historical versions.
- Verify unique constraints for active plans, evaluation identities, alert identities, and idempotency keys.
- Cover position lots, partial sells, core/tactical buckets, T+1, low-zone episodes, risk state, health, and audit.
- Cover episode cursor start/reload/revise/restart, exact audit-hash chaining, forward-only lifecycle, same-cursor replay, conflicting initial start, and cursor regression.
- Cover `0003_episode_cursor` upgrades from fresh and empty `0002` databases plus atomic pre-DDL refusal for populated `0002` episode state.
- Simulate crash and restart to confirm committed recovery and uncommitted rollback.
- Restart independently between plan save, successor-version allocation, query, JSON/YAML import, activation, and deactivation; verify review issues, explicit import-symbol binding, idempotent replay, immutable version status, nullable active identity, and activation revision are preserved.
- Concurrent activation and update must return stable 409 conflicts.
- Test idempotent writes for duplicate market data and delayed recovery.
- Cover exact, gapped, oversized, and latest-quote-only decision-history reads plus provisional/official daily identity separation.
- Cover `0008_market_index_monitor_event` upgrade/downgrade: event-type precheck, seven-column copy, row-count verification, preservation of existing sequences and identities, durable `market.index.updated` persistence/replay, and pre-DDL refusal when index events make downgrade lossy.
- Run online backup during WAL writes, `PRAGMA integrity_check`, restore smoke tests, and retain only the latest 30 successful backups.

## Boundaries

- Always: enable foreign keys and WAL on every opened database connection. The default busy timeout is 5,000 ms and explicit overrides are bounded to 1–60,000 ms.
- Always: use explicit SQLAlchemy transaction control so migration DDL and application writes commit or roll back atomically; keep transactions short.
- Always: use parameterized queries and validate JSON before domain use.
- Always: audit plan activation, AI configuration metadata, positions, and alert acknowledgement.
- Ask first: destructive migration, shorter retention, or storage other than SQLite.
- Never: copy an in-use WAL database file directly as a backup.
- Never: store an AI key or `TUSHARE_TOKEN` in SQLite.
- Never: alter a position because an alert was created or acknowledged.
- Never: call the network inside a database transaction.

## Success Criteria

- Restart preserves saved/imported plan versions, review issues, active or inactive activation state, positions, episodes, risk state, and alert deduplication state.
- Two active plan versions cannot exist for one symbol.
- The same complete 5-minute evaluation cannot create a second ledger entry.
- Manual fills respect board lot, maximum position, bucket, remaining quantity, and T+1 rules.
- An online backup passes verification and restores to a readable database.
- Database transactions do not span external calls.

## Open Questions

None blocking. Data-retention windows are application configuration with safe defaults.

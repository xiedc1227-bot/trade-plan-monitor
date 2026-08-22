# Spec: monitor-runtime (Monitoring Runtime)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-monitor-runtime.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Run one local, long-lived monitoring process that schedules Tushare collection for at most 10 active symbols, recovers gaps, evaluates each newly completed 5-minute bucket exactly once, reconciles official closes, persists state/alerts transactionally, exposes honest health, and shuts down cleanly.

The runtime must remain useful when the browser is closed. AI extraction runs in a separately bounded path and can never delay market-data deadlines or rule evaluation.

## Tech Stack

- Python 3.14.x (`>=3.14,<3.15`)
- `asyncio` application lifecycle
- Dedicated `ThreadPoolExecutor(max_workers=2)` for synchronous Tushare SDK calls
- Separate bounded async semaphore for AI HTTP calls
- FastAPI lifespan integration
- SQLite-backed schedules/state through `strategy-state`
- Structured standard-library logging with redaction

No Celery, Redis, APScheduler, distributed queue, worker cluster, or high-availability coordinator is required.

## Commands

```powershell
python -m pytest tests/unit/test_monitor_runtime.py -q
python -m pytest tests/integration/test_ten_symbol_runtime.py -q
python -m ruff check src/trade_plan_monitor/runtime tests/unit/test_monitor_runtime.py tests/integration/test_ten_symbol_runtime.py
python -m trade_plan_monitor monitor --once --config config/app.yaml
```

## Project Structure

```text
src/trade_plan_monitor/runtime/
├── clock.py           # Injected real/fake clock
├── scheduler.py       # Session-aware minute and close deadlines
├── request_control.py # Pacing, bounded concurrency, retry/cooldown
├── recovery.py        # Startup/current-day gap repair
├── symbol_service.py  # One-symbol evaluation orchestration
├── health.py          # Provider/system/symbol health state
├── service.py         # Runtime lifecycle and coordination
└── cli.py             # validate/once/run/replay/backup commands
tests/unit/
└── test_monitor_runtime.py
tests/integration/
└── test_ten_symbol_runtime.py
```

## Startup Sequence

1. Load and validate application configuration and secret references.
2. Open SQLite, apply approved migrations, and verify basic integrity.
3. Load active plan versions and reject more than 10 active symbols.
4. Probe Tushare realtime-minute, current-day-minute, calendar, daily-limit, and daily-bar capabilities independently.
5. Refresh/cache the current and next calendar horizon and current-day actual price limits.
6. During an open trading day, recover current-day minutes per active symbol through `rt_min_daily`, serially and idempotently.
7. Build the next market-minute deadline from the canonical session clock.
8. Start the Web application even when provider capabilities are blocked; expose degraded/read-only health and suppress actionable monitoring.

## Realtime Schedule

- One `rt_min(freq="1MIN")` batch includes all enabled symbols, capped at 10, after each completed continuous-trading minute plus a configurable 12-second grace.
- Tushare source timestamps are normalized by `market-data`; the scheduler uses canonical exchange intervals, not raw labels.
- There is no separate quote poll. The newest completed-minute close is the display price.
- Returned rows are validated per symbol. A missing/malformed symbol blocks only that symbol.
- Complete 5-minute buckets are evaluated exactly once; incomplete buckets immediately suppress actionable evaluation.
- Two consecutive incomplete required buckets mark the symbol `DEGRADED`, but the first incomplete bucket is already a buy-alert blocker.
- Dynamic plan activation/disable changes the next batch without process restart.

### T028 Session Scheduler Contract

- `Clock` exposes only `now()` and cancellable `sleep_until(deadline)`; `SystemClock` uses aware `Asia/Shanghai` wall time, while tests inject a fake clock. The scheduler creates no background task and cancellation propagates to its owner.
- `MarketSessionScheduler` reuses the canonical `market-data` minute ends: 09:31–11:30 and 13:01–15:00. Each known-open weekday therefore has exactly 240 unique `REALTIME_MINUTE` deadlines, each at `bar_end + grace`; opening auction, lunch, weekends, known closed days, and post-close intervals contain no realtime deadline.
- Weekends are deterministically closed. Every weekday requires the injected calendar lookup to return exactly `True` or `False`; `None` stops forward scanning and returns no deadline, so unknown calendar state fails closed rather than being skipped.
- `next_deadline()` returns the first deadline at or after the injected current time. Its optional `after` timestamp is exclusive and advances an already handled deadline exactly once. Forward calendar search is bounded to 366 dates and returns `None` at the bound, including `date.max`.
- Official-close deadlines use a non-empty tuple of strictly increasing, whole-minute local times after 15:00, defaulting exactly to 15:20, 16:00, and 17:00. They are identified as attempts 1, 2, and 3 and never masquerade as realtime minutes.
- Grace is a non-negative `timedelta` and must keep the final 15:00 realtime deadline strictly before the first official-close attempt. This preserves one timestamp identity per deadline and rejects collisions, reordered close attempts, cross-date deadlines, and overflow before scheduling starts.
- T028 performs only deterministic deadline construction and injected waiting. It does not fetch data, create a Tushare executor, apply retry/rate-limit policy, persist `CLOSE_PENDING`, evaluate rules, or publish events; those remain T029 and later tasks.

## Recovery and Close Reconciliation

- Startup recovery calls `rt_min_daily` once per active symbol, with at most one recovery call active at a time.
- Later recovery targets only detected gaps and yields to the next scheduled realtime batch.
- Upserts make duplicate/reordered recovery data harmless.
- Each complete intraday cutoff may refresh the provisional daily aggregate used for momentum evidence; the aggregate through the final minute is the provisional close. Neither is official.
- Official `daily` reconciliation attempts are configurable, defaulting to approximately 15:20, 16:00, and 17:00.
- Close-risk state advances only when the returned official row matches the current trading date.
- If unavailable, persist `CLOSE_PENDING` and retry on the next startup before evaluating the next trading day's close transition.

## Request Control

Default controls:

```yaml
requestControl:
  tushareExecutorWorkers: 2
  tushareMaxConcurrency: 2
  minIntervalMs: 1000
  jitterMs: 250
  timeoutSeconds: 15
  inCycleRetries: 2
  symbolBackoffSeconds: [30, 60, 120, 300]
  sharedRateLimitCooldownSeconds: 300
aiControl:
  maxConcurrentExtractions: 1
  queueLimit: 5
```

- Permission/access denial becomes `BLOCKED_PERMISSION` and is not blindly retried.
- Provider quota/rate-limit response starts shared cooldown with no immediate retry storm.
- Ordinary transient failures use bounded retry and later-cycle backoff.
- Tushare network calls run in the executor; database work remains on the application path outside provider threads.
- AI work has a separate queue/semaphore and lower operational priority than monitoring.

## Health Contract

Provider capabilities: `UNVERIFIED`, `READY`, `BLOCKED_PERMISSION`, `RATE_LIMITED`, `ERROR`.

Per-symbol health: `STARTING`, `LIVE`, `STALE`, `GAPPED`, `DEGRADED`, `BLOCKED`, `CLOSE_PENDING`.

Health exposes timestamps/ages, last completed minute, latest evaluation, gaps, next poll, next retry, cooldown, latency, error code, executor utilization, database/WAL status, and alert-delivery status. Secrets and raw provider bodies are excluded.

## Runtime Transaction Flow

```text
fetch outside transaction
→ validate/normalize
→ short transaction: upsert bars and reference data
→ build immutable context
→ pure evaluate outside transaction
→ short transaction: claim evaluation + apply state intents + enqueue alert/outbox + audit
→ publish committed event
```

Before intraday evaluation, context assembly range-reads the exact persisted current-day minute sequence through the claimed 5-minute bucket, caps it at 240 rows, verifies completeness, supplies the immutable slice as `current_day_minutes`, derives the provisional daily aggregate and `source_as_of`, and attaches explicit indicator provenance. It does not evaluate zones, reclaim, pressure touch, or risk rules. Pressure-touch derivation and post-touch filtering remain inside pure T023 orchestration.

## Code Style

```python
async def run_minute_cycle(self, deadline: datetime) -> None:
    symbols = await self.active_symbols(limit=10)
    bars = await self.provider_executor.realtime_minutes(symbols)
    await self.persist_and_evaluate(bars)
```

`MarketDataProvider` returns validated normalized values; the runtime must not convert provider rows a second time. Inject clock, provider, repositories, and publisher. Avoid global clients and background tasks without owned cancellation.

## Testing Strategy

- Fake-clock tests for sessions, lunch, weekends, holidays, grace, and final minute.
- Ten-symbol batch tests for complete/partial responses and per-symbol isolation.
- Deadline tests showing recovery and AI work cannot delay realtime polling.
- Permission, rate-limit, timeout, retry, cooldown, and bounded-worker tests.
- Startup recovery and dynamic plan-change tests.
- Exactly-once evaluation tests across duplicates, restart, and delayed recovery.
- Provisional/official close reconciliation tests.
- Cover exact or gapped current-day context assembly, the 240-row bound, provisional source cutoffs, latest-quote insufficiency, and official-source replacement; pressure after-touch outcomes remain T023 decision tests.
- Graceful shutdown tests that stop scheduling, finish/abort bounded work, commit completed transactions, and checkpoint WAL.
- Soak test with synthetic full trading days for 10 symbols and bounded memory/database growth.

## Boundaries

- Always: fail closed for actionable decisions when required capabilities or data are not ready.
- Always: isolate health and failures per symbol where possible.
- Always: prefer scheduled realtime work over recovery and AI work.
- Ask first: exceed 10 active symbols, add a process/queue, or change default market cadence.
- Never: submit broker orders or treat an alert as a fill.
- Never: allow an AI request to run inside the market-data executor or monitoring transaction.
- Never: expose `0.0.0.0` in the normal startup command.

## Success Criteria

- One process monitors 10 enabled symbols without a browser connection.
- One failed/missing symbol does not cancel healthy symbols in the same batch.
- Every completed 5-minute bucket is evaluated at most once per plan/formula version.
- Data older than the configured threshold blocks actionable signals immediately.
- AI provider outage or slow extraction has no measurable effect on polling deadlines.
- Restart recovery does not duplicate bars, transitions, or alerts.
- Shutdown leaves a consistent database and no orphan background tasks.

## Open Questions

- Account-specific Tushare capacity remains a live contract-test gate. If one 10-symbol batch is rejected, the runtime may chunk deterministically under the same global pacing while still supporting 10 symbols.

# Spec: runtime-recovery

> Derived from approved proposal D2–D6 / A03–A10, authorized 2026-09-21. English canonical; paired Chinese copy. Depends on provider-contract.
## Objective

One runtime owner remains able to reconcile local and provider facts after arbitrary restart; no trading decision may bypass exact dependency, activation or freshness guards.
## Contract

- Local configuration/storage bootstrap precedes provider work. A coordinator persists through expected dependency errors, including degraded startup and unknown calendar; those errors never consume the three-crash supervisor budget.
- Reconciliation executes small coalesced scope work units, one owner, bounded queue 32. Round-robin eligible recovery work prevents a failing scope starving siblings. A maintenance wake is at most 30 seconds, without unconditional provider probes.
- Transient retry uses 30/60/120/300 seconds; shared provider cooldown is at least 300 seconds; one permission recheck per operation per 300 seconds, including across process replacement. Missing credentials cause no physical requests.
- Keep physical concurrency 1, starts at least 1.25 seconds apart, timeout 15 seconds, immediate retry 0, backoff keys at most 64. Cancellation does not free a physical slot until its worker actually exits.
- Freeze completed cutoff using authoritative exchange calendar: pre-first-minute requires no nonexistent current-day minute; lunch retains morning coverage; after close reconstructs due obligations; closed days use previous completed data. Unknown calendar schedules retry, never fabricates trading dates.
- Readiness requires exact persisted required coverage. Empty/partial/current-day-only responses do not fill old dates; future rows cannot satisfy an earlier cutoff. Target rollover recomputes work.
- Discover missed legacy official closes from eligible exchange dates minus committed close identities, including absent CLOSE_PENDING records. Respect actual activation/revision; replay chronological transitions. Unknown required historical state blocks the affected plan.
- Reference keys include plan family, required data, activation and semantic revision, not merely symbol/date. Captured generation/activation must still match at commit.
- Both plan families preserve immutable evaluation identities. Store delivery eligibility atomically with each result/outbox transaction, outside canonical hashes. Unsent actionable intraday alerts expire after source cutoff + 90 seconds.
- Risk notices are state-validity based, not blanket 90-second expiry. A per-plan recovery barrier holds risk delivery until that plan reaches the current target, then rechecks latest risk/activation immediately before send. HOLD is not terminal suppression. Historical obsolete alerts remain auditable; external uncertain sends cannot guarantee exactly once.
- Shutdown stops admission and joins owned tasks/workers before closing persistence. Invalid replacement configuration blocks affected work, never silently falls back.
## Storage and rollout

Additive provider recovery checkpoints and delivery metadata only. Migration 0018_provider_recovery follows verified head 0017_market_index_recovery; later delivery migration follows the then-current head. Bounded safe keys/reasons, no secrets. Refuse downgrade that would discard pending state. Temporary-database migration tests are authorized; live migration, backup and deployment require separate approval. Do not enable new default until all alert, lifecycle and transport gates pass.
## Structure and style

Small typed functions in runtime/reconciliation.py and runtime/recovery_targets.py; reuse scheduler, request controller, evaluator transactions and SQLite repositories. No general workflow engine. Python 3.14, explicit enums, immutable targets.
## Commands and testing

`.\.venv\Scripts\python.exe -m pytest tests/unit/test_runtime_reconciliation.py tests/unit/test_recovery_targets.py tests/integration/test_runtime_recovery_storage.py -q`
Then all proposal section 7 gates. Fake clocks/providers/channels, temporary DB, actual process restart tests. Preserve identity goldens and existing failures until diagnosed.
## Boundaries

Always enforce scoped exact evidence and stale-alert safety. Ask before changing evaluator rules, adding dependencies or live actions. Never suppress failing tests, expose credentials or restore an old DB over new business records.
## Sources

[Python 3.14 task cancellation](https://docs.python.org/3.14/library/asyncio-task.html) and [SQLAlchemy transaction boundaries](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html) inform owned task cleanup and atomic local persistence, not business semantics.

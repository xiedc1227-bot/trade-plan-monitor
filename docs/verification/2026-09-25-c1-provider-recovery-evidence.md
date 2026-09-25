# C1 provider recovery: bounded offline evidence

## Scope and gates

C1 remains **OPEN** pending final independent `xhigh` review. This record aggregates A01/A02/A04/A05 checks on temporary SQLite and fake SDK boundaries. The S3-03 core command in `tasks/runtime-recovery-todo.md` passed **101 tests**; its new supplementary command passed **161 tests**. Three selected serial-request tests in `tests/unit/test_monitor_runtime.py` passed. The repaired certified production runtime file and its adjacent production certification/live pipeline regression passed **72 tests**; its test-harness change is described in `2026-09-25-certified-runtime-test-lifecycle.md`.

## A01/A02: semantics and admission

`test_provider_contract.py` verifies atomic, idempotent import of complete compatible old evidence without changing source bytes or copying old READY observations into the semantic record. A timestamp refresh does not change `semanticRevision`; interpretation changes do. Corrupt hash, future observation, wrong endpoint, unknown profile/schema, unverified time label, incompatible installed SDK, and corrupted sidecar fail closed. `test_expired_observation_retains_semantics_but_not_ready_provider_health` confirms that old compatible semantics remain available while current provider health is not asserted READY. The certified production test now exercises the installed lifecycle instead of bypassing database admission and generation ownership.

## A04: same-owner retry

`test_production_a04_retry_timeline.py` uses four consecutive fake `trade_cal` connection faults, then a valid fifth response. The installed composition stays locally readable while DEGRADED, observes 30/60/120/300-second retry floors, retains the same owner/controller/generation with zero crash-supervisor attempts, and lets the scheduler commit one exact 10:10 target after recovery.

## A05: durable scope and process restart

The `0023_index_permission_scopes` migration accepts legacy and mixed bounded key sets, creates independent `idx_mins` and `rt_idx_min_daily` reservations, preserves other checkpoint rows and work-key backoff, is idempotent, and rolls back a simulated child-process interruption. Invalid/corrupt/over-limit state fails closed. Existing independent-process tests retain an observed shared 429 cooldown and a permission reservation across controlled restarts. The live profile remains one worker, one physical request at a time, 1.25-second pacing, 15-second timeout, bounded queue, and zero in-cycle retries.

`test_index_permission_process_restart.py` adds installed composition evidence in **two serial OS processes** on one temporary database, parameterized for either endpoint to recover first. Process 1 upgrades one old `index_minutes` block to both canonical blocks. A successful read-only probe clears only the selected scope; a simulated permission denial on the other writes its next 300-second reservation. The database then contains only that second canonical permission row. Process 2 restores this row with a bound controller and liveness owner, makes **zero** endpoint SDK calls before its due time, then makes exactly one valid probe for the still-blocked endpoint after the due time. Both scopes are clear afterward, with no evaluation, alert, or index-snapshot business write. The two endpoint-specific probe suites additionally check strict response validation, shared 429 handling, market-window priority, physical-start authority, and failure retention.

## Boundary

The tests prove guarded offline endpoint readability and durable recovery behavior. They do not establish real Tushare entitlement or complete A05/release acceptance. Independent review identified a remaining **P1 functional gap**: controlled production permission rechecks are absent for `DAILY_LIMITS`, `DAILY_BARS`, `CURRENT_DAY_MINUTES`, `REALTIME_MINUTES`, and `INDEX_DAILY`; a persisted block on any of these operations can remain latched, including after a token change on the same endpoint. No real provider request, external notification, user database migration, push, or deployment was performed. C1 remains **OPEN** while those five scopes and final independent review are unresolved.

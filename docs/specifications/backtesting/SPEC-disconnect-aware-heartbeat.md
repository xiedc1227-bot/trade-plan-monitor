# Disconnect-aware heartbeat P0 specification

Approved by the user implementation instruction, 2026-10-22. [Chinese review copy](SPEC-disconnect-aware-heartbeat.zh-CN.md). [Proposal](PROPOSAL-disconnect-aware-heartbeat.md). [Tasks](TASKS-disconnect-aware-heartbeat.md).

## DHA-S01. Scope

Implement connection-local disconnect detection and heartbeat admission in the existing v1/v2 stream. Preserve all existing edits; concurrent AI extraction code, tests, fixtures, reports and daily-inventory changes are excluded. No dependency, configuration, data migration or frontend product change. The original implementation phase excluded commit/push; the subsequent user instruction authorizes review and scoped commit/push after verification.

## DHA-S02. Lifecycle contract

After acceptance, exactly 1 child receives through `websocket.receive()` and 1 child runs the existing sender/replay loop. The outer `serve` owns both and joins them on every exit. Only the receiver consumes client messages. Discard non-disconnect application messages without parsing, logging, buffering or health reads; yield fairly when immediately ready. Yield at replay-page boundaries too, because `send` may finish without suspending. At most 1 pending health observer per connection. No detached cleanup or per-heartbeat task. No new global connection limit.

Observed `websocket.disconnect` or expected send disconnect terminates this connection. A known terminal signal wins over simultaneous deadline/publication/read completion. Check immediately before heartbeat admission, replay and sends; no new health read after terminal observation. Ordinary peer close must not become an internal error. Unexpected receiver/sender/business errors remain visible with existing routing semantics. Do not broadly swallow `RuntimeError` or cleanup failure.

On any completion/error/outer cancellation, cancel remaining children once and await them, observing their exceptions. Repeated outer cancellation must not discard cleanup. Do not cancel another connection, notify all publication waiters, stop the read service, change storage pauses or release physical work. Keep contract negotiation, frames, close-code meanings, replay cursor/order/snapshot recovery, fixed v2 20-second cadence and existing deadline calculation. No overlapping/catch-up heartbeats. V1 never calls v2 health.

## DHA-S03. Read ownership and proof invariants

Cancel only the health observer through `MonitorReadOwner.run`; keep its existing lease cancellation, cooperative checkpoints and independently owned task. Never cancel an owned task/proof future, worker thread or surviving proof follower. Work already admitted may complete/unwind after socket departure; no partial proof may certify a response. Physical task counts, retained bytes, sessions and permits remain owned until actual completion. Existing `_stopped_health` temporary-reader `finally` stop/drain must complete or retain its real failure; never detach it to claim fast socket cleanup.

Every successful connected read retains independent authority-before/after, per-read clock/BEGIN snapshot, activation reread, plan/inventory/risk/calendar/proof gates and 2-attempt instability rejection. Preserve 8-read / 15-second cooperative waiting limits, 1 physical index validator, 1 distinct queued owner, 64 MiB retained evidence and exact in-flight-only sharing. Keep all evidence schemas/hashes/ordered sets, retention, fallback and publication rules. No completed health/proof cache. Storage stop/checkpoint/close still drains real work; failed cleanup retains its pause and cannot dispose an active database.

## DHA-S04. Diagnostic contract

Use existing opt-in diagnostics to record terminal observation, heartbeat admission, observer cancellation and child cleanup, linked to opaque connection/heartbeat/read IDs. Only fixed categories, monotonic clocks, statuses and numeric counts; no message body, close reason, URL, credentials or authority tokens. Preserve the 1800-second / 1024-trace / 64-active / 64-span / 128-record limits and 1 MiB files with 2 backups. Overflow/disabled/failing diagnostics cannot alter admission. Separate browser close, server detection, observer exit and physical completion. Known server closure is the admission boundary; an undelivered silent network failure cannot be detected immediately.

## DHA-S05. Measurement and acceptance

Before editing production source, obtain successful actual-owner baseline reads and browser observations on the current source. Preserve all observations, failures, cancellations and limits; do not mutate historical data or manually clear a storage fence. Use normal shutdown/drain between fixed baseline/after revisions and unchanged data/configuration/cadence/protocol. Synthetic scheduling/held-worker probes are race tests, never real latency samples.

Capture >=20 closures before first heartbeat, >=20 closures during known admitted reads, >=20 successful connected heartbeat observations and bounded 2/8-client/result-page loads. Report any missing coverage explicitly. After server-observed terminal state, new health admission must be 0. No transport-child leaks; physical owners/bytes return to baseline only after actual release/drain. Surviving observers still receive verified outcomes/failures. Preserve full successful response/hash comparisons where values are immutable; changing runtime timestamps are compared by contract rather than byte equality.

Measure >=10 alternating isolated connected rounds using the same frozen input and observation budget: retain <=2% CPU / <=5% wall overhead targets. Keep all samples, medians, ranges/maxima, memory/child-count observations, first-byte/worker partitions and mixed failures. Deduplicate shared physical proofs; do not sum logical wall intervals as saved CPU. Do not promise a fixed result speedup; separate avoided abandoned reads from genuine live-reader contention.

## DHA-S06. Verification

Write failing current-source tests first, then verify disconnect-before-admission and simultaneous races; blocking receive/send; publication storms; v1/v2 frames/replay/reconnect; outer/repeated cancellation and child failure; stopped-health temporary cleanup; queue/collection/validator cancellation; leader/follower/all departures; authority/time changes; tamper/hash/retention/fallback; storage pause and cleanup failure. Mutations removing admission protection, observer cancellation or child joining must fail tests. Upgrade fake sockets to the real receive interface; never silently disable production detection for tests.

Focused baseline: `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_read_ownership.py tests/unit/test_index_evidence_flights.py tests/integration/test_runtime_status_websocket.py tests/integration/test_runtime_status_composition.py -q`. Expand through affected websocket, authority, evidence, tracing, retention and storage suites. Browser regression from `web/`: `npm run test:e2e -- dashboard.spec.ts streamCompletion.spec.ts backtest-workspace.spec.ts backtests.spec.ts`, after confirming repository test filenames; run real-owner read-only browser journeys too. Run scoped Ruff, `npm run type-check`, whitespace and bilingual ID/token/number/link checks. Publish paired verification and portable sanitized evidence. Review final diff and confirm excluded work remains unchanged.

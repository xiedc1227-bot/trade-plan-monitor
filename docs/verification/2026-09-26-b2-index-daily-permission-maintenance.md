# B2 INDEX_DAILY permission maintenance: offline third slice

## Scope

The internal `_maybe_recheck_index_daily_permission` path handles only `INDEX_DAILY`. It enters the shared maintenance lock, checks this operation's raw/local/shared due time, reads B1 bounded candidate and missing-anchor evidence, and proceeds only when the global due selector's first eligible candidate is `INDEX_DAILY`. It creates the B2 rotation callback immediately before the controller's durable reservation. No RUNNING/DEGRADED or six-scope scheduler wiring was added.

A missing persisted completed SSE open day sets one local `now + 30s` defer only when the previous local check is due. Repeated calls and the pure deadline getter do not slide that time or reserve provider work. A ready certified index and exact persisted weekday-open anchor are required before reservation; spurious weekend-open rows are excluded from candidate selection and exact-anchor validation. The owner thread checks the anchor before and after the provider response; the SDK worker performs no database work. A frozen 31.25-second market guard is checked before queueing, at queue admission, at worker entry, and through the provider's private physical-start seam immediately before SDK transport. Response validation checks current authority, the persisted calendar/epoch, and that the clock has not moved before the captured start time; it does not reapply a future market-start window.

The permission proof is one read-only `probe_official_daily_permission(I,D)` request. It does not update index caches, business history, evaluations, notifications, or market-deadline cursor. A successful durable reservation advances only the in-memory permission cursor, even when queue admission later aborts; save failure does not. Controller callback faults propagate as sanitized local faults without closing the controller.

## Verification

RED first failed because the internal executor was absent. Fake SDK and temporary SQLite tests cover legal single-scope unlock and one SDK call, not-due/shared-429/unauthorized/no-anchor/other-scope gates, fixed 30-second local defer, save and callback faults, queue abort/stop/invalid response/timeout, restored configuration and semantic revocation, same-value calendar commit changing the epoch, worker physical-start revalidation, owner-thread database access, persisted anchor recheck after the response, serial two-scope interleaving, and a second runtime restoring the 300-second reservation while its memory cursor resets. Further RED cases showed a newer false weekend-open row replacing Friday's anchor and a same-date response clock rewind clearing the block; both are now rejected while the durable 300-second reservation remains. A response 17 seconds before the actual next market deadline still clears a valid permission block; the request started outside the 31.25-second guard. The focused and adjacent command passed **167 tests**; full Ruff and `git diff --check` passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/unit/test_daily_permission_proofs.py tests/unit/test_permission_reservation_ack.py -q
.\.venv\Scripts\ruff.exe check .
git diff --check
```

The later scheduler integration must prove that a permission result does not consume a market-deadline cursor; this internal-call slice has no scheduler dispatch or cursor to consume. The subsequent bounded fix recorded in `2026-09-26-b2-weekend-permission-candidate-consistency.md` now excludes spurious weekend-open rows from `historical_anchor`, `_historical_index_permission_anchor`, and realtime `current_open`. Other permission operations, production scheduling, and end-to-end C1 acceptance remain OPEN. No real Tushare request, notification, user database change, push, or deployment occurred.

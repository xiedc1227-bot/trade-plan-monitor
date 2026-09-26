# B2 DAILY_BARS internal permission recheck

## Contract

- DBPW01: Extract preparation into synchronous `_prepare_daily_bar_permission_locked`; keep its async locking wrapper. `_maybe_recheck_daily_bars_permission` owns the same lock and freshly prepares exactly once, without consuming an old preparation or paging twice. SKIPPED maps to SKIPPED; UNKNOWN maps to DEFERRED and preserves its original 30-second defer.
- DBPW02: Freeze the original candidate, receipt, preparation captured_at, semantic mode/revision, calendar epoch/event, reader, and session factory. Require DAILY_BARS, matching candidate/receipt symbol, and O/F membership. Historical d_need may differ from the SDK anchor.
- DBPW03: Freeze latest_start=captured_at+15 seconds and the 31.25-second market guard before queuing. Check configuration/semantic/generation/stop/calendar identity, same-day time>=captured_at, cancellation Event, and frozen market window before reservation, at queue admission, worker entry, and immediately before SDK entry. Worker checks perform zero database reads. Missing authority/demand/anchor/window defers exactly 30 seconds; a concrete market blocker retains the existing yield deadline rule.
- DBPW04: Build on_reserved from the original candidate. Only successful durable 300-second reservation moves scope, original O/F cursor and alternation, exactly once. Abort/invalid/timeout retain the reservation; actual-start floor extension does not rerun the callback.
- DBPW05: Add keyword-only `_physical_start=None` to `probe_daily_bars_permission` and its private daily path. Invoke after validated argument construction, immediately before `_fetch_frame('daily')`, outside broad catches. Propagate the identical sentinel. Ordinary daily/history paths and strict parsing remain unchanged; prove exactly one official row of the exact symbol/date.
- DBPW06: Response validation runs on the owner using the captured factory's fresh owned explicit-BEGIN snapshot. Validate the original reader/receipt and exact original anchor (SSE, weekday, earlier than response date, open). Do not call an anchor helper that opens another UnitOfWork, repage, reselect, or substitute a new receipt. Check frozen authority/source identity/epoch/time before and after the snapshot. Completion/checkpoint coverage, rollback/corruption, and identity ABA invalidate the original receipt; O/F membership movement and normal pending do not. Do not recheck the future 31.25-second startup window at response time.
- DBPW07: Only controller validate_after=true clears DAILY_BARS; remove only its local defer on success. No business writes or scheduler integration. RequestNotStarted maps to DEFERRED; known permission/429/transient/timeout/invalid-response codes map to FAILED. ERROR/CLOSED/QUEUE_FULL, SQL/save/callback errors, and cancellation propagate. Unknown worker errors remain controller-wrapped ERROR, without promising their original type.
- DBPW08: Capture the calling owner_task and one invocation-local threading.Event. On CancelledError set the Event before reraising; finally permanently sets it. All startup and response guards check the Event. Owner response checks also require captured owner_task.cancelling()==0 before reading and before true; workers never access Task. Requested cancellation cannot clear permission even before the outer catch executes. No guarantee is made that SDK entry cannot occur before the Event is set. The controller's one worker/retained slot drains physical work; do not hold the maintenance lock for drain or modify the controller. Snapshot validation and subsequent controller clearing are not atomic and confer no business execution authority.

## RED matrix

| ID | Required evidence |
| --- | --- |
| R01 | TODAY/HISTORY × O/F, d_need!=anchor, exact call, only own scope clears, no business SQL writes |
| R02 | Shared lock has no deadlock; fresh preparation once |
| R03 | Due/429/other-scope gates; missing fixed 30 does not slide or page |
| R04 | Four revocation boundaries; zero cursor movement before reservation, retained reservation after it, zero SDK call on rejection |
| R05 | Invalid original receipt cannot borrow a valid replacement |
| R06 | Historical completion/checkpoint coverage, rollback and corruption |
| R07 | Original anchor invalid despite another valid date; false weekend-open row |
| R08 | O/F movement permits clearing with original-pool callback once |
| R09 | Concurrent writer, one response snapshot, zero worker SQL |
| R10 | Clock rollback after receipt but before preparation, cross-day rejection, valid late response near market deadline |
| R11 | Save/callback/queue/invalid/429/timeout outcomes and reopened temporary recovery state |
| R12 | Real provider seam propagates identical sentinel; ordinary daily unchanged |
| R13 | Cancellation before SDK, cancellation after start with late success and drain ordering, requested-but-not-yet-caught cancellation blocks clearing |

## Verification status

Contract and RED matrix were recorded before implementation. The minute slice released the provider files at `95feccb`; this change adds only the DAILY_BARS seam in `tushare.py`, with no changes to `tushare_client.py` or minute behavior. The internal entry and real provider seam are implemented, verified offline, and independently approved for a local commit of these five files. No real services, user database, push, deployment, controller changes, or scheduler changes.

### RED and GREEN evidence

- Before the real provider seam and queued-market defer fix, the `real_provider or market_blocked` selection produced **9 failed, 1 passed, 42 deselected**: missing `_physical_start` support and an incorrect fixed defer for a concrete market blocker. After implementation, all **52** then-existing cases passed.
- Added direct entry gating, in-flight normal pending and activation identity ABA checks; all **57** cases passed.
- A new last-pre-reservation market-blocker test then failed with a fixed 30-second defer instead of the frozen blocker deadline plus one microsecond. Both pre-reservation and queued abort now use the same frozen-window defer helper; all **58** final focused cases passed.
- Final combined DAILY_BARS preparation/demand/maintenance, candidate selection/rotation/weekend consistency, INDEX_DAILY/DAILY_LIMITS maintenance and daily proof regression: **248 passed** (including the 58 focused cases).
- Minute proof/transport regression: **291 passed**. Ruff passed for the two changed source files and the new test file. `git diff --check` passed.
- The integration runs emit one existing Starlette/httpx deprecation warning; no external provider calls occur.

### Independent review

The coordinator relayed final independent approval on 2026-09-27: **281 passed across 11 test files**, including all **58** focused cases; Ruff and diff checks passed, and source/test hashes remained unchanged after testing. No P1/P2 findings remain. The initial P2 concerning the last-pre-reservation market-blocker deadline is closed, and the paired reports were confirmed consistent. Approval covers only this internal permission-recheck slice; scheduler integration and A07 production fixes are outside it. After the local commit, `production.py` and `tushare.py` are released for the minute owner’s next design/implementation slice.

### Reproduction

Run from `trade-plan-monitor/` using the existing virtual environment:

```powershell
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_maintenance.py -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_daily_bar_permission_demand.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/unit/test_daily_permission_proofs.py -q --tb=short
.venv/Scripts/python -m pytest tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py -q --tb=short
.venv/Scripts/python -m ruff check src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/market_data/tushare.py tests/integration/test_production_daily_bar_permission_maintenance.py
git diff --check
```

### Evidence boundaries

Tests use real temporary SQLite databases, the real request controller and durable recovery repository, controlled clocks/events, and offline SDK responses. Recovery floors are checked by reopening the temporary database. Worker SQL is rejected; the read-only recheck permits only recovery-checkpoint writes. The concurrent-writer test proves receipt and anchor validation share one response snapshot, including an anchor change committed after that snapshot starts.

Snapshot validation and controller clearing remain separate operations: a later commit may change the business facts. Cancellation checks prevent a requested cancellation from clearing permission even before the outer catch runs, but do not promise that a worker cannot enter the SDK before its cancellation Event is set. Physical work drains through the existing controller slot after the maintenance lock is released. These tests establish permission-proof behavior, not live provider availability or business execution authority.

# C1 stock-minute permission preparation verification

> Canonical agent-facing English version. The matching Chinese review copy is `2026-09-27-c1-stock-minute-permission-preparation.zh-CN.md`.

## SMP-01 Scope and status

- Date: 2026-09-27.
- Contract: [stock-minute permission owner](2026-09-27-c1-stock-minute-permission-owner-contract.md), approved preparation design at `3c22bff`.
- Status: **Preparation implemented; independent implementation review passed with no P1/P2; local commit authorized**.
- Source ownership transferred after SDK-boundary commit `4804207fdc78270604b952cc25a372e59d4e32bb`. The coordinator reported independent approval of that separate slice. Historical SMWO-11 OPEN text does not authorize minute execution; this slice does not amend that contract.
- Scope: `src/trade_plan_monitor/runtime/production.py`, `tests/integration/test_production_stock_minute_permission_preparation.py`, and this bilingual report. Concurrent startup-minute tests and draft repair documents remain untouched.

## SMP-02 Implemented behavior

`_prepare_stock_minute_permission_locked(operation)` returns immutable `PREPARED / UNKNOWN / SKIPPED` facts under the caller-held shared maintenance lock. It freezes candidate, original consumer, capture time, semantic mode/revision, label, provider/source, factory, and epoch/Event. It creates no reservation or SDK call.

One owned application-engine SQLite snapshot checks at most ten ACTIVE versions, bounded payloads, both activation pointers, exact symbols, positive equal revisions, equal canonical Shanghai timestamps no later than capture, and complete canonical plan identity/hash. Today's eligible legacy and explicit consumers require their composed service. Missing business READY inputs do not remove eligibility. No historical activation audit or historical-close discovery runs.

The request date requires an exact persisted SSE weekday-open fact. Windows are `[09:31:12, 11:30:00)` and `[13:00:00, 15:00:00)`. Missing facts/consumers/authority use a fixed 30-second recheck; known first-minute/afternoon times are retained. Getters do not slide deadlines. New preparation rebuilds request-date identity. Revoked tokens are replaced after the owned read only when both captured epoch and Event identity still match; old Events remain set and are never cleared.

Selector and cheap getter both contain eight scopes, preserving the original six-scope order. Independent minute symbol cursors use sorted strict successors with wraparound and survive empty sets. The existing reservation callback precomputes one immutable replacement preserving DAILY_BARS O/F state. Preparation and peeks never invoke it. Tests directly simulate the post-reservation notification; they do not establish durable minute reservation/execution behavior.

Borrowed/pre-used or incorrectly bound sessions raise configuration errors without closing or rolling back caller state. Missing factories defer; minute-only peeks do not fall back to the business UnitOfWork. SQL/programming errors propagate. Permission-only reads do not enable business historical recovery.

## SMP-03 RED and targeted GREEN

Run from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_preparation.py -q --tb=short
```

- Initial minimum RED: **4 failed**, from two missing preparation-method and two missing minute-getter failures.
- Expanded pre-implementation RED: **39 failed**. Subsequent first GREEN work exposed two fixture errors: window times preceded the certification observation. Fixtures now use earlier real certification; no product gate was relaxed.
- Source-replacement regression: **1 failed, 66 passed**, then **67 passed** after source identity capture/check.
- Fixed-due/no-factory regressions: **2 failed, 67 deselected**, then **2 passed, 67 deselected**.
- Final targeted run before the combined rerun: **74 passed**, with one existing Starlette/httpx deprecation warning.

| Contract boundary | Preparation evidence |
| --- | --- |
| SMW-01 | Complete legacy/explicit/mixed consumers; future, expired, missing service, draft/deactivated, empty set, historical-pending-only exclusion. |
| SMW-02 | Three-table pointers/symbol/revision/time; canonical payload/hash/plan ID/version; malformed content; frozen original identity across same-hash reactivation; no historical audit dependency. Response rejection remains execution work. |
| SMW-03 | Exact first minute, one microsecond earlier, lunch, afternoon, close; missing/closed/wrong-exchange/weekend calendar; semantic-mode request-date rollover. |
| SMW-05 | Eight-scope consistency, original order, raw-due/tie rotation, deferred earlier scope, independent symbol successors, empty/new symbol, stable peeks and O/F preservation. |
| SMW-08 preparation | Configuration/generation/stop/label/provider/source/factory/time changes; semantic revision, no legacy fallback, validity after old certification expiry; epoch plus Event identity replacement. |
| SMW-11 preparation | One explicit BEGIN, coherent old identity during concurrent activation commit, borrowed/wrong-bind handling, SQL errors. Response snapshots remain execution work. |
| SMW-15 | Fixed deadlines; zero preparation reservation/SDK/business writes; no historical recovery enablement or scheduler entry. |

Fixtures use temporary SQLite on the configured engine, real legacy repository activation or existing trusted complete explicit activation fixtures, controlled clocks, and an offline SDK. The concurrent-write test intentionally commits a separate fixture activation; preparation itself only reads.

## SMP-04 Adjacent checks

The following run passed **501 tests**, with the same existing warning. It began before the final fixed-due/no-factory refinements; the final combined rerun covers the affected candidate/daily-bar paths and all preparation tests.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_sdk_call_boundary.py tests/unit/test_sdk_call_boundary.py tests/unit/test_stock_minute_permission_proofs.py -q --tb=short
```

Final combined rerun: **175 passed**, with the same existing warning.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_stock_minute_permission_preparation.py -q --tb=short
```

Focused Ruff and whitespace checks passed:

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_production_stock_minute_permission_preparation.py
git diff --check
```

Independent Sol review, relayed by the coordinator, passed with no unresolved P1/P2. The reviewer independently reran the exact final six-file command above: **175 passed**, including all **74** preparation cases. Additional inline adversarial checks confirmed that historical pending alone creates no today's minute consumer while legitimate DAILY_BARS demand remains, missing-factory compatibility remains, and legacy certification expires at the equality boundary. These inline checks are reviewer-reported evidence, not additional checked-in tests or writer runs. The reviewer also reported **123 passed** across four adjacent files; the exact command was not retained here, so that count is supplemental and not the reproducible primary evidence. Diff-scoped Ruff passed, and the reviewer reported unchanged source/test hashes.

## SMP-05 Remaining gates and boundaries

Independent implementation review passed and the coordinator authorized a local commit of this slice's four files. Execution entry points, durable reservations/callback lifecycle, SDK calls, provider/controller changes, response proof validation, automatic scheduling, READY/business state, and full C1 acceptance remain outside this slice. No full repository suite or separate startup-minute RED test was rerun. No real service or user database was accessed; no push, deployment, or sending occurred.

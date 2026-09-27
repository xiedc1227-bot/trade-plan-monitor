# C1 UPD-S2 — Calendar and index permission owners

## Status and scope

Design: approved by the paired `2026-09-27-c1-unified-permission-dispatch-contract` (UPD-S2). Implementation: author verification and independent source/test review passed with no remaining P1/P2; bilingual report parity passed. This is not C1 completion, automatic eight-scope dispatch, or RUNNING/DEGRADED recovery acceptance.

The implementation started after F3-C `a1f217be34334fd68f8a635dda953e2b78e97e55`, with S1 `b3e04a4` final hooks and SMWO `fbdcaed` available. Root's unrelated fixture commits through the final base `5e2eda5` are preserved. Only these six paths belong to this slice:

- `src/trade_plan_monitor/runtime/production.py`
- `tests/integration/test_unified_permission_legacy_owners.py`
- `tests/integration/test_production_index_realtime_permission_probe.py`
- `tests/integration/test_production_certification_gate.py`
- `docs/verification/2026-09-27-c1-permission-legacy-owners.md`
- `docs/verification/2026-09-27-c1-permission-legacy-owners.zh-CN.md`

No provider, controller, startup, scheduler, lifecycle or composition source changed. Tests use fake offline SDKs, real controllers/certification wrappers and temporary SQLite. No live service, user database, deployment or push was used. Root retains commit authority.

## Implementation boundary

The three existing named entry points acquire `_permission_maintenance_lock` and call one private held body. Fresh bounded global selection must select that same operation; a named loser cannot execute the winner. The reservation callback is prepared under the lock immediately before `recheck_permission`, and only its durable `on_reserved` acknowledgement advances the global cursor. O/F and both stock-symbol cursors remain untouched.

Each invocation freezes the candidate/anchor, provider, wrapper and inner client, source label/profile, session factory, original mode authority, calendar epoch/Event and owner Task/cancellation Event. Local reads compare both epoch and Event before installing a new Event; an old revoked Event is never cleared. Calendar retains completed closed-day proof, history retains completed SSE weekday-open proof, and realtime retains its current-day/09:35:12/physical-S cutoff rules. Proof parsing remains in the original providers.

After actual wrapper/resolver completion, final authority I/O precedes the single physical sample S. Only memory checks and the frozen market window remain before the resolved SDK call. The inclusive 15-second latest start and 31.25-second market reserve remain unchanged. Missing market-window authority produces a fixed local defer. Worker paths perform neither SQL nor Task inspection.

Response validation reads the exact original anchor through one fresh owned explicit-BEGIN snapshot from the captured factory, with owner guards on both sides. Borrowed sessions fail ownership validation without closing or rolling back their caller's transaction. No alternative legal date can replace the original anchor. Requested cancellation is checked again after final authority I/O, not only before it; late success cannot clear the block. Cancellation releases the maintenance lock without prematurely returning the controller's physical slot.

Known `BLOCKED_PERMISSION`, `RATE_LIMITED`, `TRANSIENT`, `TIMEOUT` and `INVALID_RESPONSE` become `FAILED`. `ERROR`, `CLOSED`, `QUEUE_FULL`, save/callback/response-SQL errors propagate. Sentinel deferral preserves reservations and acknowledgement. The original calendar work key `permission:trade_cal:SSE` is retained so an existing work-key backoff cannot be bypassed. Local index defers update both legacy index timing fields and the common cheap getter's timing map.

## RED history and fixture distinctions

The target command used throughout was:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_legacy_owners.py -q --tb=short
```

- Initial arbitration/lock/ack tests: **9 failed, 1 warning, 4.90s**; minimal lock/selection changes: **9 passed, 1 warning, 4.52s**.
- Expanded 33-case real failure checkpoint: **15 failed, 18 passed, 1 warning, 13.48s** (`--tb=line`), covering missing-window refusal, real wrapper fences and swallowed fatal index errors. Shared owner fences: **33 passed, 1 warning, 13.40s**.
- An earlier expansion had **21 failed, 12 passed, 14.69s** mixed with invalid `attempts=7` fixture construction and expected shutdown propagation of a latched checkpoint failure. These were corrected fixtures, not product fixes or the clean RED evidence above.
- The reviewer independently diagnosed cancellation during the last authority I/O. Formal `-k final_authority_io` tests: **3 failed, 84 deselected, 1 warning, 2.76s**, all because cancellation incorrectly cleared the block. The minimal owner-thread recheck produced **3 passed, 84 deselected, 1 warning, 2.38s**. An intervening **3 failed, 84 deselected, 1 warning, 2.60s** was only a test attribute typo (`active_physical_count` instead of existing `active_count`), after the actual clear assertion was already fixed.
- The reviewer independently diagnosed calendar work-key compatibility. Formal `-k original_work_key`: **1 failed, 87 deselected, 1 warning, 1.76s**, then **1 passed, 87 deselected, 1 warning, 1.60s** after restoring the old key. The real controller's late failure creates a work-key floor one second beyond the original reservation; the test preserves zero SDK calls before it, any new reservation/ack, and one legal call after the effective floor.

Five existing realtime calendar-fence fixtures now pass `block_historical=False` only for those cases. Their stock certification made history a legitimate earlier global winner; they were not arbitration tests. Sol approved this fixture isolation without weakening token/epoch/queue/physical-call/floor/business-write assertions. Both old index files then passed **71 tests in 14.36s**. The new three-owner nonwinner tests retain actual arbitration coverage.

The existing four calendar failure parameters now expect the approved `FAILED` boundary instead of a thrown known provider error. A wrapper records and rethrows the real controller exception to the owner, preserving assertions on category, 300-second floor, one physical call and zero calendar/business changes. Focused result: **4 passed, 40 deselected, 4.24s**. Root's four separately committed certification fixtures are unchanged by this slice.

## Final author evidence

The expanded target covers 109 cases: nonwinners, serialized actual reservations, save/callback failures, queue veto/once-only acknowledgement, missing window/fixed defer, actual resolver delay/revocation/inner-client replacement, 15-second equality, 31.25-second equality and resolver overrun, final I/O→single S ordering, exact original anchors, epoch/Event interleavings and new-token rearming, requested cancellation in SQL and final authority I/O, SDK/resolver-held cancellation and drain, owned snapshots, borrowed sessions, response-SQL errors, closed-day distinctions and the error matrix. Known failures additionally compare complete calendar/minute/quote/index/evaluation/alert/delivery rows before and after the proof.

Before the final six physical-order controls, the full target passed **103 tests, 1 warning, 40.81s**. The six added controls passed **6 tests, 103 deselected, 1 warning, 3.52s**. The final command above passed **109 tests, 1 warning, 42.74s** on the frozen source/test hashes below. Counts from overlapping windows must not be added.

Direct adjacent command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_certification_gate.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/unit/test_permission_reservation_ack.py -q --tb=short
```

Result: **136 passed, 1 warning, 51.00s**. The warning is the existing Starlette `httpx` deprecation. This is author evidence, not independent review evidence.

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_unified_permission_legacy_owners.py tests/integration/test_production_certification_gate.py tests/integration/test_production_index_realtime_permission_probe.py
git diff --check
```

Scoped Ruff and `git diff --check` passed. Independent results are recorded below.

Frozen SHA256 values:

| File | SHA256 |
|---|---|
| `production.py` | `A7D112694000DDF4DB5BF35170B32BDC4F056D18A991B69BDC272AEAE3CC5938` |
| `test_unified_permission_legacy_owners.py` | `104E6FFA2F71CACAFC01B5F6DB21014E6EA35A6B102451E11A398C450DA5BF2E` |
| `test_production_certification_gate.py` | `D8C3A617242B46A294CC322649A8BB258243B082D1D0DF30825E5A02087160AE` |
| `test_production_index_realtime_permission_probe.py` | `C6E1369123D82B03B260AF645EE68EB8262EB62D22FC4994B4537761918BB3B3` |

## Independent verification

Sol independently reran the final target command above: **109 passed, 1 warning, 42.35s**. Limited adjacent command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_certification_gate.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/unit/test_permission_reservation_ack.py -q --tb=short
```

Result: **124 passed, 43.77s**, no warning. The reviewer found no remaining P1/P2 after the two fixes and approved the four calendar/five realtime fixture changes; scoped four-path Ruff and target diff checks passed. An initial adjacent command mistakenly named `tests/integration/test_permission_reservation_ack.py` and ran no tests in 0.01s; it is only a command-path error, not RED or passing evidence. Final six-source/three-test hash checks matched the start, including all four owned hashes above. HEAD changed from `8d61a8e` to `5e2eda506824e68a9f4ce089689cfe087fd255c3` only for root's process429 fixture commit; this was a stable uncommitted S2 candidate, not a clean-HEAD test. Bilingual report parity passed.

## Sources and remaining work

Implementation follows the approved contract and the existing local controller/session ownership code. Python's [Task cancellation count](https://docs.python.org/3.14/library/asyncio-task.html#asyncio.Task.cancelling) supports rejecting requested cancellation before its outer exception handler; [threading.Event](https://docs.python.org/3.14/library/threading.html#event-objects) supplies the thread-readable token. SQLAlchemy's [SQLite transaction guidance](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl) is applied by the existing `state/database.py` BEGIN listener and `require_owned_recovery_session`; no second BEGIN is added. Local SQLAlchemy remains 2.0.52; no dependency upgrade.

Bilingual report parity passed; independent final source/test review passed. S3 still owns common eight-scope dispatch, all-unavailable timing, removal of inline calendar rechecks, remaining broad catches and final-authority-I/O cancellation controls for the other five owners. S4/S5 retain real RUNNING/DEGRADED scheduling, dual clocks and the complete UPD-R01..18 connected/cross-process acceptance. These direct named-owner tests do not substitute for them.

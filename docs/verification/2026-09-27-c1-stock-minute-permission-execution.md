# C1 stock-minute permission execution verification

> Canonical agent-facing English version. The matching Chinese review copy is `2026-09-27-c1-stock-minute-permission-execution.zh-CN.md`.

## SME-01 Scope and status

- Date: 2026-09-27.
- Status: **Implemented; post-fix writer verification and independent final review passed; P2 closed with no remaining P1/P2; local commit authorized**.
- Design authority: [SMWO owner contract](2026-09-27-c1-stock-minute-permission-owner-contract.md). The coordinator released execution after independent preparation acceptance at `47a803ba68d72e3b80f495f4f08aac5f16ba4ff8` and the separately reviewed SDK boundary at `4804207fdc78270604b952cc25a372e59d4e32bb`.
- This slice owns only `src/trade_plan_monitor/runtime/production.py`, `tests/integration/test_production_stock_minute_permission_execution.py`, and this bilingual report. No provider, controller, dispatcher, recovery service, business reader, or database schema is changed by this writer.
- Automatic dispatch, business startup recovery, READY, and complete C1 acceptance remain OPEN. Design approval and provider tests are not owner implementation acceptance.

## SME-02 Implemented owner behavior

Both internal minute entry points capture the outer Task and a new invocation Event before their first await. The common owner acquires the maintenance lock and prepares exactly once. Its closure retains the original consumer/candidate, authority mode/revision, label, provider, wrapper and underlying SDK client, session factory, and calendar epoch/Event.

Before reservation, queue admission, worker entry, and the final SDK boundary, the request checks its frozen request date, latest start (`captured_at + 15s`), legal request window, 31.25-second market guard, configuration/certification/semantics, generation/stop and identity fences. The last authority I/O completes before a single S sample; only original-mode time and memory checks follow S before the resolved SDK callable. Legacy certification retains the real loader's inclusive `valid_until` boundary; one microsecond later is rejected. STOCK semantic mode does not inherit the old certification expiry.

The invocation owns its evidence slot and actual-S record. The owner requires an exact `MinutePermissionEvidence`, matching endpoint/symbol/date/label and exact actual S, `0 <= R-S <= 15s`, positive A, bounded typed counts and sorted unique source dates. C is at most two and requires the request date in the date set; START has no B, END has at most one B per source date, and A+C cannot exceed 240 ordinary identities per source date. No response-time reclassification occurs.

The captured factory opens one fresh owned application-engine explicit-BEGIN response snapshot. It revalidates the original three-table consumer, not another eligible symbol, and reads every exact SSE weekday-open date in `source_dates ∪ {request_date}`. The union is bounded at 1,001; exact `IN` chunks of 250 share that snapshot. There is no historical range helper, extra business UnitOfWork, historical audit scan, or calendar SDK request. The ownership preflight is outside the context manager, preserving caller-owned transactions on configuration errors.

The outer Task's cancellation state is checked before reading the response snapshot and before returning true. Invocation cancellation is permanent, including in `finally`; no worker accesses a Task or the application database. Already-started work drains through the controller without retaining the maintenance lock. An abandoned result slot cannot populate another invocation's slot.

The existing controller persists the 300-second reservation before invoking the one-shot cursor callback. Physical-start floor extensions and successful clear do not repeat it. Success clears only its own permission block and local defer. Known permission/429/transient/timeout/invalid outcomes return `FAILED`; original `RequestNotStartedError` yields `DEFERRED`, using a market blocker plus one microsecond or a fixed 30-second recheck. `ERROR/CLOSED/QUEUE_FULL`, checkpoint, callback and SQL errors propagate. Only controller recovery checkpoints are written.

## SME-03 RED-to-GREEN evidence

Run from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short
```

- Initial owner-entry RED: **2 failed**; the expanded pre-implementation matrix had **30 failed** for absent minute execution entry points. Initial implementation then passed **30**.
- Final-authority-I/O counterexample: replacing the wrapper's underlying SDK client was incorrectly accepted. The 48-case run contained that **one implementation RED**, plus seven fixture/setup failures. Capturing/checking the underlying client identity fixed the actual defect; the corrected 48-case matrix passed.
- Additional category-bound RED command below: **6 failed, 97 deselected**. Forged C>2, START B, excessive END B, excessive ordinary identities, and C without the request date were accepted despite the provider contract. The owner now rejects each while retaining existing provider semantics.
- Pre-review targeted result: **103 passed**, one existing Starlette/httpx deprecation warning.
- Independent review found one P2: the owner had changed the loader's inclusive legacy expiry to an exclusive boundary, and the original test incorrectly expected that refusal. The revised real-loader positive/negative controls produced **1 failed, 1 passed, 102 deselected** at exact expiry / one microsecond later. Changing only the owner's `<` to `<=` restored compatibility; the post-fix full execution target passed **104 tests**, with the same existing warning. This is the current target evidence; the independent pre-fix results are not post-fix approval.
- Invalid certification-hash construction, duplicate calendar fixture inserts, slot-restricted monkeypatching, a wrong controller constructor keyword, a mistaken checkpoint scope name, a misplaced test append, and a transaction observer that counted its fixture writer were test-construction defects. They are not product fixes or independent RED evidence; fixtures were corrected without skipping tests or removing assertions.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short -k category_count_bounds
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short -k original_legacy_expiry
```

All executions use temporary application-configured SQLite, complete real activation fixtures, controlled clocks, fake SDK callables, and the real provider/parser/controller. Fast timeout isolation uses a 0.05-second test controller; the owner evidence interval remains 15 seconds. No real service, user database, outbound notification, push, or deployment is involved.

## SME-04 Contract coverage

| Contract boundary | Checked-in owner evidence |
| --- | --- |
| SMW-01–03 | Legacy, explicit and mixed owner success; original identity replacement/same-hash revision/ABA/other-symbol rejection. The accepted 74-case preparation file supplies full consumer, three-table, request-window and fresh-date preparation coverage and is rerun with this slice. |
| SMW-04 | One exact `rt_min_daily` or `rt_min` call with symbol, `1MIN` and fields; only its own block and defer clear; business SQL writes are rejected by the observer. |
| SMW-05–06 | Existing eight-scope preparation tests rerun; real durable callback exactly once, independent symbol cursor/global position, DAILY_BARS O/F preservation, save failure, post-reservation veto/invalid response, physical floor extension, coalesced waiter. |
| SMW-07 | Four owner admission gates, queue-wait revocation, fixed +15-second equality/one-microsecond-late boundary, 31.25-second equality blocker. |
| SMW-08 | Final-I/O changes to provider/underlying client/factory/generation/stop/epoch/Event/time; semantic missing binding/mode/revision; inclusive legacy expiry with a one-microsecond-late negative control; response Event identity replacement cannot revive old authority. Preparation token rebuilding remains covered separately. |
| SMW-09 | Real A plus B/C, typed empty, incomplete-only and malformed frames; original not-started sentinel survives the provider/controller; known failure classes and unexpected errors. |
| SMW-10 | Unknown B-only date, sparse 700-day-old dates, closed/unknown/weekend facts, 1,000 sparse source dates plus request date, five exact chunks with no second UnitOfWork. |
| SMW-11 | Distinct preparation/response sessions, actual SQLite transaction state, coherent identity/calendar snapshot during a concurrent fixture writer, borrowed and split-bound response session preservation, SQL fault propagation; no worker SQL/Task access. |
| SMW-12 | Exact invocation S, no authority I/O or resampling between S and actual SDK entry, forged timestamp rejection, frozen proof validation, legal response across lunch/close and a newly approaching market deadline, rollback and late R rejection. |
| SMW-13 | Queued and in-SDK cancellation, cancellation requested before the outer catch and during the response snapshot, late positive proof after timeout, separate second result slot, no second physical start before slot drain, released maintenance lock. |
| SMW-14 | Shared real 429, durable 300-second reservation read via reopened temporary SQLite, virtual 1.25-second shared pacing, save/callback/SQL error propagation. |
| SMW-15 | Fixed local defer remains unchanged under repeated getters; unrelated local defer survives success; SQL observer allows only reads and recovery checkpoints. No automatic scheduling entry is wired. |

## SME-05 Adjacent verification

The initial comprehensive run, before the final six category-count regressions, passed **672 tests**. It included the 97-case execution version and all 74 preparation cases. The pre-review rerun of this exact command passed **678 tests**, including the then-current **103** execution cases and **74** preparation cases, with one existing Starlette/httpx warning. Source/test hashes were unchanged before and after that run. These counts precede the P2 expiry correction:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_sdk_call_boundary.py tests/unit/test_sdk_call_boundary.py tests/unit/test_stock_minute_permission_proofs.py tests/integration/test_production_stock_minute_permission_preparation.py tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short
```

Controller/storage/session adjacent verification: **84 passed**. This run preceded the final category-count-only refinement; that refinement does not change these components.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_request_recovery_admission.py tests/integration/test_runtime_recovery_storage.py tests/integration/test_close_recovery_session_ownership.py -q --tb=short
```

Post-P2 final targeted/adjacent rerun: **335 passed**, with the same existing warning. It includes all **104** execution and **74** preparation cases, candidate and DAILY_BARS paths, and real production certification/semantic gates:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_stock_minute_permission_preparation.py tests/integration/test_production_stock_minute_permission_execution.py tests/integration/test_production_certification_gate.py tests/integration/test_production_semantic_gate.py -q --tb=short
```

Independent Sol post-fix final rerun, with the exact command confirmed by the coordinator: **104 passed, 1 warning in 16.42s**. The expiry P2 is closed with no remaining P1/P2. This independent result is separate from the writer's 104/335 results:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short
```

Focused Ruff passed after the final source/test edits:

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_production_stock_minute_permission_execution.py --output-format concise
git diff --check -- src/trade_plan_monitor/runtime/production.py
```

Review snapshot SHA256:

- `production.py`: `021993781B39E3F1E88EB63402D30CCE1EBB65B2D6B0DD4746F646A0FE252581`.
- `test_production_stock_minute_permission_execution.py`: `459CCAB58ACE2A39BDC63E4C42B2A249A8E38A7ACD406ED362DC71B381263C4D`.

## SME-06 Remaining gates and limits

Initial independent owner review identified the expiry P2 above. The coordinator confirmed that independent Sol post-fix final review passed: P2 closed and no remaining P1/P2; a local commit of these four files is authorized. Concurrent A07 work and separately authorized UPD-S1 provider work are not claimed by this report; broader commands exercise the shared checkout, not a release artifact. The complete repository suite and A07 startup RED file were not run by this writer.

The proof establishes endpoint readability, not business readiness or trading authority. Snapshot validation and controller reset are not one atomic database transaction. S precedes invoking the resolved SDK callable; it is not network-send time and does not guarantee zero thread scheduling delay. Cancellation does not forcibly interrupt an active SDK call. Observed authority revocation is monotone, but unobserved external ABA bypassing supported epoch paths is not claimed detectable. Real `rt_min` positive-row availability, automatic scheduling, startup business integration and full C1 acceptance remain separate gates.

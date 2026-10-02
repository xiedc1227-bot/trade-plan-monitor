# Daily-plan offline verification — 2026-10-01

> Scope changed2026-10-02: the user authorized removal of daily broker order/partial/unknown tracking in favor of explicit atomic whole-lot simulation. This document records the prior scope; its completion/test conclusions do not approve the new cleanup. Follow the [current cleanup contract/tasks](../../tasks/2026-10-02-daily-plan-simulation-cleanup.md) and revised canonical specification. Preserve the historical evidence below.

Canonical English; paired review copy: `2026-10-01-daily-plan.zh-CN.md`. Specification: [SPEC-daily-plan](../specifications/monitoring/SPEC-daily-plan.md). Tasks: [daily-plan-todo](../../tasks/daily-plan-todo.md).

## V01. Scope and current status

The implementation uses Schema 4 / `daily-close-v1`, `daily-ta-v2` and `plan-extract-v7`. Fundamental and announcement review occurs only when the user generates a plan. Original text remains visible excluded background; it grants no monitoring fact, condition, buy/sell prerequisite, risk trigger or execution blocker. Technical structure/volume/indicator conditions and operational tradability/suspension remain in scope. Schema 1/2/3, prompt v1–v6 and existing index behavior are preserved.

Fresh independent Astra/high review inspected the complete uncommitted daily chain and closed F1–F11 after Sol/high repairs and independent rechecks. Source is frozen. The coordinator's **final complete offline backend suite passed**, followed by a separately executed additional sparse-calendar regression. Earlier interrupted or failed runs remain historical evidence. External market/AI/provider calls are replaced by offline fixtures and temporary SQLite; complete executable plans and fact evidence are synthetic human-reviewed examples. The user's unchanged original template remains the source-only missing-parameter negative case. No live provider, notification delivery, production database, actual source-plan approval, commit, push or deployment is certified.

## V02. Executed checks

Counts describe collected tests in each command, including reused/imported fixtures; they are not counts of newly added cases, and overlapping groups must not be added together.

| Check | Actual result |
|---|---|
| P04 compatibility: `test_explicit_conditions.py`, `test_explicit_rules.py`, `test_explicit_plan_review.py`, `test_ai_plan_extraction_v4.py`, `test_decision_engine.py` | **351 passed / 3.75s**, rerun after the scope and review repairs. |
| `.venv/Scripts/python.exe -m pytest tests/unit -k daily -q` | **290 passed, 2403 deselected / 5.14s**. |
| Eleven-file critical integration/domain group below | **88 passed / 23.55s**. The final calendar batching/input-bound changes received the separate actual-composition checks below. |
| `tests/integration/test_daily_accounting.py` | **2 passed / 0.99s**, per-share idempotency and unknown reservations. |
| `tests/integration/test_openapi_snapshot.py` | **14 passed / 8.80s** after both documentation fingerprints were synchronized. |
| Real `ProductionMonitorPipeline` composition | Helper: FACT/POSITION/REPORT public mutations and both startup/realtime recovery entrances passed. Astra independently reproduced the sparse-calendar counterexample after the final repair: 1500 calendar days, 1044 runtime dates, 500 certified bars/series dates, no blockers, original risk timing preserved. Its production/boundary/condition group: **12 passed / 9.04s**. |
| Separate additional sparse-calendar regression | `tests/integration/test_daily_sparse_calendar_regression.py`: **1 passed, 1 warning / 5.94s**, Ruff passed. Added after the full suite finished; it proves 50 certified holidays force 750→1500, all 1533 calendar rows persist, runtime 1044 dates survive, and series 500 bars/500 exact interval dates preserve missing-day validation. It is separate from the 6065-test full result. |
| Independent review regressions | Astra: **63 passed / 12.32s** for F4/F8, scope and history-cap repairs; all F1–F11 closed after the final production recheck. |
| Frontend full unit suite, latest coordinator rerun | **60 files, 828 passed / 6.55s**. |
| Frontend type/build | `npm run type-check`, normal build and runtime-status-preview build passed in the latest coordinator rerun. |
| Real Chrome | Both `web/tests/e2e/daily-plan.spec.ts` and `daily-review-batches.spec.ts` passed. The risk journey uses real UI technical/tradability entry, next-session timing and collapsed 40/60 internal debit details. The batch journey saves partial v1, reloads through its real link, adds batch two, saves immutable v2 and reviews/activates. No console or failed-request errors were observed. |
| Static/contracts | Ruff over `src tests`, compileall and both generated-contract `--check` gates passed. RuntimeInputs' 3033-date bound is internal; the public contract fingerprints below are unchanged by it. |
| Final `.venv/Scripts/python.exe -m pytest -m 'not live' -q` | **6065 passed, 1 skipped, 4 deselected, 1 warning / 3208.19s (0:53:28), exit 0**; includes `test_backtest_acceptance.py`. |

The eleven-file command was:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_daily_history_regression.py tests/integration/test_daily_plan_chain.py tests/integration/test_daily_plan_boundaries.py tests/integration/test_daily_scope_http.py tests/integration/test_daily_orders_regression.py tests/integration/test_daily_production_reevaluation.py tests/integration/test_daily_supplement_batches.py tests/unit/test_daily_safety_boundaries.py tests/unit/test_daily_risk.py tests/unit/test_daily_source_exclusions.py tests/unit/test_daily_plan.py -q
```

Both generated snapshots contain **60 paths = previous 51 + nine daily resources**:

- `openapi.json`: `69109c2620cca5c6467753a459e9c033faaa22862d7f68ba8dec19b8c717220b`.
- `openapi.runtime-status.json`: `027cafb61579a33e006bcf5874524c54e976715e166d6eea6029a5503513f484`.

## V03. DP-A01–DP-A20 evidence map

The following map identifies executed focused evidence, backed by the completed V02 full gate and the separate additional regression. A row does not certify a live market or the original incomplete historical plan. Python filenames below are relative to `tests/`; browser paths are relative to the repository.

| ID | Executed evidence and boundary |
|---|---|
| DP-A01 | P04 351-pass compatibility group; `unit/test_daily_plan.py` codec/hash round trip; `unit/test_daily_extraction.py` frozen-version and human-authority rejection; the 6065-test full legacy/index gate passed. |
| DP-A02 | `unit/test_daily_extraction.py::test_historical_source_stays_partial_and_ai_cannot_supply_human_authority`; `unit/test_daily_review.py::test_partial_missing_condition_cannot_be_acknowledged_away`; Chrome original extraction leaves technical gaps. |
| DP-A03 | `unit/test_daily_plan_review_service.py` real persistent review/activation/restart; `unit/test_daily_review.py` changed semantics invalidate supplements; `integration/test_daily_supplement_batches.py` exact digest/revision, immutable duplicate-version 409 and reload activation; both Chrome journeys. |
| DP-A04 | `unit/test_daily_lifecycle.py::test_holiday_calendar_and_included_endpoints_do_not_allow_chasing`; `unit/test_daily_plan.py` explicit endpoint validation; `unit/test_daily_conditions.py::test_daily_all_any_missing_retains_each_evidence`; `integration/test_daily_scope_http.py` rejects three dimensions collapsing to one fact/indicator or a bypassing ANY path. |
| DP-A05 | `integration/test_daily_plan_chain.py::test_daily_public_review_confirmation_next_session_and_expiry`; certified bar publication/cutoff rejection in `unit/test_daily_safety_boundaries.py`; Chrome severe entry remains waiting on the confirmation date. |
| DP-A06 | `unit/test_daily_lifecycle.py` certified Friday→Tuesday holiday and Tuesday-close expiry; `unit/test_daily_risk.py::test_both_reviewed_suspension_choices_have_distinct_resumption_behavior`; production calendar proof and the final sparse-calendar recovery checks. |
| DP-A07 | `integration/test_daily_history_regression.py::test_first_offline_close_recovers_only_current_next_session_ordinary_window`; `test_successor_expires_old_ready_before_accepting_later_independent_event` verifies original dates and zero stale new-order quantity. |
| DP-A08 | `integration/test_daily_plan_chain.py::test_same_completed_date_can_reevaluate_current_quote_reentry`; `integration/test_daily_plan_boundaries.py` send-time quote age; `unit/test_daily_safety_boundaries.py` risk, CORE/TAC, capacity and unknown-input blockers. |
| DP-A09 | `integration/test_daily_plan_boundaries.py::test_partial_expiry_restart_later_close_requires_new_independent_evidence`; `integration/test_daily_history_regression.py` successor expiry and independent event after risk fulfillment; old same-window authority stays permanently invalidated. |
| DP-A10 | `integration/test_daily_plan_boundaries.py::test_real_sell_pressure_never_sells_core_and_today_buy_is_not_sellable`; safety tests separate actual CORE100/TAC0 from reviewed targets; Chrome independent inventory registration. |
| DP-A11 | `integration/test_daily_accounting.py::test_partial_fill40_then60_uses_one_ledger_and_retry_never_restores`; chain actual partial-report/restart case; `integration/test_daily_orders_regression.py` actual BUY and SELL 40+60 under one external order. These are fills/internal debits, not independent 40/60-share declarations. |
| DP-A12 | `unit/test_daily_safety_boundaries.py` actual 200 + pending 100 / max 300 and own full pending BUY/SELL; `integration/test_daily_orders_regression.py` aggregate quantity, immutable external identity, UNKNOWN positive remainder locked and zero remainder reconciled. |
| DP-A13 | `unit/test_daily_risk.py::test_rebounding_second_close_still_confirms_then_third_session_exit`; `integration/test_daily_plan_chain.py::test_ordinary_rebound_below_line_confirms_then_executes_next_session`; production missed-close recovery preserves Tuesday confirmation/Wednesday execution. |
| DP-A14 | `integration/test_daily_plan_chain.py::test_official_tradability_fact_immediately_reevaluates_without_fundamental_gate`; Chrome actual SEVERE_STRUCTURE + SEVERE_DETERIORATION form entry, missing-group/same-date wait and next-session risk. |
| DP-A15 | `unit/test_daily_scope_exclusion.py` valid baseline then excluded-kind-only domain/API/storage and nested rejection; `unit/test_daily_source_exclusions.py` exact background/mixed remainder/forged exclusion rejection; `integration/test_daily_scope_http.py` real 422 with unchanged database/outbox, background review/activation and common technical-hide counterexamples. |
| DP-A16 | `unit/test_daily_risk_allocations.py` newest settled tactical lots and protected CORE; safety affected-bucket target combination, reserved SELL target debit and UNKNOWN locks; history reassessment/fulfillment consume old causes, retain audit and allow a later same-day official cause. |
| DP-A17 | `unit/test_daily_conditions.py` QFQ/basis rejection and 2×v1 histogram with identical DIF/DEA; `unit/test_daily_safety_boundaries.py` future basis/receipt rejection; real production current QFQ anchor; unit and HTTP preview reject required warmup plus offsets above 500. |
| DP-A18 | `integration/test_daily_plan_chain.py::test_activation_change_and_admission_failure_roll_back_all_daily_state`; actual report retry/restart, `test_queued_risk_quantity_is_rechecked_after_actual_inventory_changes`; boundary send-time age and history distinct risk-cause outbox test. |
| DP-A19 | `integration/test_daily_scope_http.py::test_background_rebound_review_preserves_same_technical_runtime_result`; `unit/test_daily_risk.py::test_excluded_fundamental_fact_does_not_confirm_any_technical_risk`; safety confirmed-risk unknown inventory/auxiliary evidence; tradability/T+1 verified through production and Chrome. Background changes require normal source re-review first. |
| DP-A20 | `web/tests/e2e/daily-plan.spec.ts`: paste→v7 gaps→supplement→save/review/activate→CORE100/TAC0→UNKNOWN/cancel→actual 40+60→real technical/official evidence forms→next-session exit→expiry/source invalidation. `daily-review-batches.spec.ts`: two batches, preview/reload recovery, immutable v1→v2 and activation. No fundamental form or announcement-clearance gate. |

## V04. Review repairs and practical limits

F1/F11 fix reviewed bucket scope/target authority. F2 rejects aggregate linked over-reporting and external-order identity changes before mutation; truthful external over-limit transactions remain explicitly unlinked audit records. F3 expires historic ordinary authority before successor checks. F4 deducts reserved SELL quantity from both sellability and required reduction; remaining UNKNOWN quantity locks execution, actual 40+60 reconciles it, and zero quantity does not permanently block a later risk. F5 rejects the known price/buy and close-break/addition-stop hiding counterexamples while retaining actual inventory statements and visible technical remainders. F6 validates the three independent evidence dimensions on every successful ALL/ANY path. F7 uses the actual production Clock protocol for immediate public-mutation reevaluation. F8 persists consumed cause evidence and exact cutover time, permanently invalidates old ordinary authority, marks actual target completion FULFILLED, and gives later official causes distinct outbox identity/send-time checks. F9 preserves registered supplement batches across same-digest preview/reload and rejects immutable-version collisions as 409. F10 replays only actual missing official closes after effective activation, preserves original pending-line timing and current QFQ basis, and prepares bounded certified history.

Daily-only calendar preparation starts at 750 days, expands to 1500 then at most 3000 days to obtain 500 certified open sessions, and stores every returned calendar row in batches of at most 1000 within one transaction. Runtime proof accepts at most 3033 calendar dates (history plus 32 future days, inclusive). Each DailySeries retains its actual bar interval's full calendar/suspension proof, at most 500 bars and 1000 dates; missing dates inside that interval still reject. New-listing/long-suspension/provider insufficiency is never filled artificially: required conditions remain MISSING_INPUT, and inadequate required calendar coverage is explicit. Activation checks theoretical parameter support without making a new live-history request.

Natural-language exclusions are finite source-span treatments plus explicit human scope selection. They do not prove arbitrary prose semantics or fundamental truth. AI cannot self-certify human selection; known mixed/technical counterexamples are rejected, and technical remainders stay review-visible. Genuine 40/60 partial fills are retained in the ledger and collapsed as non-independent-order details. Reviewed declaration rules control new quantities; CORE and TACTICAL are submitted/registered separately, with internal lot merging confined to one bucket.

## V05. Final gate and historical runs

The fixed-source complete backend command `.venv/Scripts/python.exe -m pytest -m 'not live' -q` exited 0: **6065 passed, 1 skipped, 4 deselected, 1 warning in 3208.19s (0:53:28)**. The coordinator retained the log at `$env:TEMP/daily-plan-final-backend.log`. The only warning is the existing StarletteDeprecationWarning about TestClient/httpx; no dependency change was made. Fresh independent review and the complete gate are finished; DPT09/C4 are complete.

After that full suite finished, the already-reviewed sparse-calendar regression was copied to `tests/integration/test_daily_sparse_calendar_regression.py` and separately run with `.venv/Scripts/python.exe -m pytest tests/integration/test_daily_sparse_calendar_regression.py -q --tb=short`: **1 passed, 1 warning in 5.94s**; Ruff passed. The warning is the same existing StarletteDeprecationWarning. Production source remained frozen. The evidence is 6065 in the complete suite plus one separately executed later regression; **6066 was not a full-suite result**.

The pre-pause full run was **5926 passed, 22 failed, 1 skipped, 4 deselected / 3324.78s**, not a success. A scope-revision `-k daily` run with 639 passing collected tests predates the review repairs. The later fast backend run loaded the old source snapshot and was deliberately stopped; it has no final result. None of these substitutes for the final complete run above.

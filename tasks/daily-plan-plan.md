# Implementation plan: daily-plan

Canonical English; paired copy: `daily-plan-plan.zh-CN.md`. Date:2026-10-02. The user authorized design → Sol/high implementation → fresh Astra/high review → fixes/re-review without another permission gate. This initiative does not replace other project plans.

## P01. Objective and dependency order

Implement the current [specification](../docs/specifications/monitoring/SPEC-daily-plan.md) and [capability map](../docs/architecture/CAPABILITY-MAP-daily-plan.md). Current incremental work is the [2026-10-02 simulation cleanup](2026-10-02-daily-plan-simulation-cleanup.md): contract → isolated daily simulation state → runtime/risk/delivery → public UI/API → independent verification. Existing DPT IDs remain traceable in [tasks](daily-plan-todo.md); DSC01–DSC06 specify the cleanup slices.

Monitoring and notification never mutate positions. One explicit eligible user simulation consumes the complete offered100-share-multiple quantity atomically. Remove this initiative's broker-report/partial/unknown/reservation subsystem; a hidden control or renamed status is not removal. Minimal simulated position/receipt/date-batch records use generic daily storage without touching legacy real inventory.

## P02. Minimum complete delivery

A fully reviewed synthetic plan enters through the real source/review/activation UI and real production adapter. Official close confirms an ordinary signal, only the next exchange session can offer it, and the user separately simulates the entire quantity. Before that command, reminders and acknowledgements leave holdings unchanged. Exact retries and a new key for the consumed signal cannot duplicate the trade. CORE100/TACTICAL0 with max300 can simulate BUY100 subject to readiness, total200; same-day acquired TACTICAL cannot sell under T+1; ordinary SELL never debits CORE. Risk simulation uses reviewed targets and server-selected internal batches without user allocation forms.

Retain source gaps, fundamentals exclusion, technical/operational facts, current review binding, correct MACD2× formula, daily/QFQ admission, certified calendar recovery, risk scope/cause/fulfillment and old-schema/index behavior. All position/action/target/display quantities are whole100-share units (0 allowed for non-trade fields). Legacy development records stay preserved and explicitly unsupported, never simulated success or uncontrolled500.

## P03. File boundaries and deletion discipline

- Domain/AI: tighten only unpublished daily models, signal/position/receipt contracts and V7 product semantics; retain frozen Schema1/2/3, v1–v6 and ta-v1.
- State: replace daily accounting with isolated simulation-tagged POSITION/SIMULATION generic records and atomic revision/idempotency. Unpublished0024 kind CHECK/model may change for fresh fixtures; no migration series, production rewrite, shared inventory sync or real PositionLot/PositionInventoryConfirmation mutation.
- Decision/runtime/notification: remove order/reservation/partial math and broker states, retain technical-risk PENDING, timing, risk invalidation/causes and fixed provider recovery. Current delivery checks consumed simulation authority.
- API/Vue: remove daily-execution-reports and all broker/client-allocation forms/fields, add the minimal daily-simulated-trades command and aggregate initialization. Server selects batches and price/time. Regenerate both contracts mechanically.
- Tests: remove only tests for deleted daily broker behavior; replace with whole-simulation transaction, old-table-isolation, current-authority, risk/recovery and real UI tests. Preserve shared legacy/index tests. Do not silently retain old40+60/UNKNOWN fixtures as the new positive path.

Use focused3–5-file slices where practical. Separate generated mechanical files. No unrelated reformat, credentials/configuration change, source-template edit, live call, production data access, commit/push/deploy. Initial simulation baseline is explicitly pre-settled; subsequent T+1 is computed from simulation dates and certified sessions. No automatic holdings import or database reset/reclassification workflow.

## P04. Verification commands

Run backend commands from `trade-plan-monitor/`, frontend commands from `web/`; actual new filenames may be split without changing acceptance:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_daily_plan.py tests/unit/test_daily_lifecycle.py tests/unit/test_daily_risk.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_daily_plan_chain.py tests/integration/test_daily_production_reevaluation.py tests/integration/test_daily_sparse_calendar_regression.py -q
.venv/Scripts/python.exe -m pytest tests/unit/test_explicit_conditions.py tests/unit/test_explicit_rules.py tests/unit/test_explicit_plan_review.py tests/unit/test_ai_plan_extraction_v4.py tests/unit/test_decision_engine.py -q
.venv/Scripts/python.exe -m ruff check --no-cache src tests
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -m pytest -q -m "not live"
npm test -- --run
npm run type-check
npm run build
npm run test:e2e -- tests/e2e/daily-plan.spec.ts
```

Add targeted simulation tests for DP-A11/12/18/20, isolation from shared legacy tables, obsolete development records and missing authority. Run both generated-contract checks using the repository's current commands. The coordinator schedules the complete backend gate after stable source and independent review; do not repeatedly rerun the unchanged53-minute capacity group after doc/test-only additions. Record exclusions/counts honestly and never relabel the prior6065 result as new-scope verification.

## P05. Risks and retained content questions

| Risk | Required mitigation |
|---|---|
| Simulated activity masquerades as broker reality | Explicit simulation labels and isolated daily position/receipt storage; assert legacy inventory tables remain unchanged. |
| Repeated click or changed plan restores quantity | Atomic idempotency, durable ordinary consumption, current plan/cause/inventory fences and restart tests. |
| Quantity40/60 survives through a retained target | Field-level0-or100-multiple checks for setup/max/targets/actions/display, no global revision-type change. |
| Removing broker UNKNOWN accidentally removes risk PENDING | Distinguish technical confirmation states; preserve first/second-close tests. |
| Removed broker fields survive hidden paths | API rejection, generated schema absence, runtime/source search and real-browser tests. |
| Scope cleanup regresses review/risk/recovery | Keep independent cause, QFQ/calendars, severe/ordinary scope and source-exclusion regression. |

The historical plan's missing strategy values and explicit suspension policy remain unresolved user content, not implementation defaults. No further stage approval is needed for this authorized cleanup.

Delete editable broker lot-size/odd-lot knobs and rule evidence/date.100-share units,1-fen simulation tick, next-session settlement and verified special-state checks are fixed product semantics supplied by the server, not per-plan broker attestations.

## P06. Earlier fundamental-scope revision retained

The2026-10-01 revision removed fundamental/announcement monitoring throughout Schema4/V7, exact source exclusions, APIs and UI while retaining technical/operational evidence. That boundary is unchanged. DP-A15/DP-A19 remain reverse tests; index and old schemas/prompts remain frozen. Current simulation cleanup neither restores fundamentals nor introduces new risk branches.

## P07. Historical verification checkpoint

The superseded2026-10-01 implementation received independent F1–F11 closure, backend6065 passed/1 skipped/4 deselected/1 warning in3208.19s, and a separately added sparse-calendar regression1 passed/5.94s; frontend828/type/build and both Chrome journeys passed. [Historical verification](../docs/verification/2026-10-01-daily-plan.md) and [historical review](../docs/verification/2026-10-01-daily-plan-independent-review.md) retain evidence. Broker partial/unknown/reservation behavior validated then is now intentionally removed, so those results do not approve this scope.

## P08. Current cleanup gate

Implementation, DSC01–DSC06/DPT09/C4 and current verification are complete. Fresh Astra/high review closed C1–C7 after independent backend, restart and actual frontend-parser checks. The [final paired report](../docs/verification/2026-10-02-daily-simulation-cleanup.md) preserves the first full failure and strict test-only correction, then records the passing non-capacity recheck with the unchanged capacity group’s earlier pass. Root’s freeze comparison confirms business source/contracts/assets unchanged. No user plan activation or live-provider certification is implied.

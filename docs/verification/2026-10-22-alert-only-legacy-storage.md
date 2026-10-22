# Reminder-only draft and legacy simulation storage — 2026-10-22

## ALERT-LEG-001 — Exact trigger

The actual `605296.SH` database contains only two `daily_plan_record` entries:
`EXTRACTION` and `REVIEW`. There are no position, simulation, report, signal, risk,
or evaluation records for this symbol, and no active plan binding.

The trigger is the existing table's `ck_daily_record_kind` constraint: its allowed
kinds do not contain `SIMULATION`. `DailyAccounting.legacy_reason` detects this
storage-wide condition before checking individual symbol records and returns
`DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED`. The database migration revision is
`0025_index_close_display`; the retained table constraint is older than the current
`0024_daily_plan` migration definition. An already recorded revision is not rerun
when the service starts.

This is a valid simulation-storage restriction, not evidence that this stock has
historical simulated holdings. No constraint or record was migrated or repaired.

## ALERT-LEG-002 — Effect on technical reminders

The runtime's `_alert_only` path independently evaluates Schema 5 policies containing
alerts but no ordinary rules or risk branches. It uses an unknown inventory projection
without creating a position. The delivery check also treats `REMINDER` separately
from simulation eligibility. Review, active binding, verified data, confirmation,
current evidence and notification-window checks continue to apply.

An isolated database recreated the original constraint without `SIMULATION`. A
synthetic reviewed and active daily price reminder generated exactly one `REMINDER`,
passed `daily_delivery_allowed`, and generated no buy/sell signals or risk exits.
Repeated evaluation did not create a duplicate event. This passed both without a
historical report and with a preserved report whose revision and bytes were unchanged.
Position initialization and simulated-trade requests remained rejected with HTTP 409.

The actual user draft remains unreviewed and inactive, so it does not currently
monitor or issue alerts. The old simulation constraint is not an additional blocker
for this pure-reminder policy; this does not waive any normal review or data check.
All test approval/activation operations concerned isolated synthetic fixtures only.

## ALERT-LEG-003 — Display repair and component boundary

The symbol runtime response derives its reminder-only exception from the active
policy. With no active policy, the response can legitimately retain the simulation
compatibility reason. `PlanSimulationPanel` previously displayed that stock-level
result as the selected draft's plan status, incorrectly implying that the draft was
itself incompatible with technical reminders.

The panel now derives the presentation from the persisted selected `version.planJson`
and review binding. A Schema 5 reminder-only draft displays either
`仅提醒草稿：待审核，尚未启用` or `仅提醒草稿：已审核，尚未启用`.
The separate simulation notice explains the compatibility restriction and that pure
reminders do not require simulation inventory. The panel explicitly states that an
inactive version does not monitor reminders.

`PlanWorkbench` still supplies the immutable version and request function;
`PlanSimulationPanel` adds only pure computed presentation; `PlanOperationForm` and
its blocking behavior are unchanged. No additional component or composable is needed
for this small display correction. Invalid, incomplete, historical, ordinary-trade,
and risk-bearing policies do not receive the reminder-only label. Genuine request
errors and preserved technical risk history remain visible.

No backend response, legacy predicate, schema, review/activation gate, form guard,
simulation authority, account data, or original AI output was changed.

## ALERT-LEG-004 — Regression results

| Check | Executed result |
| --- | --- |
| Frontend regression before the repair | 3 failed, 17 passed |
| Frontend regression after the repair | 20 passed, including 9 new cases |
| Full frontend unit suite | 1215 passed across 83 files |
| Related backend regression selection | 84 passed, including 3 new legacy-storage cases |
| TypeScript check / production build / Ruff | Passed / passed / passed |

Frontend cases cover pending and reviewed-but-inactive drafts, active reminders with
protected simulation inventory, unchanged request bodies and props, unsupported
ordinary/risk policies, incomplete/invalid/historical documents, and real read errors.
Backend cases reproduce the old storage constraint, prove no monitoring before
approval, verify price-reminder evaluation and delivery eligibility, preserve old
report bytes, reject simulation operations, and check unchanged actual/simulated
inventory. All test databases are isolated from the actual monitor database.

```powershell
# From web/
npm test -- --run tests/unit/dailySimulation.spec.ts
npm test -- --run
npm run type-check
npm run build
# From the project root
.venv/Scripts/python.exe -m pytest tests/integration/test_alert_only_legacy_storage.py tests/integration/test_unified_runtime.py tests/integration/test_daily_simulation_review_regressions.py tests/integration/test_plan_read_timezone.py tests/unit/test_daily_safety_boundaries.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_alert_only_legacy_storage.py
```

The backend result describes this selected regression scope, not the complete backend
suite. No external AI, market-data or notification provider was invoked by these tests.

## ALERT-LEG-005 — Actual page and preservation evidence

The production frontend was rebuilt into the existing workspace distributions and
the actual saved draft page was reloaded. Its status now separates the pending draft
from simulation compatibility. The service and original database were not replaced.

| Actual acceptance item | Result |
| --- | --- |
| Draft | `SNGC-OBS-20261022`, version 1, `DRAFT` |
| Technical alert | 1; official daily close strictly below fixed `2659` `FEN` |
| Buy / sell / risk-liquidation rules | 0 / 0 / 0 |
| Source and plan hashes | Unchanged |
| Review | `review_id=null`, `review_revision=0`, `confirmed_at=null` |
| Activation | No active binding; activation button disabled |
| Both original daily records | IDs, kinds, revisions and payload hashes unchanged |
| Storage constraint | Unchanged; still excludes `SIMULATION` |
| Actual/simulated inventory, risk and activation protection snapshots | Identical before/after |

Evidence is under `evidence/2026-10-22-alert-only-legacy-storage/`:
`trigger-analysis.json`, `acceptance.json`, `protected-before.json`,
`protected-after.json`, `test-results.json`, and `draft-state-separated.jpg`.
The original research appendix and AI verification archive remain unchanged at
`data/research/SNGC-OBS-20261022/validation-20261022-115118/`.

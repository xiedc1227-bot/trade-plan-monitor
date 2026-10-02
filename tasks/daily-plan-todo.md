# Tasks: daily-plan

Canonical English; paired copy: `daily-plan-todo.zh-CN.md`. Date:2026-10-02. Current scope is monitoring plus explicit whole-lot simulation. Prior2026-10-01 completion is historical; the affected rows below are now complete. [Specification](../docs/specifications/monitoring/SPEC-daily-plan.md), [plan](daily-plan-plan.md), [cleanup tasks](2026-10-02-daily-plan-simulation-cleanup.md). Stable DPT IDs remain; split mechanical generated changes separately.

## T01. Ordered implementation slices

| State / ID | Deliverable and acceptance | Depends on | Verification trace |
|---|---|---|---|
| [x] DPT01a | Daily complete model and frozen compatibility; simulation unit is100 shares, old schemas/prompts/formulas unchanged. | — | DSC01 / DP-A01 |
| [x] DPT01b | Field-specific whole-lot quantities; delete configurable broker increments/odd-lot/evidence-date knobs, bind fixed software rules; reject incompatible complete contracts. | DPT01a | DSC01 / DP-A02–04/11/12 |
| [x] DPT02a | Retain completed-day condition/formula evaluator and exact fixed/dynamic semantics; recheck in final gate. | DPT01b | DP-A04/05/17 |
| [x] DPT02b | Retain real QFQ/calendar adapter,500-observation/3033-date recovery and sparse-calendar regression. | DPT02a | DP-A06/17/18 |
| [x] DPT03a | Minimal isolated daily POSITION/SIMULATION persistence; no shared real inventory writes or new migration series. | DPT01b | DSC02 / DP-A18 |
| [x] DPT03b | Atomic whole simulation, aggregate setup, T+1, independent revision and idempotency; delete reports/reservations. | DPT03a | DSC02 / DP-A10–12/18 |
| [x] DPT04 | Ordinary confirmation/window/independent rearm/lineage plus one whole SIMULATED consumption. | DPT02b,DPT03b | DSC03 / DP-A05–09/11 |
| [x] DPT05 | Retain two technical risk timings/scopes/causes/fulfillment; whole-lot simulation targets and no order allocation projection. | DPT02b,DPT03b | DSC03 / DP-A13–16/19 |
| [x] DPT06a | Actual scheduler/review-bound simulation transaction fencing and recovery; no automatic trade from monitor. | DPT04,DPT05 | DSC03 / DP-A03/18 |
| [x] DPT06b | Current delivery and durable cause/consumption; no broker status or reservation fields in outbox/read views. | DPT06a | DSC03 / DP-A07/16/18 |
| [x] DPT07a | V7 faithful partial extraction with current100-share product semantics and source exclusions; v1–v6 frozen. | DPT01b | DSC01 / DP-A01/02/15 |
| [x] DPT07b | Preserve current source/content/evidence review and activation binding under tightened complete model. | DPT06b,DPT07a | DSC04 / DP-A03 |
| [x] DPT08a | Remove execution-report route; minimal explicit simulated-trades and aggregate initialization; technical facts still reevaluate. | DPT06b,DPT07b | DSC04 / DP-A11/12/15/19 |
| [x] DPT08b | Regenerate both contracts/types; no broker/order/client-allocation transport fields, review UI remains usable. | DPT08a | DSC04 / DP-A02/03/20 |
| [x] DPT08c | Real UI explicit full simulation/receipt/T+1/CORE; no partial/unknown/broker evidence/internal-debit forms. | DPT08b | DSC04/05 / DP-A10–16/20 |
| [x] DPT09 | Fresh DP-A01–20 evidence, independent review/fixes/recheck, applicable full gates and paired2026-10-02 report. | DPT08c | DSC05/06 |

## T02. Checkpoints

- [x] C1: unchanged old compatibility and isolated simulation storage; all new quantities have the correct field-level100-share boundary.
- [x] C2: real production/runtime transactions preserve ordinary/risk timing, cause/recovery and whole simulation without order tracking.
- [x] C3: real source/review/activation/UI journey, nonmutating reminders, explicit full simulation, no broker/fundamental gates.
- [x] C4: new-scope independent review has no material findings; current executed checks and paired report are recorded.

## T03. Handoff and boundaries

User authorization already covers removing the former daily-only report/order/partial/unknown/allocation tests and implementation, not shared legacy abilities or unrelated tests. Retain technical-risk PENDING, fundamental exclusions, T+1/CORE/max300, source fidelity and500/3033 recovery. No new migration framework, brokerage ledger, real-position sync, auto-trade, live/production data operation, commit/push/deploy. Exact current contract is D08/D09 plus DSC01–DSC06. Old development evidence stays preserved and clearly unsupported; it is not a migration project.

## T04. Retained earlier scope checklist

The2026-10-01 fundamental-scope revision is retained: exactly two technical branches; fundamentals/announcement facts absent from nested executable contracts; exact non-monitoring source exclusions; no fundamental runtime/UI blockers; DP-A15/19 remain reverse boundaries. Its formerly completed tests do not complete new simulation criteria.

## T05. Current evidence checkpoint

Implementation and DSC01–DSC06/DPT09/C4 are complete. Fresh Astra/high review closed C1–C7 after independent backend and actual frontend-parser rechecks. The [current verification](../docs/verification/2026-10-02-daily-simulation-cleanup.md) records the first full run’s outdated test expectation, its strict correction, the passing final non-capacity recheck, retained passing capacity evidence and final frontend gates. Historical6065 backend/828 frontend results and F1–F11 closure remain in [2026-10-01 verification](../docs/verification/2026-10-01-daily-plan.md) and [review](../docs/verification/2026-10-01-daily-plan-independent-review.md). New DP-A11/12/18/20 use whole-lot simulation evidence, not the removed40+60/UNKNOWN behavior. Overlapping counts are not added or presented as a single full green run.

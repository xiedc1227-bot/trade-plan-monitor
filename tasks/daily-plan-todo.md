# Tasks: daily-plan

> Historical separate-daily implementation record. Superseded on 2026-10-02 by [One Trade Plan Workflow](../docs/specifications/monitoring/SPEC-unified-plan.md). Its tests and completion statements certify only the recorded old scope, not the current one-plan workflow. Preserve historical evidence; do not use this document to require a separate daily product.

Canonical English; paired copy: `daily-plan-todo.zh-CN.md`. Status: implementation, independent review and publication complete on2026-10-02. This single record retains DPT, DSC and C1–C4 completion. The [specification](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/specifications/monitoring/SPEC-daily-plan.md) defines current behavior; [final verification](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/verification/2026-10-02-daily-simulation-cleanup.md) records executed gates.

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

The current daily chain is monitoring plus explicit whole-lot simulation. Reminders and acknowledgment do not mutate holdings; initialization and trades use fixed100-share units, with simulation inventory isolated from shared real/legacy holdings. Retain technical-risk `PENDING`, T+1, CORE protection, plan `max_qty`, source review and500/3033 recovery. Broker reports, partial/unknown orders, reservations and client-allocation APIs are absent. Fundamentals do not enter monitoring; new broad-market index logic is deferred, while existing Schema1/2/3 and index behavior remain. Obsolete development data is explicitly unsupported and never converted into simulated success.

Implementation commit `a8ec8e6a2862fca275a8eac5bad0e768e86ce08c` and documentation commit `030075c4946bf34833a0155fde6b4deda3c79055` were pushed to GitHub. Former execution plans, pause/resume instructions and cleanup handoff are consolidated here; their historical text remains available at that documentation commit. No live-provider, production-database or deployment operation was performed in this task.

## T04. Retained earlier scope checklist

The2026-10-01 fundamental-scope revision is retained: exactly two technical branches; fundamentals/announcement facts absent from nested executable contracts; exact non-monitoring source exclusions; no fundamental runtime/UI blockers; DP-A15/19 remain reverse boundaries. Its formerly completed tests do not complete new simulation criteria.

## T05. Current evidence checkpoint

Implementation and DSC01–DSC06/DPT09/C4 are complete. Fresh Astra/high review closed C1–C7 after independent backend and actual frontend-parser rechecks. The [current verification](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/verification/2026-10-02-daily-simulation-cleanup.md) records the first full run’s outdated test expectation, its strict correction, the passing final non-capacity recheck, retained passing capacity evidence and final frontend gates. Historical6065 backend/828 frontend results and F1–F11 closure remain in [2026-10-01 verification](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/verification/2026-10-01-daily-plan.md) and [review](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/verification/2026-10-01-daily-plan-independent-review.md). New DP-A11/12/18/20 use whole-lot simulation evidence, not the removed40+60/UNKNOWN behavior. Overlapping counts are not added or presented as a single full green run.

## T06. Consolidated cleanup task record

| State / ID | Completed boundary |
|---|---|
| [x] DSC01 | Fixed whole-lot contract and v7 source treatment; broker-rule configuration removed. |
| [x] DSC02 | Isolated simulation holdings and atomic trades; idempotency, T+1 and explicit obsolete-data rejection. |
| [x] DSC03 | Ordinary signal and two technical risk branches; deduplication, transaction fences and recovery. |
| [x] DSC04 | Minimal initialization/simulation APIs, generated contracts, review/activation and UI. |
| [x] DSC05 | Offline backend, frontend, actual-browser and compatibility regression evidence. |
| [x] DSC06 | Fresh-scope independent review, fixes/recheck and paired acceptance record. |

Complete API fields, errors, storage and compatibility boundaries are maintained in `SPEC-daily-plan` D08/D09; acceptance criteria are DP-A01–DP-A20. This table does not create a second contract.

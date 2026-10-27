# Specification: monitor-readiness

Status: APPROVED FOR IMPLEMENTATION — 2026-10-27. Module of [plan-monitor-assurance](SPEC-plan-monitor-assurance.md); depends on [source-condition-coverage](SPEC-source-condition-coverage.md). [Chinese copy](SPEC-monitor-readiness.zh-CN.md).

## MRD-S01 — Objective and authority boundary

Explain whether this exact plan can currently receive the monitoring promised by its own rules. Reuse monitor contract2, current runtime ownership/read/proof services, source review, health, signal and notification authority. Do not create another evaluator, worker, heartbeat, acquisition path or trading token. `plan-monitor-readiness-v1` always carries literal `authorityGranted=false`; execution endpoints never accept its hash/badge as approval.

Display the actual declared scope: `ALERT_ONLY`, `TRADE_RULES` or `MIXED`. A valid one-alert plan can be ready for that one alert without becoming a full trading plan. `SUCCEEDED`, `ACTIVE`, HTTP200, a connected page, a historical replay and a cached healthy snapshot cannot independently imply current readiness.

## MRD-S02 — Six dependency-aware axes

Use per-axis `PASS`, `WAIT`, `BLOCKED`, `UNKNOWN`, `NOT_APPLICABLE`, with exact reasons/evidence/times. Keep all failed/waiting axes visible rather than returning one misleading green summary.

| Axis | Required evidence | Important dependency rule |
| --- | --- | --- |
| `SOURCE_COVERAGE` | Current source/candidate/mapping/rules version, complete obligations and exact human binding | Historical valid review without current coverage has axis BLOCKED with a review-required reason and summary `NEEDS_REVIEW`, not source corruption or PASS |
| `REVIEW_ACTIVATION` | Exact reviewed saved version and current activation revision, source validity/scope | A saved draft/replaced plan is not the current active plan |
| `RUNTIME_OWNERSHIP` | Current generation/lifecycle, nonstale heartbeat and existing ownership/drain/protection state | Service reachability, an old heartbeat or another process's last result is insufficient |
| `DATA_EVALUATION` | Official calendar, expected target, permitted provider/basis/formula, completeness/freshness, actual evaluation target/outcome | FALSE can be a complete valid evaluation; missing input/first evaluation cannot |
| `INVENTORY_CAPITAL` | Only rule-required known inventory/sellability, fee/economics inputs, applicable book/quote/revisions | Reminder-only needs no inventory/book; market-value cap needs no historical cost; BUY-only inputs are not SELL vetoes |
| `NOTIFICATION_DELIVERY` | Selected channel/configuration, eligibility, queue/retry/failure state, verified delivery evidence where claimed | QUEUED/acknowledged/generated is not DELIVERED; no automatic test message |

Dependency determination comes from the exact plan/rule, not the presence of a database table or a global requirement that every plan know every account value. A prerequisite unrelated to a rule is `NOT_APPLICABLE`, never a missing-data failure. Inventory, simulation capital, real holdings and research balances stay separate. Never initialize or infer them to make readiness pass.

## MRD-S03 — Evaluation, waiting and execution states

Expose per-rule evaluation states: `CONDITION_TRUE`, `CONDITION_FALSE`, `WAITING_OFFICIAL_CONFIRMATION`, `AWAITING_FIRST_EVALUATION`, `MISSING_INPUT`, `BLOCKED`, `UNKNOWN`. Map existing runtime outcomes without changing their public semantics. Retain signal/action state separately, including approved quantity, consumption and original execution window; monitor health is not current trade eligibility.

For a daily official-close rule, before the calendar-defined close is available, show normal `WAITING_OFFICIAL_CONFIRMATION` only when current owner/target scheduling and prerequisites establish that this is expected. Do not label the absent future close a provider failure or fill it with an intraday quote. If a required earlier completed bar/official close is missing or stale, show that failure instead. A broad existing `WAIT_FOR_VERIFIED_INPUT_OR_NEXT_SESSION` string alone cannot distinguish these cases; use typed calendar/target/evidence reasons.

`CONDITION_FALSE` with complete current evidence means monitoring successfully checked an unmet condition. `MISSING_INPUT`, no completed evaluation, stale/different target or cached read cannot be converted to FALSE. Before the first real eligible evaluation, show its absence; do not invent completed counts. Waiting for an event/window, a consumed signal or an expired execution window does not itself mean the monitor is broken and cannot create a new occurrence.

Summary states are `READY_FOR_MONITORING`, `WAITING_EXPECTED_CONFIRMATION`, `WAITING_REQUIRED_SERVICE`, `NEEDS_REVIEW`, `BLOCKED`, `UNKNOWN`. Default precedence is: a definite non-review safety/data/configuration blocker → BLOCKED; otherwise missing/stale human coverage/review → NEEDS_REVIEW; otherwise unavailable/uncertain required authority → UNKNOWN; otherwise an established expected service wait (for example pending delivery) → WAITING_REQUIRED_SERVICE; otherwise only expected calendar confirmation pending → WAITING_EXPECTED_CONFIRMATION; otherwise READY_FOR_MONITORING. All underlying axes remain visible. READY requires all applicable axes current and passing plus eligible actual evaluation evidence; waiting states grant no actionable authority. No overall READY while an applicable axis is unknown/failed/unverified. T16 proves this precedence and boundary combinations, rather than inventing frontend precedence.

Known trade ineligibility is separate: a completely evaluated false condition, known whole-quantity cap failure, consumed signal or closed execution window can coexist with healthy monitoring. INVENTORY_CAPITAL checks required evidence availability/integrity, not a requirement to make every trade pass its money predicates. Do not turn known ineligibility into a monitor-service failure or an automatic SELL.

## MRD-S04 — Snapshot, freshness and bounded reads

The view owns `computedAt`, exact `planVersionId`, source/content/coverage/review binding, activation revision, runtime generation, current scope/target identifiers, evidence/provider/formula/calendar references, per-axis observed/as-of times and relevant inventory/book revisions. `freshUntil` is the earliest applicable existing evidence expiry, or null when freshness cannot be established. Reuse established runtime/source freshness policies; introduce no relaxed universal freshness timeout. Client time or a cached success cannot renew authority.

Current facts must belong to one coherent admitted context. If a read crosses a plan activation, proof change, runtime-generation change or relevant inventory/book revision, return UNKNOWN/context-changed or retry within the existing bounded read-owner policy. Never join a new plan with old evaluation evidence to fabricate readiness. Use existing CURRENT/CACHED/UNAVAILABLE provenance; a cached view is clearly historical, not current PASS. UI discards late responses on context change and removes a ready claim once evidence expires.

A database-only installation audit is `PERSISTED_ONLY`: stored heartbeat/evaluation rows cannot establish the current process's owned authority. Without a legitimate snapshot from the already-running current owner service, runtime readiness stays UNKNOWN/NOT_READY. An explicitly configured loopback read of that existing service may collect such a snapshot; it must not launch the service or trigger provider acquisition, and cannot replace missing current authority with persisted timestamps.

`GET /api/v1/plan-versions/{version_id}/monitor-readiness` is a bounded projection of existing owned facts: no network/provider acquisition, heartbeat update, database migration, outbox write, simulation, review or activation. Missing runtime facts return typed UNKNOWN; missing assurance storage returns UPGRADE_REQUIRED/UNKNOWN without automatically creating tables. Keep current plan/tree/read ownership limits, at most10 active symbols, existing response/admission budgets and a1MiB new view bound. Size/availability failures cannot silently omit a blocking axis or rule. No full historical scan per polling tick.

## MRD-S05 — Notification truth and read-only risk visibility

Distinguish configured, eligible, pending, retrying, failed, suppressed and delivered. A delivery claim requires the dispatcher's actual successful channel result and bound receipt, not an outbox intention, acknowledgement or old unrelated channel success. Report target/channel and receipt time without secrets. If there is no current trustworthy configuration/delivery verification, use `DELIVERY_UNVERIFIED`; no automatic message is sent by a readiness read. Manual verification messages require separate explicit authorization and clear test labeling, without changing market prices or real rules to force a signal.

Preserve send-time eligibility checks for exact source/review/window/current data/inventory/capital. A source/coverage correction suppresses affected actionable messages; queue history remains truthful. Do not suppress independent informational risk warnings because a BUY budget/coverage input is missing. Such a warning is labeled with its uncertainty/legacy scope and does not authorize risk simulation or broker activity.

## MRD-S06 — UI and three different acceptance claims

Use plain language beside the plan and each rule: source coverage/review status, monitored scope, actual last evaluation and target, normal close waiting versus missing data, applicable inventory/budget needs and notification state. Preserve current required manual decisions; do not show a one-click “make ready” action that repairs conditions, grants approval, initializes costs or activates plans. Show source→rule links and steps the user must take, without exposing implementation codes as the main explanation. Loading, failures, disconnected/cached states and stale responses are distinct and accessible. Verify320/768/1024/1440 layouts and keyboard/error feedback.

Acceptance claims are separate:

1. **Engineering:** isolated scenarios prove correct positive/negative readiness, current ownership and zero business writes/network calls.
2. **Extraction:** the approved real-provider corpus is evaluated under its exact version; a result does not certify current runtime health.
3. **Real installation:** read-only inspection records actual migration/schema, saved version, current coverage/review, activation, owned runtime/evaluation/data and notification evidence. A documented BLOCKED/UNKNOWN/NOT_READY diagnosis can be a correct audit, but cannot be reported as an actually ready installation.

A positive real-readiness claim needs the actual prerequisites and authorized observations, including channel verification if claimed. User migration, real-source review/activation, initial inventory/cost confirmation and test sends are not performed automatically by this audit. If such operations remain unapproved or prerequisites absent, list them plainly and retain NOT_READY. Do not modify live data to manufacture a positive test.

## MRD-S07 — Acceptance scenarios and implementation seams

Acceptance: PMA-A05/A06,A09–A12. Required scenarios include: healthy alert-only with unknown inventory; market-value cap without cost book; cost-cap BUY missing basis with independent technical-risk SELL unaffected; complete FALSE; expected current-day close waiting; missing previous official data; first evaluation; stale quote/provider/calendar/proof; changed activation/runtime generation; CACHED/UNAVAILABLE; pending/retrying/delivered/suppressed notification; expired/consumed signal; missing upgrade; and concurrent reads with zero side effects.

Reuse `web/runtime_status_models.py`, `runtime/health.py`, current monitor-read/proof services, `runtime/daily_service.py` and dispatcher projections. Suggested new focused seams are `web/plan_readiness_models.py` and `web/plan_readiness_service.py`, with existing plan routes/workbench adapters. Do not loosen current runtime health to obtain a green badge. The task list owns the future test/API/generated/UI slices; this draft changes no runtime or frontend code.

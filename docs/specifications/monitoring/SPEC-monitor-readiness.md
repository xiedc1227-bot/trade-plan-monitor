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

## MRD-S08 — Typed fact field appendix

### MRD-S08.1 — Additive shape and ownership

This appendix defines fact shapes only. It adds no read assembly, eligibility evaluator, dispatch, queue, storage, approval token or automatic test send. `RuleReadinessFacts.money`, `RuleReadinessFacts.notification` and `RuleReadinessFacts.risk` default to null and are omitted when null. The five new nullable execution fields below follow the same omission rule. Existing a6/a7 fields, including their existing null keys, retain their serialization. Actual readiness JSON preimages must round-trip byte-for-byte when the additions are absent.

New projections inherit the existing closed, frozen, strict `ApiValue` contract and camelCase aliases; embedded native capital/economics results keep their original field names and validation. Preserve exactly six axes, at most76 owners, at most50 complete native condition leaves, literal `authorityGranted=false`, and existing all-null freshness/summary precedence. Merely supplying facts does not promote any axis or derive trading/delivery eligibility.

Reuse the parent rule's owner and admitted read context, plus existing `ReadinessObservation` where listed. Do not add duplicate owner/hash/provenance wrappers. Context equality cannot prove an original risk cause; a later reader must independently verify the exact original sources and their applicable freshness. No unique original signal/event or no trusted result means nullable/absent facts, not a guessed approval, failure, pending state or native `NONE`/`PASS` verdict.

### MRD-S08.2 — Money

`ReadinessMoneyFacts` has these fields:

| Field | Type / nullability | Meaning |
| --- | --- | --- |
| `inputs` | Required `AxisReadiness`; `axis` must be `INVENTORY_CAPITAL` | Per-rule input availability, existing reason and `ReadinessObservation`; retain the original axis constraints |
| `capital` | `CapitalAssessment` or null; omit null | Copy the exact native frozen capital result, including phase, policy hash, quantity, revisions, blockers and evidence hash |
| `economics` | `EconomicsResult` or null; omit null | Copy the exact native `NONE`/`PASS`/`FAIL`/`UNKNOWN` result; absence is not `NONE` |

Validate native values without calculating fees, economics, capital or quantity again. Preserve strict Python validation and the native JSON-reading path so serialized tuple arrays round-trip; this does not allow bool/string coercion into numeric fields. Native `FAIL` can coexist with `inputs.state=PASS`: a known whole-trade failure is not a monitoring input fault. `capital.quantity` and `economics.quantity` are checked quantities, not approved quantities; they cannot populate `execution.approvedQuantity`. Null results do not claim a trusted verdict. Native result values and nested snake_case names remain unchanged.

### MRD-S08.3 — Original execution facts

Extend the existing `ReadinessExecutionState`; retain `approvedQuantity`, `consumed`, `executionWindow`, `windowState`, `eligible` and `reason` unchanged.

| New JSON field (Python field) | Type / nullability | Meaning |
| --- | --- | --- |
| `signalId` (`signal_id`) | Bounded existing `Reference` or null | Exact original signal; supplied together with its revision |
| `signalRevision` (`signal_revision`) | Existing `Revision` or null | Paired with `signalId`; integer0–9007199254740991, never a bool |
| `executionDate` (`execution_date`) | Date or null | Original known execution date; no calendar inference |
| `observation` | `ReadinessObservation` or null | Exact observed execution facts and their original times/references |
| `blockers` | Complete tuple of existing `Reference`, at most128, or null | Null means no trusted list; an empty list does not prove eligibility; never truncate |

Both signal reference fields are null/absent or both supplied. Their presence does not validate source ownership by itself. Do not require old valid a6 callers to supply the additions retroactively. Preserve `consumed` and `eligible` as independent true/false/null facts; no combination derives permission. The original approved quantity comes only from the verified original signal's final quantity. `q0`, candidate quantity, static rule quantity and risk target are not substitutes. Each `Reference` remains1–256 characters; no new execution framework is created.

### MRD-S08.4 — Exact event and channel facts

`ReadinessNotificationFacts` carries nullable `eventId` (`event_id`, UUID), `causeId` (`cause_id`, `Reference`), `target` (existing `EvaluationTarget`), `createdAt` (`created_at`, original Shanghai timestamp), and `observation` (`ReadinessObservation`); omit those null fields. `channels` is a tuple of at most3 `ReadinessNotificationChannel` values, unique by the existing `DeliveryChannel` enum: `IN_APP`, `CONSOLE`, `WEBHOOK`. An empty tuple means no channel facts were supplied, not that channels are disabled. Event metadata, historical classifications and attempts require their exact original `eventId`; configuration can be observed without an event.

| Channel JSON field (Python field) | Type / nullability | Meaning |
| --- | --- | --- |
| `channel` | Required existing `DeliveryChannel` | Exact channel, not another channel's success |
| `configured`, `enabled` | Strict bool or null; omit null | Independently verified configuration/enabled state; unverified does not mean false |
| `eligible` | Strict bool or null; omit null | Copied current eligibility only; false does not create historical `SUPPRESS` |
| `historicalStatus` (`historical_status`) | Existing `RecoveryDeliveryStatus` or null | Original `ELIGIBLE`/`HOLD`/`SUPPRESS` classification, separate from current eligibility |
| `historicalUpdatedAt` (`historical_updated_at`) | Shanghai timestamp or null | Original classification update time; supplied together with `historicalStatus` |
| `latestAttempt` (`latest_attempt`) | `ReadinessDeliveryAttempt` or null; omit null | Exact latest trusted event/channel attempt; no attempt means no such record |

Configuration, current eligibility, historical classification and attempt history can change independently; do not infer one from another. `IN_APP` delivery establishes only that channel's actual receipt and cannot verify `WEBHOOK`. No event/attempt is not automatically failed, queued or pending. The DTO does not recalculate send-time eligibility or change any terminal suppression policy.

### MRD-S08.5 — Secret-free attempt and temporal validation

`ReadinessDeliveryAttempt` is a closed equivalent projection of the existing secret-free `DeliveryAttemptRecord`. Its exact fields are `id` (`Reference`), `eventId` (`event_id`, UUID), `channel` (`DeliveryChannel`), `attempt` (strict integer1–9007199254740991), `status` (`DeliveryAttemptStatus`), `responseCode` (`response_code`, null or strict integer100–599), `nextRetryAt` (`next_retry_at`, nullable Shanghai timestamp), `deliveredAt` (`delivered_at`, nullable Shanghai timestamp), and `errorCode` (`error_code`, nullable existing `ChannelErrorCode`). Nullable attempt-record fields retain native nulls. Reuse `CLAIMED`, `DELIVERED`, `RETRY_PENDING`, `FAILED` and the original closed safe error enum; introduce no parallel verdict/dispatch enum or raw error text.

A nested attempt must match both the notification's exact `eventId` and its containing `channel`. Only `status=DELIVERED` has a non-null `deliveredAt`; it also has no error or retry deadline. `CLAIMED`, retrying, queued intentions and read acknowledgement cannot express delivery. Where original creation/observation times are known, event creation/target, historical update and delivery times must be ordered within them; in particular `createdAt <= historicalUpdatedAt <= observation.observedAt`. All supplied timestamps are timezone-aware Shanghai values. Unknown times stay null, and DTO validation never samples a clock or renews them. These shape checks are necessary, not proof of an actual successful send: the later reader must resolve the original dispatcher receipt.

Forbid unregistered fields, endpoints, tokens, approval tokens and raw errors. Validation must not copy unsafe error strings into `errorCode`. Do not serialize channel secrets or infer a positive delivery/readiness claim from these optional facts. Acceptance covers old-byte omission compatibility, native result identity/no recalculation, strict/null/immutable boundaries, paired signal references, original owner/leaf limits, duplicate channels, wrong event/channel binding, illegal delivery times, safe error enums and absent-event/attempt semantics.

### MRD-S08.6 — Risk comparison, obligation, origin and maintenance

Nullable, default-omitted `RuleReadinessFacts.risk` contains a closed, frozen, strict `ReadinessRiskFacts`, only for the exact `RISK_BRANCH` owner with `side=SELL`:

| Field | Type / nullability | Meaning |
| --- | --- | --- |
| `current` | Native `DailyRiskEvaluation` or null; omit null | Copy this evaluation's actual severe condition evidence or ordinary `ordinary_close`, retaining native snake_case names, owner, target and time. Absence is not FALSE. |
| `obligation` | `ReadinessRiskObligation` or null; omit null | Actual current RISK's `riskId`, `revision`, `kind`, `status`, `confirmedTradeDate`, `earliestExecutionDate`, `fulfilledAt`, `blockers`; no quantity or permission. |
| `origin` | `ReadinessRiskOrigin` or null; omit null | Original immutable `evaluationId`, `planVersionId`, `contentHash`, `reviewId`, `activationRevision`, `evaluatedAt` and native `DailyRiskBirth` in `birth`; supply only after `read_risk_origin()` verifies it. |
| `maintenance` | Required existing `AxisReadiness`; `axis=DATA_EVALUATION` | Actual maintenance status and its own `ReadinessObservation`, separate from whether a new comparison occurred. |

Use the unique `ReadinessRiskObligation` component, without reusing/changing old public `DailyRiskState` or importing report/backtest models. Projection fields use existing `ApiValue` camelCase aliases; `current` and `birth` retain native names and native Python/JSON validation. Original IDs and blockers use `Reference` (1–256 characters); revision is a strict integer0–9007199254740991, activation revision is1–9007199254740991, blockers retain the complete tuple up to128 entries. Obligation's three nullable date/time fields retain nulls. Do not infer missing values.

`fulfilledAt` may describe an earlier cause: native new-cause reset retains old fulfillment/cutover history while status becomes `CLEAR`, `PENDING` or `CONFIRMED`; the new `confirmedTradeDate` can be null or later than that timestamp. Preserve this real combination. The timestamp neither fulfills the new cause nor proves skip. Only ordinary risk supports `PENDING`; `CONFIRMED`/`FULFILLED` retain a non-null actual confirmation date.

The existing parent `RuleReadinessFacts.observation` describes the current comparison; `maintenance.observation` describes actual maintenance. Add no third duplicate observation. Origin can belong to another original version/review/activation and must not be rebound to active `ReadinessContext`; matching context/IDs alone verifies neither cause nor maintenance.

### MRD-S08.7 — Risk shape consistency and limits

Current comparison, obligation and birth retain one risk kind; current/birth `risk_identity` matches the parent owner. Supplied parent comparison time/target and complete root match native `current`. Ordinary `ordinary_close` never becomes a condition root/tree. Current severe FALSE can coexist with old `CONFIRMED`; neither changes the other or releases the obligation. Missing origin can coexist with an independently valid comparison and persisted obligation, with origin/maintenance unverified. Old `technical_evidence` never fills `current`.

With `current=null`, supply no completed TRUE/FALSE root/leaf, comparison time or evaluated target. Preserve definition-derived `UNKNOWN`/`MISSING_INPUT` diagnostic leaves where applicable; ordinary risks without a condition naturally have none. `maintenance=PASS` requires a `CURRENT` observation with known `asOf`, an obligation, and origin for non-`CLEAR` obligations. Without `current`, only ordinary `CONFIRMED`/`FULFILLED` fits the designed-skip shape. These checks do not prove producer behavior, source identity, original ownership or read consistency. An origin identifies an immutable evaluation after its birth close, not an evaluation-head pointer; supplied history cannot follow a known maintenance observation. A `CURRENT` parent comparison matches admitted plan/content/activation; comparison and maintenance observations cannot mix contexts.

Retain six axes,76 owners,50 leaves,1MiB, existing freshness policies and literal `authorityGranted=false`. Embedded native risk trees also count toward50 leaves: per owner use the larger of parent diagnostic leaves and native current condition leaves, without counting the same projection twice. This shape slice does not implement assembly, `changed_readiness()`, summary applicability or READY.

### MRD-S08.8 — Later consumer's narrow ordinary designed-skip rule

A later consumer may exclude only a proved ordinary `CONFIRMED`/`FULFILLED` designed skip from UNKNOWN rules representing missing applicable authority. It must verify all of:

1. A current owned immutable EVAL, exact target, generation/configuration, freshness and all sources required by maintenance. Missing observation fields alone never prove skip; no new producer marker is needed.
2. Complete current SQL RISK payload/revision equals that EVAL's unique exact RISK, including `origin_evaluation_id`; `read_risk_origin()` verifies the original cause. All original source bindings participate in the second read.
3. Actual native skip, with no new birth, pending new cause, cutover requiring comparison, or applicable new comparison. A new cause after `FULFILLED` cannot borrow old fulfillment/origin or a shared risk ID as exemption.
4. Actual `maintenance=PASS` with existing expiry, without inventing `current`, completed roots/leaves or comparison time. All other rules and six axes participate normally.

This narrows applicability, keeping summary priority unchanged. Missing/expired sources, changed RISK/origin, older snapshots without native risk facts, new birth and missing actual comparison evidence remain UNKNOWN/failures; real `MISSING_INPUT` retains its original priority. Unknown notification/delivery also remains applicable. `changed_readiness()` must clear new current/maintenance claims and preserve diagnostic leaves; DATA_EVALUATION and summary must both consume only verified maintenance with its expiry. This needs a separate narrow consumer/summary implementation and real production/race tests; the model slice does not implement or accept it.

For later ordinary `ordinary_close` consumption, map only actual native branches under MRD-S03, without inventing condition roots/leaves: a complete `CLEAR`/`OBSERVATION` with `below=False` and no input gaps, including an actual second close with `below=False` transitioning to `OBSERVATION`, may display `CONDITION_FALSE`; actual `confirmation_close_used` transitioning to `CONFIRMED` may display `CONDITION_TRUE`. First breach, early close or restarted adjacent-pair `PENDING` cannot establish two-close confirmation from `below=True`. Only the actual updated second-close date (`second_close_date_after`, retaining `expected_second_close_date` as prior-comparison context), official calendar, owner scheduling and complete required prior inputs, with that event still in the future, can establish `WAIT`; otherwise remain `UNKNOWN`. Real missing inputs retain original `MISSING_INPUT` priority. This native-field mapping is for later consumer acceptance, not implemented by this model slice.


The bounded consumer is delivered in `7c4404c`, with verification and operational limits in [PMA-R86](../../verification/2026-10-27-plan-monitor-assurance.md#pma-r86--actual-risk-readings-and-narrowly-proved-maintenance). Default prior-day intraday reuse remains UNKNOWN until complete current admission is established; this adds no producer refresh or scheduling behavior.


## MRD-S09 — Narrow current IN_APP service verification

This implements MRD-S02/03/05's separation of monitoring service, sending eligibility and successful delivery; it introduces no strategy, automatic test send or new approval flow. R87/R88 supply actual configuration and exact historical receipts, not a current service PASS by themselves.

A current service check may be recorded only by the existing real dispatcher/production deadline path. Retain one bounded latest immutable check, tied to the actual sole native `InAppChannel` instance, existing runtime generation/configuration, and exact existing completion contexts (at most10 plans). Record original start/completion times, actual successful IN_APP storage-check evidence and the original applicable owner/target expiry bounds. A closed/disabled dispatcher returning an empty tuple is not a successful check. Startup recovery without a proved evaluation context cannot certify a plan. The getter and readiness GET perform no work and do not refresh timestamps.

New check start, incomplete/failed/cancelled work, storage error, instance replacement, closure, configuration/generation change or changed relevant completion context revoke the previous current check. Later unrelated progress or repeated GETs cannot extend its captured expiry. Reuse the existing coherent-read identity and minimum freshness bounds; add no universal TTL, per-event cache, worker or history scan.

For the actual sole native IN_APP configuration, a current successful check plus independently verified complete current FALSE evaluation and absence of applicable delivery obligations may establish notification service PASS without an event. Absence must come from exact native evaluation and applicable original SIGNAL/RISK/candidate facts, not empty event IDs, a bounded scan or FALSE alone; unresolved obligations remain UNKNOWN. A precise already-DELIVERED IN_APP receipt may establish fulfillment of that exact obligation when current service verification and ownership also hold; it does not make current eligible true or permit another send. The first slice may accept only the provable subset and must list remaining UNKNOWN cases explicitly.

Do not generalize this zero-event proof to WEBHOOK, CONSOLE or custom adapters sharing the same enum. A scan cursor/limit can omit existing events: checked storage is not an empty queue or universal event coverage. Current WAIT/eligibility requires separately proved actual scheduling/dependency facts; historical CLAIMED/RETRY_PENDING or an earlier allowed decision alone is insufficient. Keep absent/uncertain verification as UNKNOWN/DELIVERY_UNVERIFIED, retain accurate historical facts, and never manufacture a signal to obtain a green state. Acceptance requires actual producer/dispatcher work, current complete-FALSE/no-obligation success, hidden obligations, wrong/missing/expired context, failed/closed/replaced instance, no GET side effects and unchanged historical/API boundaries.

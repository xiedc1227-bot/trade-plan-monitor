# Proposal: Backtest the Monitoring Loop

> **Repair baseline restored, 2026-10-10:** ML01–ML13 below restore the original daily-continuity requirements from `e95de03ec809517cc0a3b2484c6145675418960c`. The user has authorized implementation of RP-T01–RP-T20 in this repair session. The [repair plan](../../../tasks/plan.md) controls the exact file boundaries and expressly retained later platform choices; its RP sections override superseded proposal details. Implementation authorization is not completion or approval of unreviewed concrete API changes. ML14–ML18 and historical verification remain evidence of the previous narrower delivery, not acceptance of this repair.

Module: `backtest-engine`; adapters: `backtest-data`, `backtest-jobs`, `backtest-results`, `backtest-api`, `backtest-web`. [Chinese review copy](PROPOSAL-monitor-loop-backtest.zh-CN.md). Current tasks: [todo.md](../../../tasks/todo.md).

## ML01. Objective and assumptions

The user has confirmed the main workflow: **first plan establishes the opening position → daily plan updates derive add/reduce conditions → monitoring triggers add/reduce reminders → simulated execution → account/state feedback → continued monitoring until the end date**. The first plan's existing holdings initialize the account once; they are not purchased a second time. The user supplies the plan collection and response settings; the run discovers reminder and trade times from historical evidence.

Assumptions proposed for review:

1. The user supplies the first historical plan and all follow-up plans together. Extract and review the source plans into Schema 5 before the run. The first plan anchors the historical account/timeline and provides explicitly stated initial holdings and costs; today's job creation/import time is not the historical start. A plan reviewed today may be researched over past dates, but the report must not imply it was known then.
2. Automatic updates include inventory, sellable quantities, consumed signal occurrences, risk state, and the resulting monitoring view. Strategy text, thresholds, quantities, or logical branches do not change merely because a reminder fires.
3. Confirmed by the user: all plans are prepared and supplied before the historical run; plan updates occur by day. Freeze a schedule keyed by `symbol` and `effective_trade_date`, and switch plans at the corresponding trading-day boundary. The run does not generate strategy content.
4. The recommended mode applies an explicitly selected simulated response policy to eligible trade reminders. This research authorization never enables automatic live trading.
5. Confirmed by the user: the end date is optional. A supplied date ends the study on that date; otherwise resolve it to the current date in Asia/Shanghai when the run is submitted.
6. Confirmed by the user: one batch upload, followed by sequential per-plan AI extraction in chronological order. This is not one AI request containing every plan. ML13 defines extraction, predecessor binding, validation and retry behavior.

Success means a causally complete, auditable monitoring history; returns are a result of the simulated responses, not the sole acceptance criterion.

## ML02. Observed gaps and intended changes

The current replay already shares monitoring evaluation; it is not a separate evaluator throughout. Its orchestration is the gap:

| Observed current behavior | Proposed behavior |
|---|---|
| `research_session.py` constructs one plan and activation identity. | A session owns the active plan version, its activation revision, and evolving execution state. |
| `research_input.py` / UR03 require explicit operations targeting an exact occurrence. | Ordinary research needs a response policy, not a prewritten list of future trades. Recorded actions remain an optional replay mode. |
| `research_runner.py` marks ordinary authority ended after `REPLACE`. | Successful replacement invalidates old ordinary authority, binds the successor, refreshes requirements, and continues the same run. |
| `_ResearchRuntime._enqueue` suppresses notifications. | Capture reminders through an isolated sink, including the same eligibility and stale-evidence checks that precede live delivery. |
| `_simulate` updates inventory, consumes the signal, and may fulfil risk obligations. | Reuse those transitions, then refresh the monitoring view and derived requirements before subsequent actions. |
| UR06 may preserve a monitoring receipt after research cash becomes insufficient. | In the new mode, cash checks, inventory changes, signal consumption, and monetary entries form one research transaction; rejection changes none of them. |

Current contracts remain [SPEC-unified-plan.md](../monitoring/SPEC-unified-plan.md) and [SPEC-unified-replay.md](SPEC-unified-replay.md). Approval of this proposal would authorize a new monitoring-loop mode that replaces the explicit-script requirement, replacement-ends-run behavior, and post-receipt cash handling **only in that new mode**. Frozen historical runs retain their original meaning.

## ML03. Shared core and environmental adapters

```mermaid
flowchart TD
    P[Reviewed plan and activation] --> C[Derive conditions and evidence requirements]
    H[Historical evidence and virtual clock] --> M[Shared monitoring evaluation]
    C --> M
    M --> R[Eligible reminder captured locally]
    R --> A[Configured simulated response]
    A --> E[Execution checks and atomic research accounting]
    E --> U[Update inventory, signal and risk state]
    U --> C
    V[Preloaded daily plan schedule] --> T[Switch at the effective trading day]
    T --> P
    M --> J[Event history and report]
    E --> J
```

Reuse condition interpretation, signal independence/expiry, risk priority/latching, delivery authorization, execution eligibility, and accounting transitions. First inspect their actual online call paths. Extract shared application participants only where adapters cannot safely use them; do not copy strategy logic or retain a dependency on private HTTP handlers as the intended architecture.

Online adapters use real data, time, storage, notification delivery and explicit user actions. Research adapters use a frozen dataset, virtual clock, private repositories, a recording notification sink and a simulated response policy. No production composition, provider request, live notification or live plan mutation occurs during deterministic replay.

“Derive conditions” means interpreting the reviewed plan and constructing its current monitoring requirements: condition tree, timeframe, warm-up, validity, confirmation, quantity, reset policy and execution window. It does not mean asking an AI to invent new conditions at every market tick. Position/risk changes update eligibility; only an authorized content revision changes strategy definitions.

Before replay, ML13 uses AI to translate supplied text into structured candidates and change descriptions. Programs validate and materialize complete versions; review then freezes the accepted chain. During replay, the monitoring engine only reads those frozen versions and market evidence, with no AI extraction calls.

## ML04. Inputs and state ownership

Freeze all reviewed plan snapshots and their daily schedule, dataset/revisions, run range and warm-up, known cash, dated inventory lots and costs, trading calendar, indicator/adjustment evidence versions, response/fill assumptions, and optional external evidence. Preserve existing point-in-time adjustment and availability checks. Unknown inventory permits observation but blocks execution and full-account return claims.

Proposed schedule fields: `symbol`, `effective_trade_date`, `plan_version_id`, `plan_hash` and an immutable reviewed snapshot binding. Each symbol has at most one entry per effective trading day. Sort and validate the complete schedule before submission; reject conflicting duplicates, unknown/unreviewed versions and non-trading effective dates rather than silently shifting them. Preflight must establish an applicable plan at the run start. Plan validity/activation constraints still apply and cannot be widened by scheduling. These are proposed input fields, not existing API claims.

**Optional end date.** Accept an optional `end_date`. Omission/null resolves once to the submission date in Asia/Shanghai; store the resolved date and whether it was explicit or defaulted. The date is inclusive. Reject an end before the first-plan start or after the submission date; a historical replay does not wait for future dates. A weekend/holiday is a valid end date: preserve the requested date and use the exchange calendar for actual market sessions. Plans effective after the end remain outside this run's decision timeline.

Resolve and freeze the evidence cutoff with the input: for a past end date use the end of that local day; for today's end use the submission instant. Consume only completed, available evidence no later than that cutoff. Do not create today's closing data while the session is still open. Admission checks still require the needed dataset coverage; genuine gaps are shown and handled by the existing coverage rules, not silently treated as an earlier requested end. Reports distinguish the requested/resolved end date, frozen evidence cutoff and actual last market evidence/valuation time. Waiting in a queue, retrying tomorrow or repeating a frozen run does not move its end date or add newer evidence; submitting a new run can use a later current date.

At the cutoff, stop generating and executing intents, retain remaining holdings for valuation and show pending intents as unfilled at the run end. Do not force liquidation solely because the study ended. This terminal run status does not claim the underlying plan's signal expired early.

**First-plan initialization.** Derive the historical start from the first supplied plan, rather than asking for an unrelated start and a manually reconstructed portfolio. Separate the account snapshot at that first-plan point from the earliest executable monitoring time: execution requires the plan to be available and effective. A plan available before trading on September 7 can govern that day; one written after its close cannot produce trades earlier that day. An intraday first plan can initialize the session at its known availability time without backdating it to the opening. Subsequent content updates still use the daily schedule. Show this mapping before running; keep import time separate and load warm-up before the historical start without generating transactions.

Use explicit statements of actual holdings, actual CORE/TACTICAL allocation and cost in the first source to build a reviewed initial-account snapshot. Strategy allocation targets alone still cannot initialize holdings. Bind extracted values to source text and record any confirmed supplements/overrides. Already-owned shares are opening inventory, not a new simulated buy; do not charge purchase fees again or infer an acquisition date from the plan date. Unknown cash or acquisition/sellability facts remain missing inputs: request them when needed for funded trading/T+1 checks, or explicitly limit the run to observation with incomplete account valuation. Never insert an arbitrary cash balance or assume all opening shares are sellable.

The user's pasted first plan from [盛新锂能中期波段交易计划](https://chatgpt.com/c/6aa21e11-9d54-83ea-8a91-3c401c270008) illustrates the extraction; these are source assertions, not independently verified market facts:

| Source item | Initialization/interpretation |
|---|---|
| `002240`; actual 100 shares; CORE 100, TACTICAL 0 | Seed 100 existing CORE shares once. |
| Cost CNY 40.105/share | Preserve exact precision; total opening accounting cost is CNY 4,010.50 (`401050` fen). Do not round the unit cost to 40.11. |
| Maximum 300 shares | Position ceiling; the remaining 200-share capacity is neither existing inventory nor buy authorization. |
| Reference 28.98; delayed intraday quote 28.45 | Dated reference market observations, not acquisition cost or automatically valid opening valuation. |
| Hypothetical buy 100 at 28.70 and sell at 29.30 | Fee illustration, not an actual fill, opening lot or active order. |
| Ordinary buy/sell currently 0; observation zone 28.50–29.00 | No ordinary buy authorization; do not turn an observation zone into a buy trigger. CORE is not available for the ordinary tactical sale. |
| Technical risk line 25.99; risk exit includes CORE, target 0 | Preserve the declared multi-close confirmation/exit sequence; a simple intraday touch is not authorization to sell. |

Extract the source fee/slippage assumptions as visible research settings for review: commission 0.03% each side, minimum CNY 5 each side, sell stamp duty 0.05%, transfer fee 0.001% each side, and slippage CNY 0.01/share each side. Do not silently substitute a basis-point model. These are supplied assumptions, not a claim about current statutory rates. Do not add hypothetical historical acquisition fees to the stated opening cost without evidence.

Keep original accounting cost and the start-of-research market valuation separately. Measure interval equity change from the initial known market value plus known cash, while reporting historical cost-based P/L separately. Pre-existing losses must not be labelled losses caused by the monitoring period. Missing opening prices/cash block the corresponding return metric rather than replacing cost with a convenient quote.

The pasted source mentions a September 9 report using September 8 close and an update containing September 10 intraday information. September 7 in the user's explanation is an illustrative start, not proof this exact text was available then. Establish the first-plan time from the actual supplied artifact; never backdate this text to September 7. The current design does not choose or run a specific historical dataset.

Preserve unrepresentable clauses as visible limitations: the source's partial fills, pending-order capacity and fundamental-information exits are not fully covered by the current whole-trade technical-monitoring contract. Missing scoped evidence for subjective technical invalidation remains unknown. This source is not a fully executable fixture merely because its initial holdings can be extracted; do not silently omit unsupported clauses or claim complete source-plan parity.

Keep four distinct state groups:

| State | Contents and ownership |
|---|---|
| Plan definition | Immutable source/content hash, reviewed conditions and quantities; new content creates a new version. |
| Monitoring state | Active version/revision, signal occurrences, resets, expiry, risk records, evidence dependencies and reminder identities. |
| Research account | Cash, dated CORE/TACTICAL lots, sellable quantities, costs and fees; shared inventory transitions plus research money entries. |
| Event history | Evidence availability, evaluations, reminders, requests, fills/rejections, state transitions, version changes and valuation. |

Declare research activation independently of production activation. Bind imported research review declarations explicitly; do not manufacture historical human facts. Inspect all scheduled plans to preflight and preload the union of data requirements, but expose only the currently effective plan to decision-making. Future plan contents cannot influence earlier conditions, actions or event identities. Market and external evidence keep their own availability cutoffs. Missing successor data blocks affected conditions with a reason; it never silently falls back to the old strategy.

## ML05. Event time and one monitoring cycle

Drive evaluation with evidence availability and scheduled lifecycle boundaries, not just a loop over price rows. The calendar must advance expiry and T+1 sellability even when no new price arrives. At a timestamp, process a deterministic sequence:

1. Make newly available market revisions and scoped external facts visible; apply calendar transitions.
2. At the trading-day boundary, apply that day's scheduled plan before the first monitoring evaluation or execution attempt; also apply explicitly ordered deactivation and approved reassessment events. Reject ambiguous competing lifecycle events. Invalidate old pending ordinary actions before they can execute. No scheduled intraday plan-content switch is supported in this design.
3. Freeze the current plan/state revisions and evidence cutoff, derive requirements, and run shared monitoring. Missing dependencies yield unknown/blocked conditions.
4. Recheck reminder eligibility using current revisions/evidence and capture the simulated delivery. Pure technical alerts cannot authorize a trade. Delivery here means a configured research assumption, not proof of real external delivery.
5. Process eligible response intents. A new intent can use only a future eligible price interval; an older intent may attempt execution now. Use shared risk/conflict priority; do not invent a favorable buy/sell order for simultaneous conflicting signals.
6. For a successful attempt, atomically commit cash/fees, dated lots, occurrence consumption and risk fulfilment. Refresh affected monitoring state before considering another intent. Rejected attempts leave those states unchanged.
7. Record before/after state and mark available prices for valuation. Post-trade refresh cannot create a new independent occurrence by repeatedly consuming the same evidence. No zero-time trade loop is allowed.

Formal daily confirmation still executes only in `NEXT_EXCHANGE_SESSION_ONLY`; completed five-minute confirmation retains `CURRENT_SESSION`. `PLAN_ACTIVE` does not extend a single signal's execution window. Warm-up never generates reminders or trades. Late corrections are new events and never rewrite already recorded history.

## ML06. Reminder response and fill policy

Offer three business-facing modes; names below are proposed contract discriminators, not current API fields:

| Mode | Behavior |
|---|---|
| `FOLLOW_REMINDERS` (recommended) | A frozen policy responds to each currently authorized ordinary/risk trade reminder with one complete requested quantity. |
| `OBSERVE_ONLY` | Record reminders and state changes; no generated execution requests. |
| `RECORDED_ACTIONS` | Replay explicitly supplied user actions; no additional automatic response. Useful for historical comparison and parity fixtures. |

The first mode requires the user to select the policy at run creation. It applies to executable trade reminders, not every Boolean condition or pure technical alert. Retain one intent per authorized occurrence, even if delivery is repeated. Risk intents bind the current risk revision/target, not an obsolete quantity.

Recommended initial fill model: full quantity at the **close of the first eligible completed one-minute interval whose start is at or after the response's ready time**, with configured slippage and fees. Ready time includes reminder availability plus a frozen response delay (proposed default: 0 seconds). A minute already in progress at decision time is ineligible. The result becomes known only when that minute's evidence is available; recheck current authority, risk, quote applicability and price limits then. Record both price time and availability time. Never fill at the close that first generated the same reminder.

For example, a five-minute confirmation available at 09:35:12 cannot fill at 09:35 or 09:36 using the 09:35–09:36 interval; the first candidate interval is 09:36–09:37, evaluated only after its evidence arrives. A daily reminder waits for the next eligible exchange session. End-of-run intents remain visibly unfilled.

Enforce current full-quantity positive 100-share units, T+1, CORE protection, position limits and risk/conflict checks. Check cash including fees before commitment; no partial quantity substitution. Cash/sellability/market blockers may be retried on subsequent evidence while authority remains valid, with one attempt per intent per eligible interval. Expiry, consumption, replacement or deactivation closes ordinary intents. Insufficient data/liquidity evidence yields an explicit blocked/unsupported attempt, never a fabricated fill. Preserve conservative existing suspension/price-limit rules; minute bars cannot establish queue priority or real execution certainty.

## ML07. Plan updates and successor continuity

There are two update paths, both visible in the timeline:

**Execution-state update.** A fill changes cash/lots and the corresponding signal/risk state; the next monitoring view uses the new holdings, capacity, sellability and consumed occurrence. A satisfied condition alone, notification delivery, or read receipt does not change inventory. Repeated buying requires the plan's existing independent-signal reset rule, not simply a new day. No new sell condition is invented when a buy fills.

**Daily plan-content update.** All reviewed versions are supplied before the run. At the start of `effective_trade_date`, before any evaluation or execution: recheck the scheduled binding → end old ordinary authority and pending intents → activate that day's version → rebuild requirements → continue monitoring. Use the exchange calendar in Asia/Shanghai. Initialize the applicable version before the first event for an intraday run start; do not replay pre-start trades. Draft saving alone does not switch plans. Carry cash/lots, acquisition dates, costs and existing risk obligations across the switch; never reset the account or silently release risk. Risk reassessment follows the existing explicit evidence rules.

Schedule semantics (carry-forward confirmed by the user; other defaults remain proposed):

- A schedule row states the day a plan starts governing monitoring, not necessarily its creation/report date. A plan using day D's close must be assigned to the next eligible trading day, never day D's opening. Later-authored retrospective plans remain explicitly labelled experiments.
- Confirmed: with no new row on a day, continue the most recent still-valid active plan. Show this carry-forward in the preview. If its authority has expired or was deactivated, do not extend it; record no ordinary plan authority while preserving risk obligations and account valuation. Reject an uncovered run start before running.
- Repeating the same immutable version on adjacent days is continuation, not a fresh activation; preserve occurrence/reset/consumption state. A genuinely different scheduled version uses the existing replacement semantics.
- An old ordinary daily signal that was due to execute today loses authority if a different plan replaces its owner before execution. Do not silently transfer it to the new version. Without replacement, it retains its original next-session window. This consequence must appear in the report and acceptance fixtures.
- Loading every future plan into storage is not permission for the monitoring core to read it early. No strategy generation, AI generation call, automatic content editing or intraday strategy update occurs during replay.

Example: D1 schedules P1, D2 schedules P2, and D3 has no row. D1 monitors P1; D2 switches to P2 before monitoring and retains the accumulated account; D3 continues P2 if still valid. The preview expands this into an explicit daily plan calendar.

Initialize the account from the first plan only. Later plans' statements such as “currently 200 shares” or “now flat” are historical observations, not instructions to overwrite simulated holdings/cost/cash. Compare them with the replay account and show discrepancies. In `FOLLOW_REMINDERS`, the ledger evolves only through its simulated fills; do not fabricate trades to match a later description. If a follow-up strategy is explicitly contingent on a different account state, mark the affected instructions incompatible pending an explicit reviewed interpretation, rather than inventing quantities or changing their meaning. `RECORDED_ACTIONS` may apply separately evidenced actual trades with their prices, quantities and times; a portfolio statement alone is insufficient. The report describes execution of supplied historical plans, not a claim that these fixed follow-ups would have been authored identically under a different simulated trading history.

The authoring date records when the plan was actually written, for provenance and interpretation of its information context; preserve an exact timestamp when available. The effective trading date selects when that version starts governing monitoring. Import time is a third, separate storage event and changes neither date. For example, a plan written on Monday evening using Monday's close starts on Tuesday; if no new plan arrives Wednesday, it continues while valid, with its original Tuesday effective date unchanged. A plan written Friday for next Monday can be stored over the weekend without becoming active early. Importing historical plans today preserves their original authoring/effective dates. A plan actually authored today but assigned to a past trading day is a retrospective experiment, not a historically available plan. Date labels alone do not prove absence of future information; underlying evidence cutoffs still require validation. Only the effective trading date drives schedule selection.

## ML08. Persistence, determinism and limits

Reuse existing durable jobs, frozen datasets, isolated result storage, cancellation and atomic report publication. Use a new versioned input/report discriminator for this mode; exact version identifiers and API schemas belong to the approved interface design. Do not relabel old `backtest-run-v4` or `backtest-report-v3` data with changed semantics.

The run identity includes normalized input, plan-chain/evidence artifacts, dataset identity, response/fill policies and relevant engine versions. Event identities depend only on their causal past, so changing future evidence cannot rename earlier events. Task IDs, retries and wall-clock time stay outside semantic identity. Preserve cash and inventory in one private transaction with stable idempotency keys; a failed worker attempt can restart from frozen input with identical output. Mid-run checkpoint optimization is not required initially.

Retain the current 70,000-decision-event bound; include any added monitoring refreshes in the count. Freeze and validate separate finite limits for captured reminders, intents, plan revisions and attempts during interface design; exceeding a limit fails visibly and publishes no completed report. Stream the audit trail rather than keeping the entire run in memory. Missing condition evidence is a recorded business blocker; unsupported inputs or engine errors are run failures. Canceled/failed runs never appear as completed performance results.

## ML09. User workflow and reports

The create page accepts the first plan and all follow-ups in one batch, then previews the extracted first-plan start, initial holdings/cost/allocation and daily effective-date schedule. The user optionally supplies an end date (blank means today in Asia/Shanghai), chooses the dataset and response mode, and fills only genuinely missing account inputs such as available cash or sellability evidence. Show the resolved date and available-data cutoff in the submission result. Execution assumptions and optional timed facts are advanced inputs. Ordinary use does not require raw operation JSON or retyping initial values already explicit in the plan. Preview a calendar showing each day's effective plan, switches, carry-forward and uncovered days, alongside unresolved plan bindings, duplicate dates, account-context discrepancies, data/warm-up gaps and unsupported clauses. Clearly label whether this is a historical plan replay or a retrospective experiment using later-authored plans.

The main result is a timeline: **active plan → condition/evidence → reminder → response → fill/blocker → state update → next monitoring cycle**. Show a plan-version lane, holdings/cash/equity charts, and reminder-to-execution counts including rejected/expired/unfilled intents. Each step links to its causal event, active version, cutoff, state revision and reason. Distinguish “condition satisfied”, “reminder eligible”, and “trade completed”.

Before starting the run, show extraction progress per plan, failed/needs-review items, each version's condition diff and the complete daily plan calendar. Let the user correct or retry the affected item and review the resulting chain together. Do not require uploading the entire collection again after one extraction failure. Batch upload/extraction is preparation; ML04's default end date and cutoff are resolved at backtest submission, not at the earlier upload time.

Include return/drawdown/fees/turnover only where valuation is valid; label missing prices and unknown holdings. Observation-only results emphasize reminders and may show mark-to-market on known initial holdings; never attribute that change to simulated trades. A return curve alone cannot demonstrate monitoring parity.

## ML10. Acceptance criteria

| ID | Required evidence |
|---|---|
| ML-A01 | Without any scripted trades, one reviewed plan produces a buy reminder, a policy-generated full fill, updated inventory, a later independently eligible sell reminder/fill, and continued monitoring. Prices/quantities are declared fixture values, not invented production strategy. |
| ML-A02 | Repeated true conditions and repeated reminder delivery do not duplicate trades; only the declared reset policy creates another occurrence. State refresh cannot consume the same evidence into an infinite loop. |
| ML-A03 | Pure alerts and `OBSERVE_ONLY` never mutate holdings; `RECORDED_ACTIONS` adds no automatic requests. |
| ML-A04 | Completed five-minute/daily/mixed conditions, delayed reception, warm-up, gaps, corrections and the 09:35:12 example obey point-in-time availability and execution windows. Changing future inputs leaves earlier events unchanged. |
| ML-A05 | Fees-inclusive cash failure, T+1, CORE, max position and full-quantity rejection leave cash, holdings and signal consumption atomically unchanged; a later valid attempt can succeed exactly once. |
| ML-A06 | Shared risk/conflict priority governs simultaneous candidates; no favorable arbitrary ordering. A new risk or stale evidence blocks a queued positive reminder/intent. |
| ML-A07 | Successor activation invalidates old ordinary intents, preserves lots/cash/risks and continues with new conditions in the same run; draft-only changes have no effect. Unknown or unreviewed successor content is blocked. |
| ML-A08 | Feed identical facts, lifecycle changes and execution outcomes through online application participants and the research adapter; compare semantic reminders and state transitions event by event, with independent expected-value assertions. Exclude only environmental delivery IDs/time. |
| ML-A09 | Repeated runs/retries produce identical canonical reports; cash/inventory commits are fault-tested; cancellation and all finite-limit failures publish no completed report. Old frozen reports/exports remain byte-compatible. |
| ML-A10 | Existing API/job/result paths and a browser flow create and inspect the loop without handwritten future trades; deterministic tests make zero live-provider, AI, notification or production-database calls. |
| ML-A11 | Preload P1/P2 and switch only at their effective trading days before evaluation/execution; retain account state. Cover carry-forward, expired plans, uncovered start, duplicate/non-trading dates and intraday run initialization. Repeating the same version does not reset signals. Replacement cancels old next-session ordinary intents; continuation preserves their window. Editing future P2 cannot change earlier P1 decisions. |
| ML-A12 | Extract the first-plan 100 CORE shares, 0 TACTICAL, cost 40.105/share and ceiling 300; preserve total cost `401050` fen without an opening simulated buy or duplicate purchase fee. Reference quotes/hypothetical fee trades do not initialize lots. Missing cash/sellability stays explicit. |
| ML-A13 | A later plan declaring 200 or 0 shares cannot overwrite the replay ledger; detect incompatible account-dependent instructions. Interval return and historical cost P/L remain distinct. |
| ML-A14 | Today's import/job time does not replace the first-plan historical start; no trades precede its availability/effectiveness. The supplied September 10 information cannot drive September 7 decisions. Unsupported source clauses remain visible rather than silently translated into executable rules. |
| ML-A15 | Explicit and omitted/null end dates produce the correct inclusive Asia/Shanghai boundary. Cover UTC/local-day differences, queueing across midnight, retries, holidays, today's incomplete session, invalid before-start/future dates and genuine data gaps. Frozen reruns do not extend the cutoff; reports show actual coverage. Ending preserves open holdings and does not create a liquidation trade. |
| ML-A16 | One batch is extracted sequentially: the first source yields initial-account data and a complete rule candidate; each follow-up sees only its own source and validated predecessor context. No future-plan text enters an earlier request. Every accepted item produces a complete snapshot and traceable change list. |
| ML-A17 | Exercise add/modify/revoke/retain and full-replacement versus partial-update semantics; missing scope or unclear references block dependent extraction. Preserve original bindings for inherited rules; AI cannot invent thresholds, account mutations or approvals. |
| ML-A18 | A failed item retries without re-extracting its unchanged predecessors; unresolved semantics stop dependent items. Changing an earlier source/base invalidates dependent candidates and their reviews, but leaves frozen historical runs intact. Batch review and all required bindings precede replay; replay makes zero AI calls. |
| ML-A19 | App startup/status/monitor navigation/shutdown performs zero backtest preparation even with unusable backtest-only settings. Explicit first-use failure is scoped to backtest; metadata reads never resume jobs or paid work, and queued recovery requires explicit selected authorization. |
| ML-A20 | Concurrent first requests share one lazy initialization; waiter cancellation and failed-init polling cannot duplicate work. Bounded threads/resources drain before retry/replacement; a controlled non-cooperative timeout reports degradation, never forced termination. |
| ML-A21 | Persist cancellation and inject cancel/commit/lease races: committed cancellation wins, stale work cannot publish, lost completed replies reuse verified results. Unconfirmed cancellation is visible; failed/cancelled jobs do not requeue. |
| ML-A22 | Existing storage-domain/notification guards prove separate state; no new deep aliases. Replay makes zero network/AI/live-sink calls. Explicit single-active historical sync retains local fixed pacing, timeout/error handling and cooperative cancellation; monitor request control is unchanged. Global quotas, reserved capacity and cross-business scheduling remain excluded. Low-frequency single-source AI extraction retains existing guards and does not block isolation. |
| ML-A23 | Record Windows 10-stock monitoring baseline/load gates and existing finite single-task/streaming guard regression. Report shared CPU/memory/disk and non-cooperative thread limits; no hard per-thread resource or native-crash isolation claim. |
| ML-A24 | API/UI distinguishes service/job/item failure and stale/unconfirmed views, with scoped stop/recovery. Monitoring remains usable; recovery repeats neither paid extraction nor submission/cutoff resolution. Review concrete bilingual contract changes. |

## ML11. Engineering boundaries and verification

This is one redesign within `backtest-engine`, using existing module boundaries. Expected code ownership: `backtest/` for orchestration/clock/response/account/report adapters; `decision/`, `runtime/`, `state/` for necessary shared participants; `web/` for input/results. Existing `research_*` readers remain available for frozen mode compatibility. Tests belong in `tests/unit`, `tests/integration` and `web/tests`.

The approved per-plan preparation approach also touches the existing `ai/plan_extraction.py`, source-review/domain validation participants and narrowly scoped batch orchestration. Reuse the single-plan extraction capability and add explicit predecessor/change context; do not claim the current prompt already implements batch updates. Keep any changed extraction/prompt contract versioned and regression-tested against existing single-plan behavior. No strategy-generation capability is added.

Use existing strict immutable Python models, snake_case, revision-checked transitions and exact Decimal/integer-fen arithmetic; Vue changes follow TypeScript Composition API and `<script setup>`. Preserve naming and bilingual documentation conventions.

- Always: maintain one strategy evaluator, causal evidence, isolated storage, full-quantity constraints, explicit version contracts and online parity regressions.
- Resolve before extending scope: new production schema/dependencies or shared multi-symbol capital. Strategy generation and intraday plan-content switching are outside this daily-schedule design.
- Never: alter historical bytes, invent thresholds/facts, weaken failing tests, write production state, send real alerts, submit broker orders or silently reinterpret historical runs.

After implementation, run the following from `trade-plan-monitor/` (frontend commands from `web/`), plus focused tests added for ML-A01–ML-A18 and affected extraction/source-review tests with fake AI responses:

```text
.venv/Scripts/python.exe -m pytest tests/unit/test_unified_replay_input.py tests/integration/test_unified_replay.py tests/integration/test_unified_replay_parity.py tests/integration/test_unified_runtime.py tests/integration/test_unified_simulation_transactions.py -q -m "not live"
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
npm run test -- --run
npm run type-check
npm run build
npm run test:e2e
git diff --check
```

Expand tests according to shared-participant changes, retain unaffected capacity evidence, and record actual commands/results in bilingual verification reports. Do not claim these checks have run for this design-only change. Existing unrelated failures are reported separately, never waived by modifying baselines.

## ML12. Decisions for review

Confirmed scope: all historical plans are supplied before the run and activated by effective trading day. The earlier question about generating strategy content is resolved; no generation during replay is required.

Confirmed input workflow: start the historical study from the first plan, extract its explicit initial portfolio and cost, and process the supplied follow-ups thereafter. Initialization occurs once; any missing cash/sellability or source-time ambiguity is an input gap to resolve for an actual run, not permission to invent a baseline account.

The user has confirmed the opening-position → plan update → add/reduce conditions → reminder → execution loop and manual end-date selection with a current-date default. ML04 defines the proposed deterministic cutoff and end-of-run handling; this workflow confirmation does not by itself assert implementation or test completion.

Confirmed extraction choice: upload once, extract each plan separately in chronological sequence, validate/save per item, and preview/review the entire chain before replay. ML13 records this choice; no further choice between one-shot and per-plan extraction is pending.

Recommended baseline: `FOLLOW_REMINDERS`, explicit execution assumptions, automatic execution-state updates and the frozen daily plan schedule. Preserve observation and recorded-action modes. The user has confirmed carrying forward the latest still-valid plan on days without a new entry. ML07's switching before the day's first evaluation/execution remains a design recommendation.

This document specifies the proposed behavior and acceptance contract. Implementation tasks and code follow a later review of the proposal; no implementation is included here.

## ML13. One upload, sequential per-plan extraction

**Preparation sequence.** Preserve the original text, source identity/hash, plan time and explicit ordering for each item. Confirm source boundaries and chronological order before extraction; conflicting dates or ambiguous same-day order require correction rather than upload-order guessing. Source chronology and the effective-day calendar are distinct: multiple same-day source updates still need an explicitly selected effective version under ML04. Freeze a stable item order for the batch and process one item at a time.

1. Extract the first source into initial-account facts and a complete monitoring-rule candidate, keeping those outputs separate as ML04 requires.
2. For each follow-up, provide its source plus the preceding validated structured candidate and retained source bindings. Include earlier source excerpts only when needed to resolve an explicit reference. Never include later plans or future replay results. If the predecessor is ambiguous or incomplete, stop dependent extraction until corrected.
3. Ask AI to identify changes and scope: a full replacement or a partial update, with explicit additions, modifications, revocations and retained conditions. Every change cites the current source; inherited fields retain their original evidence. A program checks targets and applies supported changes to materialize a complete new snapshot plus its diff.
4. Validate the candidate, persist the item result and its predecessor binding, and continue only when no unresolved semantic dependency remains. Show initial-account values, changes and unresolved issues in a batch preview.
5. Review the complete chain through the existing source-bound review process and freeze approved snapshots and the effective-day schedule before backtest submission. Automatic format/consistency validation is not human approval: a clean candidate may support further preparation, but neither it nor its descendants become executable solely by passing validation.

**Update semantics.** For partial updates, retain only the scope supported by the update or an explicit reviewed clarification, such as “other conditions unchanged.” Full replacements must identify removed prior rules in the diff; omission alone does not authorize silently retaining or deleting an unclear rule. Vague instructions such as “new platform” or “obvious deterioration” remain unresolved evidence/parameter requirements. A follow-up account description does not mutate the simulated account. Reusing a rule identifier preserves traceability, not authority for an old signal across a genuine version replacement; ML07 still applies.

**Per-item state and recovery.** Show pending, extracting, validated candidate, needs review and failed states, alongside separate approval status; these are proposed business states, not existing API enums. Save source/base hashes, extraction contract/prompt version, model/provider, candidate/diff/bindings, issues and attempt metadata. A transient/format failure retries only that item using the same frozen inputs, retaining successful predecessors. Semantic uncertainty needs correction, not unlimited retries or silent skipping. No dependent item is processed against a failed or unresolved base.

Each persisted result binds its source revision and predecessor content hash. Editing an earlier source, order, interpretation or base invalidates affected descendants and their reviews; resume preparation from the earliest affected item. Reject a late extraction result if its source/base has changed. Do not overwrite approved frozen snapshots or previously submitted runs. Explicitly re-extracting unchanged text can yield a different candidate; review it as a new result rather than assuming AI determinism. Deterministic replay depends on stored accepted snapshots, not on reproducing model output.

**Why this approach.** It extends the existing single-plan extractor with predecessor context, a sequential batch controller and per-item progress. Local failure recovery and source/diff review are simpler than disentangling all versions from a single large model response. The user still uploads once; preparation may require multiple AI requests, but monitoring/replay requires none.

**Repair boundary clarification (2026-10-10).** Historical planning/approval wording in these restored original sections is provenance, not a new start-permission gate. RP04/RP05 and the per-task file allowlists control implementation: only the three named new production helpers, existing storage/threads/admission participants, no extra exports or shared-core rewrite. ML-A19–ML-A24 remain active. ML14–ML18 preserve later platform choices and executed history; references there to one frozen plan describe the old format, while the new format freezes a daily chain for one symbol/account/run.

### RP04-FIELDS. Concrete repair codecs and field boundary

RP-T01 collision inspection found none of the eight proposed discriminators in production code, tests or generated frontend code. The following is the bounded implementation design, not an assertion of completed API review. Separate new branches preserve the old defaults, serialized fields, hashes and rejection behavior; never add optional fields to an old frozen encoding merely to accommodate the new branch.

| Discriminator | New branch and exact material fields | Compatibility |
|---|---|---|
| `backtest-preparation-v2` | Existing preparation identity/revision/status/times/owned `work_claim`; ordered `items` (1–256). Each item carries `source`, `source_revision`, `candidate_revision`, `candidate`, `attempts`, `base_hash`, and `status`. Candidate bindings add predecessor `base_hash` and source revision/hash; the work claim binds the current `source_id` and base. Whole-chain `review` binds the ordered item identities/revisions/hashes. | Existing SQLite tables, owner tag and receipt identity remain; v1 stays single-source. |
| `prepared-loop-plan-v2` | `preparation_id`, `revision`, ordered `items`, `schedule`, `account`, `account_origin`, `reviewed_at`. Each frozen item retains source/revision, extraction candidate/evidence hashes, complete `version`, source-bound mapping, change list and account-context evidence. Only the first item establishes `account`. | `prepared-loop-plan-v1` remains a single version/account. |
| `monitor-loop-input-v2` / `backtest-run-v6` | Keep `initial_account`, `boundary`, `dataset_hash`, `response`, `costs`, `limits`; `schedule.entries` accepts 1–256 canonical effective-date bindings to complete reviewed versions. New-version `account_context` contains optional `core_qty`/`tactical_qty`, explicit `dependent_rule_ids`, and source `evidence`; it is a comparison/eligibility constraint, not an account mutation. | v1/v5 preserve exactly one entry. New input/run hashes use their own discriminators; old hashes keep their domains. |
| `monitor-loop-dataset-v2` | Keep scope/boundary/days/warmup blockers; replace the single plan binding with ordered relevant `plan_bindings` (`effective_trade_date`, `version_id`, `plan_hash`) and `requirements` as their union. | v1 manifests and copied market artifacts remain unchanged. |
| `monitor-loop-stored-input-v2` | Same `prepared`, `run_input`, `dataset`, `day_hashes` envelope, with the corresponding v2 branches and exact cross-binding validation. | Existing bounded job reference and old immutable bundle remain valid. |
| `monitor-loop-event-v2` | Keep sequence/time/cutoff/causal payload; bind active `version_id` and `authority_id`. Add lifecycle payloads for replacement/continuation/no authority, closed ordinary intent IDs and observed account-context differences. | v1 events retain exact bytes. All v2 lifecycle events count within the existing 420,001-event envelope (`6 * 70,000 + 1`), not an increased limit. |
| `backtest-report-v5` | Same single-run summary, metrics, continuous valuations and event artifact; replace single authority with ordered version bindings and transition facts. | v4 report readers/hashes and older exports retain their meaning; no new export mode. |

Schedule order is canonical by `effective_trade_date`; duplicate days and mixed symbols/markets are rejected. A repeated identical version keeps its original activation/effective day; a reused version ID with different immutable content is rejected. The first source can start intraday. Each successor must be available by that day's first exchange session at 09:30 Asia/Shanghai; later availability is rejected, never shifted. Expired latest content does not resurrect an older version. Calendar preflight rejects closed/unknown effective days and uncovered start. Future-after-end rows remain provenance but never affect earlier selection or required evidence.

Source order is explicit and distinct from canonical schedule order. Missing dates remain unresolved until review; contradictory known source chronology is rejected. Version/activation/event identity excludes whole-chain review time/hash, item attempt/generation IDs and future sources. A version's causal binding covers its snapshot/content, own and inherited past source/evidence bindings, explicit account context and activation time. Changing future input changes run identity, never past semantic identity.

The table uses Python/domain field names. Public transport envelopes retain existing camelCase aliases; embedded research contracts (`input`, `source`, frozen values) retain snake_case. The creation discriminator is therefore `input.schema_version`; mutation envelope discriminators are `schemaVersion`.

The minimal new Web branches use `schemaVersion: "backtest-preparation-v2"` on preparation mutation commands; old commands without it remain v1. Creation keeps `{input: {schema_version, preparation_id, sources}}`. Existing `PUT /api/v1/backtest-preparations/{preparation_id}/source` accepts `{schemaVersion, expectedRevision, source?, sourceOrder?}`: `source` is the complete existing `PreparationSource` with its stable `source_id`; `sourceOrder` is an exact permutation of all existing source IDs (1–256), not insertion/deletion. At least one is required. The earliest changed source/order position invalidates that item and every dependent candidate/review; unresolved physical work retains the slot.

Extraction/retry adds `sourceId`, `expectedSourceRevision`, `expectedBaseHash` to the existing revision command when selecting an affected item; initial sequential extraction starts at the earliest unresolved item. Cancellation/recovery remain whole-operation commands with the existing generation/physical-drain checks. Chain review supplies the exact ordered item source/candidate/base/evidence bindings, per-item reviewed corrections and one opening-account declaration. Only `GET /api/v1/backtest-preparations/{preparation_id}/items` is added, with `expectedRevision`, `offset` (0–255) and `limit` (1–100); a changed preparation revision conflicts instead of mixing pages. Root progress and item pages keep the existing 2 MiB preparation projection bound. HTTP mutations keep the 4 MiB total encoded-body bound and reject before partial admission.

Run creation adds an explicit `schemaVersion: "prepared-loop-plan-v2"` branch to the existing prepared command (`preparationId`, `manifestHash`, `response`, `costs`, optional `endDate`). The server resolves the frozen chain/dataset and returns one existing job/run receipt. Existing job enums, idempotency, origin guards, errors, recovery and result pagination limits do not change. RP-T14 must review the actual generated diff in both profiles before recording any contract approval.

RP-A09's synthetic four-version fixture is `tests/fixtures/monitor_loop_continuity.json`; its literal oracle is verified by `tests/unit/test_monitor_loop_continuity_fixture.py`. Fixture validation is a baseline, not proof that the runtime already implements continuity. Old-mode fixtures and second-entry rejection checks remain compatibility requirements throughout the repair.

## ML14. Why backtest startup is currently coupled

Source inspected on 2026-10-07 at `main` `e95de03`. These are code findings, not new runtime acceptance results.

| Current path (relative to `src/trade_plan_monitor/`) | Finding |
|---|---|
| `web/app.py:create_production_app` | Supplies a default backtest lifecycle factory whenever none was injected. Opening the existing Web application therefore includes backtest service preparation even if the user never submits a run. |
| `backtest/composition.py:create_backtest_composition` | Opens the cursor key, historical market database and result/job database, then constructs services and the coordinator. This prepares query/submission/recovery capability; it is not execution of a historical study. |
| `web/lifespan.py:create_runtime_lifespan` | Starts monitor, AI, plan service and backtest sequentially before `yield`. A backtest factory/interface/start exception escapes startup and enters shared cleanup, which stops the already-started monitor. |
| `backtest/jobs/coordinator.py:start` / `_run` | Starts a background coordinator, which may claim previously queued work or recover expired leases. A fresh application with no jobs does not manufacture a new replay. Existing operations run in a dedicated thread, not the Web event loop. |
| `_execute_claim` / `shutdown` | Ordinary operation exceptions normally fail only the job. Coordinator/store errors can disable the service. A timed-out shutdown cannot terminate an already-running thread. |

**Business relationship:** backtest needs application-owned configuration, storage, API bindings and a task lifecycle. These resources must be prepared before affected operations are accepted. It does not need to succeed before monitoring or the website becomes available. The current all-or-nothing startup policy is an implementation choice, not a business dependency. The empty-WAL repair addressed one store error without changing that policy.

The user selected **same-process business isolation with dedicated backtest threads, prepared only on explicit first use**. No child process is required now or as a mandatory later step. Process/service/remote deployment alternatives remain unselected; introducing them requires a new scope decision. [ADR 0008](../../decisions/0008-isolate-backtest-service-lifecycle.md) records the selected lifecycle boundary and its limits.

## ML15. Selected thread and state boundaries

Keep one product, one Web/API entry and one application process. Preserve the existing single execution slot and result/job database ownership from ADR 0001. The current coordinator already owns a dedicated execution thread and a bounded repository executor; the missing boundary is independent startup, failure, recovery and cleanup, not creating one thread per stock or merely adding another replay thread.

Web startup registers only inert backtest routes and lightweight lifecycle/status bindings; no backtest preparation or background warm-up follows startup. Explicit first use requests guarded preparation; blocking work stays in lazily acquired, explicitly owned bounded executors. Service states are independent of monitor health, preparation items and jobs. Existing routes remain mounted; unavailable backtest operations return scoped errors instead of preventing application startup.

Share immutable rules/application participants, never mutable live runtime/account/clock/notification instances. Research owns one frozen plan, account, virtual clock, tagged preparation/market/results stores, private transactions and captured reminders. Replay constructs no live provider, AI or real sender. Initialize opening holdings/cost once; fixed plan text cannot overwrite the evolving ledger.

On 2026-10-07 the user adopted compatibility-only storage protection: preserve independent default backtest databases, existing path normalization and `storage_guard.py` rejection of live-monitor tables or mixed market/result domains. Add no deep actual-file identity checker for Windows case, symlinks/junctions or hard links, and no new cross-file alias framework for WAL/SHM, keys, logs or staging. Regress the existing guards; this scope does not claim exhaustive alias or filesystem-race protection. Preparation extraction and historical sync require explicit requests and separate transports. On 2026-10-07 the user confirmed that low-frequency AI extraction must not block resource isolation: preserve ordinary single-source extraction guards; no new global AI quota infrastructure or monitor-controller change is required for this purpose.

On 2026-10-07 the user narrowed the former "reserve live market capacity" item to local historical-sync pacing. Preserve one active sync operation and add only a fixed minimum interval between outbound sync request starts. Reuse the existing 1.25-second live pacing value as a conservative local default; this is not a combined provider-quota guarantee. The wait observes existing cooperative cancellation, and requests retain existing timeouts/error mapping. A failed or rate-limited sync reports its existing failure; no new automatic retry policy is introduced.

Keep formal monitoring's current request controller and transport behavior. Do not add a global quota pool, reserved capacity, cross-business priority queue, per-account/per-interface budget registry, shared cooldown or adaptive allocation. No AI connection, monitoring-module change, quota settings UI or new generic admission framework is required. Implement within `backtest/sync.py` and verify serial request spacing/cancellation with fake calls. Shared host/network contention remains covered by the existing offline load acceptance; this scope does not claim complete provider-quota isolation.

Expose application services directly inside the process; no IPC channel, worker handshake, public worker port, process launcher or backtest CLI is introduced. Immutable command values cross thread boundaries. Database connections and progress/cancellation ownership must respect their existing thread rules; do not share a connection merely because both businesses are in one process.

## ML16. Independent startup, failures and recovery

Proposed backtest service states: `DISABLED`, `NOT_INITIALIZED`, `STARTING`, `READ_READY`, `READY`, `RECOVERING`, `DEGRADED`, `STOPPING`, `STOPPED`. Preserve existing job enums. Job failure does not degrade a healthy service; initialization failure does not fail every historical job.

**On-demand policy:** application startup registers only inert backtest routes and a lightweight lifecycle manager in `NOT_INITIALIZED`. It does not call the backtest factory/start, validate backtest-only paths/credentials/schema, open a backtest database/key, create a backtest executor/coordinator, scan/recover jobs or schedule background warm-up. Valid monitoring and Web dependencies determine application readiness; a backtest-only defect cannot fail it. Configuration required by monitoring itself remains a monitoring dependency.

First explicit use of a backtest data API requests preparation. Loading frontend code, prefetching routes, opening monitoring pages, schema generation, health/status polling and whole-app shutdown do not initialize backtest. GET `/api/v1/backtest-service` reports `NOT_INITIALIZED` without touching stores. A user visiting a backtest page triggers its actual data request; direct API callers use the same gate.

Initialize only the capabilities needed. Historical result/dataset/job reads prepare bounded metadata/read resources and reach `READ_READY`; they do not start execution, acquire AI/market permits or resume queued tasks. Valid explicit extraction/sync/verify/run requests activate required execution resources and reach `READY`. Merely viewing history must not trigger an old paid sync/extraction or replay. The current all-in-one factory therefore must split metadata/service preparation from coordinator activation, preserving store ownership and existing identities.

Use one in-process single-flight initialization task guarded by a lock/generation; concurrent first requests share it and cannot duplicate stores/executors. Run blocking preparation on an owned lazily created executor. Cancellation of one HTTP waiter must not cancel shared initialization. A proposed 1-second response wait returns the requested result if ready, otherwise scoped 503 with bounded `Retry-After` and a status projection; it never returns a false empty list or accepted job. Mutation retries use the original idempotency key. Input/cutoff is frozen at the actual durable admission reservation, not at a rejected pre-initialization request.

At first use show `STARTING`, then `READ_READY` or `READY`. Initialization failure shows `DEGRADED`, preserves the entered form and leaves monitoring unchanged. A proposed 5-second initialization watchdog reports slow preparation but cannot forcibly cancel a thread. Once failed, status polling/data refresh must not create endless retries: repair/retry is explicit, single-flight and allowed only after prior physical work drains. `DISABLED` remains an intentional setting; `NOT_INITIALIZED` is ordinary unused state, not a fault.

Application restart leaves old queue/leases untouched and dormant. Reading job history does not claim/recover/execute them. New explicit submissions authorize their own jobs only; previously pending work resumes only after explicit user selection/confirmation (proposed bounded `resumeJobIds` on recovery control, at most 1). Coordinator claim/recovery is gated by current-session authorized job IDs, not every historical queue row. Persisted cancel/completion and lease fences still govern reconciliation; readiness alone cannot replay an unknown paid outcome.

An unused manager has nothing to stop: app shutdown must not initialize it for cleanup. An activated manager cooperatively cleans up only resources it actually acquired, independently of monitor cleanup. No fixed idle-unload timer is required in this release; leaving the page stops polling, not a submitted durable job. Explicit backtest stop releases drained resources; reopening history may request read preparation again, but execution requires a new explicit operation/resume authorization.

| Fault / action | Monitor/Web effect | Backtest behavior and recovery |
|---|---|---|
| First-use key, permission, schema, database or factory/start failure | Website and already-started monitoring remain available | Scoped `DEGRADED`, repair guidance and retry after owned resources drain; no blind database deletion/migration. |
| Ordinary invalid input / job exception | None from exception propagation | Reject input or mark only the job `FAILED`; healthy service stays `READY`. |
| Coordinator/repository failure | No monitor stop/restart | Stop admission; reads/cancel may remain available if their store/control path is independently healthy. Recreate only after old tasks/executors drain. |
| Slow request or cooperative cancellation | Monitor continues subject to shared-resource load | Durable `CANCEL_REQUESTED`; check token at safe boundaries. Unconfirmed cancellation never appears as `CANCELLED`. |
| Hung/non-cooperative thread or shutdown timeout | Cannot guarantee resource/exit independence | Report `DEGRADED`/restart required; no unsafe thread kill, no duplicate executor or concurrent replacement. An explicit whole-application restart affects monitoring too. |
| Cancel/complete/lease race | None from business-state propagation | Current claim, revision and cancellation are revalidated in atomic completion; stale work cannot publish a completed partial report. |
| Backtest-only stop/recovery | Monitor lifecycle unchanged when cooperative cleanup succeeds | Stop new claims and request cooperative interruption; separate cleanup/error ownership. Existing completed results are retained. |
| Whole-application shutdown | Both stop deliberately | Begin monitor and backtest cleanup independently; record timeout honestly. Running executor threads may still prevent process exit. |
| Native crash, process memory exhaustion, host/disk failure | May affect both | Explicit remaining same-process risk accepted for this choice; threads do not contain process-level failure. |
| AI preparation/item failure | Existing activated monitoring continues while dependencies remain valid | Persist this source outcome; edits/retries bind its revision; unknown paid outcomes need explicit scoped recovery. |

Automatic recovery applies only to already explicitly activated work, never an unused service or failed first initialization. It handles classified transient coordinator/service failures after physical drain: at most 3 attempts with delays of 1, 5 and 15 seconds per incident; 5 minutes healthy resets the incident budget. Storage/configuration/unsupported input, non-cooperative work and unknown paid outcomes require explicit action. Keep 30-second job leases and 3 claim generations; service recovery never resets job attempts. Failed/cancelled jobs do not silently requeue. Frozen replay recovery starts from durable input, not a half-mutated in-memory account.

Safe boundaries should occur at most 1 second apart during local loops; provider waits have explicit transport deadlines. Cooperative shutdown has a proposed 5-second observation budget. Timeout is a diagnostic/escalation boundary, not a guarantee that a thread stopped. Avoid unbounded await on the Web event loop; capture backtest cleanup failure separately and still attempt monitor cleanup. Do not dispose stores while a late worker can access them.

Proposed service resources remain `GET /api/v1/backtest-service`, `POST /api/v1/backtest-service/recovery-requests` and `POST /api/v1/backtest-service/stop-requests`, with existing guards/error envelopes. Status uses lightweight lifecycle state even if backtest stores are unavailable. Controls bind a boot epoch and expected revision, caching at most 1,000 key receipts per epoch; after parent restart old epochs conflict and require status re-read. Accepted stop/recovery is not proof of completed cleanup.

Show service/job/item failures separately, available read/submit/cancel/export capabilities, safe reason, last progress and recovery action. Retain stale job views with timestamps, keep monitoring navigation usable and reduce degraded polling. Claim “monitoring continues” only when actual monitor health supports it. Service recovery does not create paid AI work, change the frozen cutoff or submit a new run. No new monitor-control API or reinterpretation of existing monitor health is included.

## ML17. Windows checks, finite work and accepted limits

Windows development and deployment use the same thread-based lifecycle. No `spawn`, Job Object, cgroup, child-process reaping or process CPU/memory hard cap is required by the selected design. Python threads share a process and cannot be reliably forcibly stopped; dedicated executors isolate work scheduling and ordinary exceptions, not native crashes or process memory exhaustion. [Python threading](https://docs.python.org/3/library/threading.html) and [executor shutdown](https://docs.python.org/3/library/concurrent.futures.html) establish this boundary.

Implemented application limits: permit one unfinished task across sync/verify/replay and preserve 256 KiB requests. The latest user instruction on 2026-10-07 supersedes earlier queue/preparation concurrency choices: until the task reaches a terminal state, reject new tasks and mutually exclusive preparation/sync/verify/replay operations. Cancellation-in-progress and expired leases retain the slot. Existing read-only status/history/results and live monitoring remain usable. Apply admission through existing transaction boundaries; add no queue, scheduler or generic lock framework. Preparation review/freeze remains a prerequisite. Preparation entries implement the same rule, recorded in MV20–MV30; implemented task admission/recovery evidence is MV18 and ADR 0009. On 2026-10-07 the user limited exports to compatibility: preserve existing supported-mode CSV/JSON contracts and bytes; add no loop-export support, bulk export, export jobs, scheduler or export participation in heavy-operation exclusion. Retain IP04 finite source/event/evaluation limits. Stream results instead of loading unlimited history. On 2026-10-07 the user cancelled disk-capacity and log budgets because deployment disk headroom is ample. Add no retained/transient byte cap, disk free-space admission threshold, log quota or new log rotation. Keep only the latest 30 materialized historical run records, ordered by publication/retention time descending with run_id as a deterministic tie-breaker; after publishing a new result, use existing bounded maintenance to delete the oldest excess runs and their summaries, fills and details. Pins do not exempt a run from this total cap. Protect queued/running jobs and shared datasets/snapshots still referenced by retained runs or jobs. ML-T21 implements this retention change and MV32 verifies it; it remains outside ML-T34 isolation prerequisites.

On 2026-10-07 the user adopted existing finite-work safeguards only: retain bounded queues/inputs/events, the single job slot, owned bounded threads, paging/batch reads and ordinary cooperative cancellation. Cancel new dynamic memory/CPU sampling controllers, pressure thresholds and pressure-triggered admission/cancellation; no generic resource-control module is required. Offline load verification may measure memory, queue wait and monitor delay to find actual bottlenecks, without adding a production pressure-control system. These existing safeguards cannot impose a per-thread CPU/memory ceiling or guarantee same-volume disk I/O isolation. The 1-second proposed service-control acknowledgement deadline must not block on heavy operation completion; long reads use bounded paging and explicit timeouts. Preserve existing export chunking/disconnect behavior and compatibility checks without new export development.

| Windows verification | Required evidence |
|---|---|
| Lazy activation | Assert zero backtest factory/store/key/executor/provider/queue access on startup/status/monitor navigation/prefetch/shutdown, then inject first-use damaged/locked/read-only stores and key/schema/factory errors; monitor remains serving. |
| Thread ownership | Concurrent first requests initialize once, cancelled waiters do not cancel shared work, metadata reads do not start execution; dedicated bounded executors have no duplicate lifecycle after retry/reload and partial failure reclaims resources. |
| Cancel/shutdown/recovery | Safe-boundary cancellation, lost replies, outstanding provider calls and coordinator errors; old work drains before replacement. A deliberately non-cooperative test uses a bounded controllable fixture and proves timeout/blocked replacement, not forced thread termination. |
| State and publication | Cancel/commit/lease races, repeated submissions, stale completion, rollback and result retention; no live account/notification mutation. |
| Storage/capability | Existing storage-domain guard regression and local sync pacing/cancellation; fake services only, no production DB or paid access. |
| Load regression | 10-stock monitoring with admitted preparation/replay/WAL load; compare schedule delay, Web response, queue wait, missing/duplicate semantic events and memory growth. Existing exports require compatibility regression only. |

Reference load host: at least 4 logical cores, 8 GiB RAM, local SSD and required free space. Record Windows/Python versions and hardware. Run 10 minutes of fake-provider monitoring baseline and 10 minutes with the admitted backtest load; collect at least 1,000 status requests per phase. Proposed gates: status p95 <= 250 ms, p99 <= 1 second, p95 increase <= 100 ms, monitor scheduling p99 added delay <= 250 ms, zero missed fake evaluations, duplicate/missing semantic reminders or unexplained monitor restarts. If gates fail, reduce admitted load or fix the measured bottleneck; do not claim thread isolation solves contention. These original gates are unchanged; MV43 records final executed measurements and corrections after failures, certifying only the measured paced fixture.

This choice deliberately accepts shared process/native-crash/memory/host failure and inability to force-stop stuck threads. A child process is an optional future scope change only if those accepted boundaries become insufficient. It is not a mandatory second implementation phase.


## ML18. Final delivery and review scope (2026-10-09)

All 37 active tasks and 13 checkpoints are complete; cancelled ML-T06/ML-T09 and ML-A07 retain their historical IDs. The 20 tasks requested in this run are individually verified, committed and pushed to GitHub. One-source explicit extraction, complete plan/opening-account review and freeze, one cutoff, the private complete loop, atomic settlement, native causal reports and latest-30 retention are delivered. ML02/ML14 gaps describe the planning-time baseline, not current blockers.

MV43 records actual Windows 600/600-second ten-stock monitoring/admitted replay acceptance, preserving four failed long measurements and narrow corrections. Offline experiment starts are at least 120 seconds apart, at most five per ten minutes; no production throttle or memory/CPU/disk controller is added, and unrestricted stress is not certified. Public fill identities and exact legacy retry remain stable; historical compatibility scanning only filters SQL candidates and reuses the decision within one transaction, without changing monitor rules. MV44 records final relevant backend/frontend/build/real Chrome checks; MV45 records operations and thread boundaries. MV46 and SPEC-unified-plan U09 record the concrete differences of both generated profiles, final approval and unchanged historical compatibility branches. ML-T29 adds only the 10 reviewed paths to the exact allowlist, preserving full path equality, snapshot and public-error assertions.

Only one unfinished task exists at a time; cancellation-pending and unknown work keep the exclusive slot, and accepted stop/repair is not physical drain. Status/history reads do not authorize backlog, and resume requires exactly one explicitly selected task. Native loop exports remain 409, with existing export byte contracts preserved. Shared-process, inability-to-force-stop and uncertified live AI/market-source boundaries remain. See [operations](../../operations/monitor-loop-backtest.md) and [executed verification](../../verification/monitor-loop-backtest.md).

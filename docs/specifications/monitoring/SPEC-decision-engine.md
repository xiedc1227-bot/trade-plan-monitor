# Spec: decision-engine (Deterministic Decision Engine)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-decision-engine.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Given one active plan, one immutable market snapshot, and one strategy-state snapshot, return an explainable decision and proposed state transitions without performing I/O. Identical input must always produce identical output for testing, replay, and audit.

The engine is the only authority for price zones, confirmations, blockers, position constraints, pressure reduction, and close risk. AI and the Vue frontend cannot duplicate these rules.

## Tech Stack

- Python 3.14.x (`>=3.14,<3.15`)
- Immutable dataclass/Pydantic value objects from `plan-domain`, `market-data`, and `strategy-state`
- Pure functions and pytest table-driven tests
- Integer-fen price comparisons

## Commands

```powershell
python -m pytest tests/unit/test_decision_engine.py -q
python -m pytest tests/replay/test_decision_replay.py -q
python -m ruff check src/trade_plan_monitor/decision tests/unit/test_decision_engine.py tests/replay
```

## Project Structure

```text
src/trade_plan_monitor/decision/
├── models.py       # Evaluation context, result, evidence, and transition intents
├── conditions.py   # Typed condition evaluators
├── episodes.py     # Low-zone episode state transitions
├── risk.py         # Official-close risk transitions
└── engine.py       # Priority and evaluate entry point
tests/unit/
└── test_decision_engine.py
tests/replay/
└── test_decision_replay.py
```

## Frozen replay scope

The singular result, episode, CORE/TACTICAL, low-zone and official-close rules below describe frozen `LEGACY_LOW_BUY` research/compatibility behavior. The consolidated [frozen plan reference](SPEC-plan-domain.md) preserves Schema 1–3 model and exact explicit-rule arithmetic/result identities; Schema 4 readers preserve their original stored meaning. Existing result hashes and backtest inputs follow [ADR 0005](../../decisions/0005-version-explicit-plan-rules.md).

Current Schema 5 conditions, confirmations, reminder-only rules and isolated simulation follow [One Trade Plan Workflow](SPEC-unified-plan.md). Old strategy requirements cannot become defaults or extra blockers for a current plan. No frozen format may activate or simulate through current services.

## Public Contract

```python
def evaluate(context: EvaluationContext) -> EvaluationResult:
    """Pure evaluation: no database, network, system clock, logging, or randomness."""
```

`EvaluationContext` explicitly contains evaluation time, active plan and hash, complete bars, indicators and formula version, actual daily limits, data health, positions, current low-zone/risk state, and trading-calendar facts.

An `INTRADAY` target supplies `current_day_minutes` as an immutable tuple containing the exact normalized complete `MinuteBar` sequence from the first canonical minute end of the target trading date through `target.bucket_end`, inclusive, with at most 240 values. The sequence is strictly increasing, belongs to one symbol and date, and is complete under the trading calendar and canonical lunch break. Any context claiming complete intraday data must include a matching open target-date `TradingDay`; a missing or closed target row cannot certify the slice. "Minute price," "current price," and "latest valid price" mean the `close_fen` of its last bar; no partial minute, system-clock value, `DailyBar.close_fen`, or separately queried quote is eligible. Missing, duplicate, noncanonical, stale, future, mixed-symbol, or wrong-target required minute evidence fails closed. Structural 5-minute conditions continue to consume complete `FiveMinuteBar` values.

The evaluation identity names the requested target; it does not manufacture market evidence. An intraday blocked result may therefore have both `market_data_at` and `price_fen` absent. When they are present, they identify the actual latest certified complete minute at or before `target.bucket_end`; a fresh complete target uses exactly `target.bucket_end`. An official-close result uses only the certified reconciled official close at the canonical 15:00 cutoff, or leaves both fields absent.

`ta-v1` price-valued indicator fields are finite float yuan; `rsi14` is dimensionless on 0–100. The context must preserve explicit `None` values for insufficient windows, and any required missing indicator blocks evaluation rather than being inferred or replaced.

Every current-date daily indicator input carries explicit `PROVISIONAL` or `OFFICIAL` provenance and an exact `source_as_of`. For an `INTRADAY` target, entry-momentum and reclaim evidence use official prior-date daily bars plus exactly one deterministic current-date provisional daily aggregate through `target.bucket_end`, with `source_as_of == target.bucket_end`. The aggregate through 15:00 remains provisional. For an `OFFICIAL_CLOSE` target, continued-deterioration evidence uses the reconciled `official_bar` only when `advance_close_risk=True`, with `OFFICIAL` provenance and a canonical 15:00 source cutoff. Symbol, trading date, formula version, provenance, source cutoff, and reconciliation source must agree. Missing, mixed, stale, or mismatched provenance fails closed. Evidence records provenance and source cutoff; provisional evidence never advances official-close risk or official deterioration.

`EvaluationResult` contains:

- one authoritative `SymbolDecisionSnapshot`;
- zero or more `StateTransitionIntent` values;
- zero or one actionable `SignalIntent`;
- satisfied evidence, unmet evidence, blockers, and numeric facts, using a bounded union of DSL `ConditionEvidence` and non-DSL `RuleEvidence`;
- next observation or action;
- evaluation identity and deterministic result hash.

`RuleEvidence` preserves a stable code, non-satisfied or satisfied outcome, up to 16 ordered typed facts, and up to 4 explicit missing-input codes without inventing a condition-DSL tag. T024 maps the five T022 structural records plus `PLAN_INACTIVE`, `PRESSURE_TOUCH`, `RISK_RECOVERY`, and `RISK_DETERIORATION` into this shared result evidence without recomputing their facts.

The runtime applies transition intents and enqueues the alert intent in one transaction.

T038 diagnostic evaluation is a read-only application-service use of this same public `evaluate(context)` contract. Its request names exactly one canonical intraday five-minute target or one official-close trade date and an expected source revision. The application-service response retains the unchanged canonical `EvaluationResult`; the HTTP adapter revalidates its self-authenticating `resultHash` and embedded evaluation identity before projecting the authoritative decision. The embedded `planHash`, symbol, kind, typed target, and `formulaVersion` must match both that result and the request, with no transition-intent application, evaluation-ledger claim, alert enqueue, position change, clock read, or provider call. The adapter cannot alter priority, recompute a result hash, or construct a second decision. An explicitly reported diagnostic audit is the sole optional write.

## Evaluation Priority

1. Return `BLOCKED_DATA` for target-global unusable data.
2. Evaluate applicable official-close risk transitions.
3. Evaluate applicable tactical-position pressure reduction.
4. Apply entry-only blockers, with `BLOCKED_DATA` before `BLOCKED_RISK`.
5. Evaluate low-zone core/tactical entry signals.
6. Return `LOW_ZONE_WATCH` or neutral/out-of-zone `WAIT`.

Applicability is target-specific: `INTRADAY` evaluates pressure and low-zone orchestration, while `OFFICIAL_CLOSE` evaluates official risk and retains the supplied episode state. A non-applicable evaluator contributes no artificial missing-input blocker. Entry-only blockers never suppress exposure-reducing pressure or official-risk actions.

`DATA_NOT_READY`, `DAILY_LIMIT_UNKNOWN`, `EPISODE_HISTORY_GAP`, and candidate-applicable DSL `MISSING_INPUT` evidence map to `BLOCKED_DATA`. `BEARISH_VOLUME_EXPANSION`, `RISK_PENDING`, and known failed buy-safety or position-availability evidence map to `BLOCKED_RISK`. Logical DSL roots retain their validated three-valued semantics: a `SATISFIED` `ANY` is not blocked by a missing alternative. If an active non-satisfied buy-safety blocker tree contains both a known failure and a nested missing input, data precedence applies and the missing input is retained in `next_step`. An inactive plan returns `WAIT`, creates no transition or signal intent, retains `PLAN_INACTIVE` evidence, and uses `REVIEW_BLOCKER` as its next step.

A higher-priority result suppresses a lower-priority signal while retaining all lower-priority evidence for display. If pressure reduction suppresses a simultaneously ready buy, the returned episode transition preserves the derived low and cursor as `ACTIVE` with no alerted signal; it must not consume the buy as `ALERTED`. A later target bucket may evaluate the active episode again.

## Signal Types

- `WAIT`
- `LOW_ZONE_WATCH`
- `BLOCKED_DATA`
- `BLOCKED_RISK`
- `BUY_CORE_READY`
- `BUY_TACTICAL_READY`
- `PRESSURE_REDUCE_READY`
- `RISK_BREACH`
- `RISK_RECOVERED`
- `RISK_EXIT_READY`
- `RISK_EXIT_PENDING_SETTLEMENT`

By default only `BUY_*_READY`, `PRESSURE_REDUCE_READY`, `RISK_BREACH`, and `RISK_EXIT_*` create textual alerts. Ordinary `WAIT` and watch progress update the UI only.

## Huaya Intelligent Plan Rules

### Price Zones

- Low-buy zone: `[63.00, 64.50]`.
- Observation zone: `(64.50, 68.80)`.
- Pressure zone: `[68.80, 70.20]`.
- Risk line: official close below `60.80`.
- 64.50 belongs only to the low-buy zone; 68.80 belongs only to the pressure zone.

A zone touch is observed only when a normalized complete minute close satisfies the zone inclusion flags. The first matching `MinuteBar.bar_end` is `touch_at`; an intraminute high/low alone, a jump across the whole zone without a minute close inside it, and an incomplete minute do not count.

### Low-Zone Episode

1. Create an episode when the minute price first touches the low zone; the touch itself does not alert.
2. `episode_low` is the lowest price after the episode begins.
3. A later complete bar whose low is at least one tick lower resets confirmation progress.
4. Require at least two complete 5-minute bars without a new low after the latest low, with the latter close no lower than the former.
5. Latest volume is no greater than the previous bar and no greater than 1.5 times the median of the prior 20 bars.
6. Provisional daily MACD histogram improves by at least 0.02, or the latest valid price reclaims daily EMA10.
7. All blockers are clear.
8. With no core position, emit one 100-share `BUY_CORE_READY`. With a core position and a later independent episode, emit one 100-share `BUY_TACTICAL_READY`. Total position cannot exceed 200 shares.
9. Close an unalerted episode after two complete 5-minute bars outside the low zone. An alerted episode remains deduplicated; a new alert requires exit and re-entry into a new episode.

Every episode snapshot carries a required `last_processed_bucket_end`, represented as a canonical complete 5-minute boundary in `Asia/Shanghai`. The touch bucket initializes the cursor and establishes `episode_low` from the touch close plus only post-touch minutes in that bucket; it does not count as a confirmation bar. An existing `ACTIVE` or `ALERTED` episode consumes exactly the continuous bars in `(last_processed_bucket_end, target.bucket_end]` in order. A strictly lower integer-fen low resets progress, an equal low advances progress once, and every successfully consumed target advances the cursor even when progress is saturated or the episode is already alerted. `target.bucket_end == last_processed_bucket_end` is a complete no-op: facts that arrive later cannot create a transition or signal for an already consumed bucket. If a later target first discovers an earlier touch, the same evaluation catches up through that target. Missing cursor anchors, missing intermediate bars, or unprovable cross-trading-day adjacency fail closed without advancing the cursor.

For a closed episode, `last_processed_bucket_end` is exactly the second consecutive outside-zone bar that closes it. Re-entry searches minute closes strictly after that closure cursor and creates a distinct deterministic episode identity. Recovery may therefore close the old episode at its closure boundary and process a later re-entry as a new episode without replaying already consumed bars.

`PRICE_RECLAIMS_INDICATOR` is a crossing event, not an above-level state. Select the exact five normalized complete minutes of the current evaluation bucket from `current_day_minutes` and compare every adjacent pair with the same selected current-date daily indicator value. The condition is satisfied if and only if at least one pair has `previous_close_fen / 100 < indicator_yuan <= current_close_fen / 100` and the bucket-ending minute still has `bucket_end_close_fen / 100 >= indicator_yuan`. Equality at the crossing or bucket-ending current price satisfies; equality at the previous price does not. Missing any bucket minute or indicator is missing input; complete evidence with no in-bucket crossing, or with the bucket-ending price below the indicator, is unsatisfied. Entering the bucket already above the indicator is not a reclaim.

Finite decimal facts and outcome comparisons are independent of the ambient Decimal context. Integer fen-to-yuan conversion is an exact two-place coefficient shift; an even integer-volume median preserves its exact half-share value; finite threshold multiplication and subtraction remain exact. Only genuinely non-terminating displayed ratio evidence uses the canonical 50-significant-digit, half-even context, while the corresponding outcome uses exact coefficient multiplication and direct Decimal comparison without expanding integer ratios.

### Buy Blockers

- Required market data is stale or incomplete;
- trading calendar or actual daily price limits are unknown;
- a bearish 5-minute bar exceeds the configured median-volume multiple;
- current price is too close to the actual limit-down price;
- price is walking the Bollinger lower band;
- manual event-risk flag;
- risk-line breach awaiting confirmation;
- indicators are invalid or missing;
- maximum position has been reached.

T022 returns bounded structural blocker records alongside DSL evidence so later result assembly can preserve the reason for suppression. The stable codes are `DATA_NOT_READY`, `DAILY_LIMIT_UNKNOWN`, `EPISODE_HISTORY_GAP`, `BEARISH_VOLUME_EXPANSION`, and `RISK_PENDING`; each record has a non-satisfied outcome, explicit numeric/state facts, and required missing-input codes when the outcome is `MISSING_INPUT`. `BEARISH_VOLUME_EXPANSION` applies only when the latest complete 5-minute bar closes below its open and its share volume strictly exceeds a `VOLUME_TO_MEDIAN_LTE` threshold on an explicitly conjunctive `ALL` entry path; a threshold under any `ANY` alternative is not a global blocker. Equality and bullish bars do not activate this structural blocker. The Huaya sample blocker tree remains the ordered `ALL` of `MANUAL_EVENT_RISK_CLEAR`, `DISTANCE_FROM_LIMIT_DOWN_GTE(minimum_ratio=0.01)`, and `LOWER_BAND_HITS_LTE(max_hits=2, window_bars=4)`. T024 owns mapping these records into final `BLOCKED_DATA`/`BLOCKED_RISK` result priority and does not change T022 episode progression.

### R07 Manual Event-Risk Confirmation

`MANUAL_EVENT_RISK_CLEAR` is backed by a durable, audited confirmation scoped to one symbol, the active immutable plan-content hash, and an inclusive expiry trading date. Its authoritative input is exactly three-state: an explicit `CLEAR` projects `False`, an explicit `RISK_PRESENT` projects `True`, and a missing, plan-changed, expired, or post-cutoff confirmation projects `None`. `None` must remain unknown and fail closed; it must never be defaulted or coerced to `False`.

The production context reads that record in the same SQLite unit of work as the plan and risk facts before constructing `EvaluationContext`. An exact plan-hash change, expiry or post-cutoff confirmation makes the input unknown; a restart with the same hash and still-valid scope retains the persisted confirmation. R07's hash includes the plan version and is not R08's new semantic `contentHash`. Each accepted confirmation records its revision, confirmation time, expiry date, state, plan hash, and audit action; optimistic revision and idempotency make a retried semantic command return its prior receipt without creating another audit event. The record is not an official-close risk acknowledgement and cannot weaken that separate fail-closed state.

`LOWER_BAND_HITS_LTE` selects the latest `window_bars` adjacent complete 5-minute bars ending at the evaluation target. Every bar must have exactly one `ta-v1` 5-minute `IndicatorPoint` with the same `(symbol, bar_end, formula_version)`. A hit is `bar.close_fen / 100 <= point.boll_lower_yuan`; equality is a hit. Reusing one band, using a daily band, forward filling, or aligning by position without matching identities is forbidden. Missing, duplicate, misaligned, or `None` band evidence blocks evaluation; otherwise the condition is satisfied if and only if `hit_count <= max_hits`.

`RETREAT_FROM_SESSION_HIGH_GTE` requires the certified gapless current-day minute slice. It uses the maximum high from all complete current-day bars and minutes through the target, and satisfies exactly when `(session_high_fen - latest_close_fen) / session_high_fen >= minimum_ratio`; missing current-day history returns `SESSION_BARS`. Any rolling 5-minute window that crosses trade dates must prove adjacency from the supplied bounded trading-calendar history. A missing current-date calendar row returns `TRADING_CALENDAR`; a known calendar mismatch remains an incomplete bar window.

### Pressure Reduction

Price must touch the pressure zone, `SELLABLE_QUANTITY_GTE(bucket=TACTICAL, quantity=100)` must be satisfied, and at least one of the following four rejection patterns must hold. Those four alternatives are the complete operational definition of failure to hold above the pressure reference; no additional common pressure-close condition is required:

- upper wick is at least 40% of the bar range;
- retreat from session high is at least 1%;
- `VOLUME_TO_MEDIAN_GTE(minimum_ratio=1.5, window_bars=20)` is satisfied and the close is in the lower half of the bar;
- two consecutive complete bars close below the pressure reference after the touch.

Pressure orchestration derives `pressure_touch_at` from `current_day_minutes`. For the `CONSECUTIVE_CLOSES_BELOW_LEVEL` alternative, T023 selects only adjacent complete 5-minute bars with `bar_end > pressure_touch_at`; equality is not after. A bar containing an earlier-minute touch may count, but an equal-end, pre-touch, prior-day, incomplete, or non-adjacent bar cannot. Counted closes are strictly below the reference; equality does not satisfy this alternative. The other three alternatives may use the complete bar containing the touch. `CONSECUTIVE_CLOSES_BELOW_LEVEL` remains a generic leaf; touch filtering is T023 orchestration, not hidden T021 leaf behavior.

With no position or only a core position, display pressure evidence without creating a reduction alert.

### Official-Close Risk

- An inactive plan never creates, clears, or advances risk state.
- An intraday price or provisional close below 60.80 does not advance risk state.
- The first reconciled official close below 60.80 on a certified open target day emits `RISK_BREACH`, blocks additions, and records the original breach trading date and close.
- A reconciled official close at or above 60.80 on any later certified open trading date emits `RISK_RECOVERED` and clears the state. A newly created `EXIT_PENDING_SETTLEMENT` state is not resolved again on its own transition date.
- If a later official close remains below 60.80, risk exit also requires continued deterioration against the original breach-day baseline: close no higher than the original breach close, and volume not lower than the original breach volume or daily MACD histogram not improving from the original breach-day value. Missing, inconsistent, or non-breaching baseline evidence fails closed.
- Exit selects the newest remaining tactical lot first, otherwise the newest remaining core lot; newest means acquisition date descending with `lot_id` ascending as the same-date tie-breaker. A lot is eligible when at least the plan lot size remains.
- If that preferred lot is T+1-restricted, emit `RISK_EXIT_PENDING_SETTLEMENT` and do not substitute an older or core lot. Re-evaluate the same deterministic preference on later certified open days; once the preferred target is sellable, emit `RISK_EXIT_READY` without adding a new risk status.

## Idempotency Identity

- Intraday evaluation: `(plan_hash, symbol, completed_5m_bucket_end, formula_version)`.
- Close evaluation: `(plan_hash, symbol, official_trade_date, formula_version)`.
- Alert: `(plan_hash, trading_date, signal_type, episode_or_risk_transition_id, quantity)`.

Duplicate data, recovery data, or restart may enrich evidence but cannot create a second identical action.

The pure result keeps `INTRADAY` and `OFFICIAL_CLOSE` as explicit discriminated identity kinds, so an intraday 15:00 target is not the same identity as that date's official close. T024 does not alter persistence. Before T032 may claim both identity kinds, the evaluation ledger requires a separately approved lossless persistent kind discriminator; overloading the intraday 15:00 timestamp is forbidden.

## Canonical Result Hash

The result-hash preimage is the ASCII domain `decision-result-v1`, one NUL byte, and compact canonical JSON for every `EvaluationResult` field except `result_hash`. Object keys are lexicographically sorted, array order is preserved, JSON uses no insignificant whitespace, and the complete preimage is UTF-8. Enums use their values, while dates and `Asia/Shanghai` timestamps use canonical ISO forms. A finite Decimal is `0` for either signed zero or otherwise uses `<optional-minus><coefficient>e<base-10-exponent>` after removing coefficient trailing zeros; scale, ambient Decimal context, and signed zero therefore cannot change the hash. The effective coefficient is limited to 10,000 digits, and non-finite numbers are rejected. The stored value is the full lowercase SHA-256 hexadecimal digest.

Construction and validated copy updates recompute or verify this digest so a result cannot retain a stale hash after any semantic field changes. Canonical full-result serialization includes `result_hash` and uses the same JSON rules without the hash-domain prefix. Every field other than `result_hash`, including `evaluated_at`, transitions, evidence order, next step, and identity kind, participates in the digest.

Pressure and risk use separate SHA-256 cause domains. A pressure cause is derived from `plan_hash`, `symbol`, and the first certified `pressure_touch_at`; a risk cause is derived from `plan_hash`, `symbol`, and the original `breach_trade_date`. Replays preserve the same cause, and `RISK_EXIT_PENDING_SETTLEMENT` → `RISK_EXIT_READY` retains the original risk cause.

## Code Style

```python
def evaluate_condition(
    condition: Condition,
    context: EvaluationContext,
) -> ConditionEvidence:
    evaluator = CONDITION_EVALUATORS[type(condition)]
    return evaluator(condition, context)
```

Each DSL condition uses an independent evaluator that returns evidence and does not mutate state. Avoid a giant nested conditional.

## Testing Strategy

- Cover every signal, blocker, price boundary, and priority conflict.
- Verify a low-zone touch does not alert and a new low resets progress.
- Verify durable cursor catch-up, equal-low one-time advancement, same-target no-op, gap/calendar failure closure, saturated and alerted cursor advancement, exact closure cursor, and strict post-closure re-entry.
- Verify every structural blocker code, outcome, missing input, and numeric/state fact, including bearish-volume equality and one-share boundaries.
- Cover 64.50, 68.80, and one-fen boundary changes.
- Cover core-first entry, maximum position, T+1, and no reduction with core-only positions.
- Cover first breach, recovery, no deterioration, deteriorating exit, delayed official daily data, and restricted lots.
- Cover exact or missing `current_day_minutes`, minute-close price facts, every in-bucket reclaim crossing position plus bucket-end hold or loss, time-aligned lower-band equality, indicator provenance, and generic strict-below consecutive-close evidence.
- In T023, cover pressure-touch derivation, pre-touch/equal-time/post-touch bar eligibility, touch-containing bars, all four failure-to-hold alternatives, and no inferred fifth predicate.
- Cover a satisfied `ANY` with a missing alternative and a non-satisfied buy-safety tree containing simultaneous known-risk and missing-data evidence.
- Re-run identical contexts and compare result hashes.
- Cover the canonical Decimal scale/sign/context boundary, the 10,000/10,001 effective-coefficient boundary, stale-hash rejection, and evidence-order sensitivity.
- Replay valid entry, continuous decline, stale data, duplicate/recovered data, same-target restart, and independent episodes.

## Boundaries

- Always: provide time, calendar, and market facts explicitly in the context.
- Always: return complete evidence and next step with every result.
- Ask first: add a signal, change priority, or change Huaya Intelligent thresholds.
- Never: access the database, call Tushare/AI, render text, send notifications, or read system time.
- Never: mutate input state or infer a fill.
- Never: interpret ambiguous source-plan prose at runtime.

## Success Criteria

- Identical input produces byte-stable canonical output and hash.
- One valid low-zone episode creates at most one buy intent.
- Every action is explainable from stored numeric evidence.
- Missing, stale, or incomplete market/reference data fails closed per symbol.
- Risk and T+1 behavior matches the plan and trading calendar.
- State for 10 symbols is fully isolated.

## Open Questions

None blocking. Thresholds are plan-version data; changing them creates a new version.

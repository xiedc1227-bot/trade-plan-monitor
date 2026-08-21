# Spec: decision-engine (Deterministic Decision Engine)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-decision-engine.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Given one active plan, one immutable market snapshot, and one strategy-state snapshot, return an explainable decision and proposed state transitions without performing I/O. Identical input must always produce identical output for testing, replay, and audit.

The engine is the only authority for price zones, confirmations, blockers, position constraints, pressure reduction, and close risk. AI and the Vue frontend cannot duplicate these rules.

## Tech Stack

- Python 3.11+
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

## Public Contract

```python
def evaluate(context: EvaluationContext) -> EvaluationResult:
    """Pure evaluation: no database, network, system clock, logging, or randomness."""
```

`EvaluationContext` explicitly contains evaluation time, active plan and hash, complete bars, indicators and formula version, actual daily limits, data health, positions, current low-zone/risk state, and trading-calendar facts.

`EvaluationResult` contains:

- one authoritative `SymbolDecisionSnapshot`;
- zero or more `StateTransitionIntent` values;
- zero or one actionable `SignalIntent`;
- satisfied conditions, unmet conditions, blockers, and numeric evidence;
- next observation or action;
- evaluation identity and deterministic result hash.

The runtime applies transition intents and enqueues the alert intent in one transaction.

## Evaluation Priority

1. Validate plan activation, calendar/session, complete bars, indicator version, reference data, and freshness.
2. Apply immediate fail-closed blockers.
3. Evaluate official-close risk transitions.
4. Evaluate tactical-position pressure reduction.
5. Evaluate low-zone core/tactical entry episodes.
6. Return neutral or out-of-zone observation state.

A higher-priority result suppresses a lower-priority signal while retaining lower-priority evidence for display.

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

### Pressure Reduction

Price must touch the pressure zone, fail to hold above the pressure reference, at least 100 tactical shares must be sellable, and one pattern must hold:

- upper wick is at least 40% of the bar range;
- retreat from session high is at least 1%;
- volume is at least 1.5 times the rolling median and the close is in the lower half of the bar;
- two consecutive complete bars close below the pressure reference after the touch.

With no position or only a core position, display pressure evidence without creating a reduction alert.

### Official-Close Risk

- An intraday price or provisional close below 60.80 does not advance risk state.
- The first official close below 60.80 emits `RISK_BREACH`, blocks additions, and records the breach trading date.
- An official close at or above 60.80 on the next trading day emits `RISK_RECOVERED` and clears the state.
- If still below 60.80, risk exit also requires continued deterioration: close no higher than the breach-day close, and volume not lower or daily MACD histogram not improving.
- Exit targets the newest sellable 100 shares, tactical before core. If the target lot is T+1-restricted, emit `RISK_EXIT_PENDING_SETTLEMENT`.

## Idempotency Identity

- Intraday evaluation: `(plan_hash, symbol, completed_5m_bucket_end, formula_version)`.
- Close evaluation: `(plan_hash, symbol, official_trade_date, formula_version)`.
- Alert: `(plan_hash, trading_date, signal_type, episode_or_risk_transition_id, quantity)`.

Duplicate data, recovery data, or restart may enrich evidence but cannot create a second identical action.

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
- Cover 64.50, 68.80, and one-fen boundary changes.
- Cover core-first entry, maximum position, T+1, and no reduction with core-only positions.
- Cover first breach, recovery, no deterioration, deteriorating exit, delayed official daily data, and restricted lots.
- Re-run identical contexts and compare result hashes.
- Replay valid entry, continuous decline, stale data, duplicate/recovered data, restart, and independent episodes.

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

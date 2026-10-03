# Frozen Plan Domain and Replay Compatibility

> Frozen Schema 1–4 compatibility reference. New live extraction, review, activation and simulation use [One Trade Plan Workflow](SPEC-unified-plan.md), Schema 5 and `plan-extract-v8`. The model/rule meanings below apply only to historical readers and isolated research replay; they do not expose old live commands or authorize activation. Existing bytes, hashes, review evidence and research identities must remain unchanged.

## Public Contract

### Versioned Plan

```python
class TradePlan(BaseModel):
    schema_version: Literal[1]
    plan_id: str
    version: int
    symbol: str
    name: str
    market: Literal["SSE", "SZSE", "BSE"]
    metadata: PlanMetadata
    activation: ActivationPolicy
    position: PositionPolicy
    levels: PriceLevels
    entry: EntryPolicy
    reduction: ReductionPolicy
    risk: RiskPolicy
    blockers: BlockerPolicy
    monitoring: MonitoringPolicy
```

Activation policy is a discriminated union:

- `MANUAL`: remains active until explicitly disabled by the user.
- `TRADING_DAY`: active only on one specified trading day.
- `DATE_RANGE`: active between start and end dates according to the trading calendar.

`activation_is_eligible_on` is the canonical date policy for both replay and production.
It evaluates the market date carried by the evaluation target, not the later wall-clock
time at which delayed work or restart recovery happens. `TRADING_DAY` equality and both
`DATE_RANGE` endpoints are inclusive; `MANUAL` remains eligible until explicit disablement.

At most one version is active per symbol. Editing an active version creates a new draft, and activating the new version atomically deactivates the previous one.

### Allowlisted Condition DSL

Monitoring conditions are typed data, never expression strings. Schema v1 supports:

- `PRICE_IN_ZONE`
- `NO_NEW_LOW_FOR_BARS`
- `NON_DECREASING_CLOSE`
- `VOLUME_TO_PREVIOUS_LTE`
- `VOLUME_TO_MEDIAN_LTE`
- `VOLUME_TO_MEDIAN_GTE`
- `MACD_HIST_IMPROVEMENT_GTE`
- `PRICE_RECLAIMS_INDICATOR`
- `UPPER_WICK_RATIO_GTE`
- `RETREAT_FROM_SESSION_HIGH_GTE`
- `CLOSE_IN_BAR_LOWER_HALF`
- `CONSECUTIVE_CLOSES_BELOW_LEVEL`
- `OFFICIAL_CLOSE_BELOW_LEVEL`
- `NEXT_TRADING_DAY_RECOVERY`
- `POSITION_BUCKET_AVAILABLE`
- `SELLABLE_QUANTITY_GTE`
- `MANUAL_EVENT_RISK_CLEAR`
- `DISTANCE_FROM_LIMIT_DOWN_GTE`
- `LOWER_BAND_HITS_LTE`

Each condition has its own Pydantic model and bounded parameters. Logical composition allows only `ALL` and `ANY`, with maximum depth 4 and at most 50 leaf conditions per plan.

`VOLUME_TO_MEDIAN_LTE` uses `max_ratio`; `VOLUME_TO_MEDIAN_GTE` uses `minimum_ratio`. Both compare the latest completed-bar volume with the median of the specified number of preceding completed bars. `SELLABLE_QUANTITY_GTE` requires both an explicit `bucket` (`CORE` or `TACTICAL`) and a board-lot `quantity`, so one bucket can never satisfy another bucket's sellability rule.

`PRICE_IN_ZONE` uses the latest valid normalized complete minute close. `PRICE_RECLAIMS_INDICATOR` scans every adjacent pair in the exact current 5-minute bucket against one selected current-date indicator value, requires `previous_price < indicator <= current_price` for at least one pair, and also requires the bucket-ending price to remain at or above the indicator; entering the bucket already above is not a reclaim. `LOWER_BAND_HITS_LTE` compares each selected complete 5-minute close with the `ta-v1` 5-minute lower-band point of the same identity and counts equality as a hit. `CONSECUTIVE_CLOSES_BELOW_LEVEL` itself requires the configured number of adjacent complete closes to be strictly below the named level. Pressure-specific after-touch eligibility is imposed later by T023 orchestration and is not a hidden leaf parameter.

The four configured pressure rejection alternatives together are the complete definition of failure to hold; Schema v1 adds no fifth pressure condition.

Unknown conditions, arbitrary formulas, scripts, SQL, field paths, dynamic imports, and external calls are invalid input.

### Validation Rules

Validation covers:

- A-share symbol format and exchange consistency;
- valid tick size, price precision, and board-lot quantities;
- `0 < core_target_qty + tactical_target_qty <= max_qty`;
- non-overlapping actionable price zones with explicit boundary inclusion;
- risk line and pressure reference values within reasonable configured bounds;
- positive, bounded windows, ratios, timeouts, and bar counts;
- supported indicator formula versions and timeframes only;
- complete activation date fields;
- all market evidence required by each condition is available from `market-data`;
- no unresolved material AI warning or unmapped source text at activation.

Every validation result contains `code`, `path`, `severity`, `message`, and `activationBlocking`. Errors prevent saving. Ordinary warnings allow draft saving, while activation-blocking warnings must be resolved first.

## E02. Plan variants and finite vocabulary

| Contract | Stored discriminator | Execution meaning |
|---|---|---|
| Existing plans | `schema_version=1` or `2`; original bytes unchanged | Derived display mode `LEGACY_LOW_BUY`; current repaired implementation identified as `legacy-low-buy-r06`. Preserve low-zone episodes, CORE/TACTICAL, pressure rejection and official-close risk. Schema v2 keeps its existing index contract. |
| New explicit plans | `schema_version=3`, `execution_mode=EXPLICIT_RULES`, `execution_version=explicit-rules-v1` | Independent reviewed rules evaluated on completed five-minute closes. No episode, core-first, tactical-only, pressure-touch, MACD, median cap, Bollinger, distance threshold, or official-risk latch is inherited. |

Schema v3 has the existing `plan_id`, `version`, `symbol`, `name`, `market`, `metadata` and `activation` fields, plus `position`, `monitoring`, `rules`, and `conflict_policy` below. It forbids legacy `levels`, `entry`, `reduction`, `risk`, `blockers`, and `reference_market` fields. This first explicit mode does not support index conditions; shared informational index displays may continue but never become required inputs. Switching modes requires a new reviewed plan version, never an in-place migration or field inference.

| Field | Exact v3 contract |
|---|---|
| `position` | `{inventory_scope: ALL_REGISTERED, lot_size: 100, max_qty: positive integer multiple of 100}`; no target or actual holding field |
| `monitoring` | `{timeframe_minutes: 5, indicator_formula_version: ta-v1}`; `ta-v1` retains normalization identity, but does not imply any indicator condition |
| `rules` | 1–3 rules, unique bounded `rule_id` using the existing `PlanId` syntax; at most one rule for each of BUY, SELL, RISK_ALERT |
| Rule fields | `rule_id`, `condition`, `action`, `confirmation`, `repeat_policy`, `safety_conditions` |
| `confirmation` | `{kind: COMPLETED_BAR_CLOSE, timeframe_minutes: 5}`; no pre-close or daily-close substitution |
| `safety_conditions` | Explicit optional condition tree, or explicitly reviewed `null` meaning no extra strategy blocker; applies only to this rule |
| `conflict_policy` | `{trade_conflict: BLOCK_BOTH, risk_conflict: RISK_ONLY | RISK_WITH_SELL_BLOCK_BUY}`; both fields require review |

Condition trees allow only `ALL` and `ANY` plus the leaves below. Reuse maximum depth 4 and 50 total leaves across all rule and safety trees, with nonempty logical nodes, no cycles and no extra fields. Array order is preserved for evidence and hashing; it is not temporal ordering or trade priority. `MANUAL_EVENT_RISK_CLEAR` is allowed only in an explicitly declared rule safety tree. There is no automatic manual-risk requirement for the synthetic plan.

| Leaf | Required parameters | Meaning |
|---|---|---|
| `COMPLETED_CLOSE_IN_RANGE` | `low_fen`, `high_fen` positive integers, `include_low`, `include_high` strict booleans | Current completed five-minute close lies in the specified interval. Reuse `PriceZone` comparisons; reject an inverted or tick-empty interval. Flags must be supplied, not defaulted in a draft. |
| `VOLUME_TO_MEAN_GTE` | `window_bars` integer 1–500; `minimum_ratio` canonical finite decimal string in `(0,10]`; `history_scope=CONTIGUOUS_TRADING_BARS` | Current completed five-minute volume is at least the ratio times the arithmetic mean of exactly the preceding completed bars, excluding current. |
| `COMPLETED_CLOSE_BELOW` | `price_fen` positive integer | Current completed five-minute close is strictly below the threshold. |
| `MANUAL_EVENT_RISK_CLEAR` | No new parameter | Reuse R07 explicit clear / risk-present / unknown input, scoped as E08 specifies. |

Fixed literals, bounds and first-release limits are implementation constraints, not claimed source trading instructions. Additional indicators, arbitrary formula strings, `NOT`, cross-rule references, trailing stops, daily-reset variants, batches, and sequencing are unsupported in this mode. Do not force an unsupported request into the closest leaf. Preserve its source span, report `UNSUPPORTED_SEMANTICS`, and block activation of the whole affected plan until a user explicitly supplies a supported replacement. Acknowledging an unsupported warning alone is not resolution.

## E03. Exact completed-bar and arithmetic semantics

At target `t`, require one certified complete five-minute bar ending at `t`; its five normalized minute inputs and close must agree with the existing target/cutoff contract. Partial bars, high/low touches without the required close, a newer quote, future data or provisional daily close cannot satisfy a rule. Reuse existing freshness and valid-market-target safeguards, including the current 90-second live freshness bound; do not introduce a new trading threshold.

For `window_bars=N`, select the exact ordered adjacent trading bars `b[t-N]...b[t-1]`. Lunch and non-trading dates are skipped only through the existing canonical session/calendar adjacency proof. Prior trading dates are eligible under `CONTIGUOUS_TRADING_BARS`; never skip a missing scheduled bar, forward-fill, substitute zero, or shorten the window. This cross-session meaning must be shown in review; the original plan does not expressly select a same-day reset. A requested same-day-reset interpretation is unsupported in v1 and remains unmapped. Insufficient stored/certified history is `MISSING_INPUT`, even if a provider request might later recover it.

Let `S=sum(prior.volume_shares)` and `V=current.volume_shares`. Compare `V*N >= minimum_ratio*S` with exact integer/Decimal coefficient arithmetic, independent of ambient Decimal precision. Display `S/N` as mean volume; a rounded display ratio is never the comparison input. For the acceptance values `[100,100,100,100,600]`, `S=1000`, `N=5`, mean `200`, median `100`: `V=299` fails, `300` and `301` pass at `minimum_ratio="1.5"`. `V=200` is the deliberate mean-versus-median counterexample. The current bar is not added to `S`.

Certified zero volumes are data: if all N preceding volumes are truly zero, the arithmetic threshold is zero and the inequality applies directly, including equality; the displayed division ratio is absent, not infinity. Missing volume is not certified zero. Do not inherit the median evaluator's zero-baseline rejection or add an unmentioned positive-volume minimum. Evidence includes the N bar identities, current identity, `sum_volume_shares`, `window_bars`, `mean_volume_shares`, `minimum_ratio`, threshold and outcome; paginate/display within existing evidence budgets rather than stuffing 500 facts into one 16-fact record.

`ALL`: any false makes false; otherwise missing makes missing; otherwise true. `ANY`: any true makes true; otherwise missing makes missing; otherwise false. Keep evidence for all branches; a false/missing alternative cannot become a global blocker. Only an explicitly applicable safety tree can veto its own rule, following the same three-valued semantics.

## E04. Actions and actual inventory

| Action | Exact shape and effect |
|---|---|
| BUY | `{type: BUY, quantity: positive integer multiple of 100}` -> `BUY_READY` reminder for exactly that quantity |
| SELL | `{type: SELL, quantity: positive integer multiple of 100, inventory_scope: ALL_REGISTERED}` -> `SELL_READY` reminder for exactly that quantity from ordinary sellable inventory |
| RISK_ALERT | `{type: RISK_ALERT}` -> `RISK_ALERT` pure reminder; quantity, bucket, target lot and fill are absent |

BUY requires a known complete current inventory and `total_qty + quantity <= max_qty`. SELL requires known sellability and `sellable_qty >= quantity` under the certified calendar/T+1 facts. Do not round, clamp, split or silently substitute another quantity. `ALL_REGISTERED` includes eligible CORE, TACTICAL and ordinary opening balances; a CORE-only holding of 100 can satisfy SELL 100. There is no target-lot priority in the rule; any optional form allocation is selected by the user and validated separately. Exceeding max blocks new buys but never conceals actual inventory or suppresses a qualifying sell/risk reminder.

The source's “existing 100, sellable today 100” is an **independent human-confirmed inventory assertion**, not `position.core_target_qty=100`, not an AI-created fill, and not an empty-list default. Extend the current position repository with:

- `inventory_confirmation`: symbol, explicit complete-registration assertion, `as_of_trade_date`, `confirmed_at`, `inventory_revision`, and registered balance/lot references; absence means `UNKNOWN`. A confirmed empty inventory is an explicit zero assertion. Confirmation must not postdate the evaluation cutoff.
- An additive ordinary `opening_balance` when only existing settled holdings are known: identity, symbol, original and remaining quantity, `sellable_from` (the confirmed trading date), source/audit and revision. Initially support confirmed fully sellable balances and explicit zero; partially settled/unknown settlement opening inventory remains unresolved. Do not invent cost or acquisition date to satisfy old lot constructors, nor tag ordinary holdings TACTICAL. Existing CORE/TACTICAL lot bytes remain unchanged.
- Existing registered lots plus opening balances yield one snapshot: `status=KNOWN|UNKNOWN`, nullable `total_qty` / `sellable_qty`, revision, as-of/cutoff and missing reasons. Opening balances are counted exactly once. Confirmation references the entire current ledger; an unconfirmed external adjustment invalidates completeness. Subsequent explicit buys/closures update that ledger and revision atomically. Advancing a certified trading date recomputes sellability; missing calendar is unknown, not zero. Expose the last confirmation time; no invented elapsed-time expiry is added.

Opening registration is allowed without an active plan, preventing an activation/registration cycle. It records reality even when total exceeds a candidate maximum; a plan limit is not authority to rewrite holdings. Reuse explicit audited commands, revision and idempotency checks for debiting a referenced `LOT` or `OPENING_BALANCE`; extend the existing closure service for the latter. An opening confirmation against existing lots must identify their already-counted quantity and only add the unrepresented balance; do not import the same 100 twice. A holding change during evaluation invalidates the candidate commit and triggers reevaluation before any alert. A failed or unreadable registration never becomes known zero.

Alerts, retries, delivery, “read”, risk acknowledgement and plan activation do not alter or reserve inventory. A fill exists only after a separate actual-position command. RISK_ALERT consumes no inventory readiness and does not create legacy `risk_state`, `RISK_PENDING`, sell, exit, recovery or automatic buy blocker. Its coexistence effect is only the reviewed conflict policy.

## E05. First trigger, repetition and conflicts

Each rule has a required `repeat_policy`:

- `{mode: ONCE_PER_ACTIVATION}`: emit at the first eligible completed target at or after activation; subsequent satisfying targets for that rule are suppressed throughout that activation revision. Restart, acknowledgement, a false bar, day change, and a recorded fill do not reset it.
- `{mode: EACH_QUALIFYING_BAR}`: each distinct eligible completed target can emit once, including before a fill is registered. No implicit position reservation, daily cap, debounce, re-entry requirement or cooldown. The preview must say that repeated alerts do not represent cumulative filled quantity.

For both modes, a blocked/suppressed candidate does not consume the rule. A same-target retry is not a new opportunity; late manual input applies only to later unclaimed targets. New activation of a newly reviewed version starts a new activation revision and visibly restarts the repeat scope. Re-arming within an activation, once-per-day, wait-for-fill, false-to-true rearm, “first A, then B”, and batch execution are unsupported in v1. List such source requirements as unmapped; never use array order as a sequencing substitute. The original source supplies no repeat/rearm value, so its draft stays unresolved until explicit per-rule choices exist.

Conflicts are evaluated from **currently satisfied condition and safety roots**, before repeat suppression. A still-true risk condition affects conflict policy even when its own alert was already emitted. If BUY and SELL are both eligible on the same target, `trade_conflict=BLOCK_BOTH` suppresses both and records `TRADE_RULE_CONFLICT`; no arbitrary array priority. Risk is never swallowed by a trade's dedup key:

| `risk_conflict` | Same-target risk + BUY | Same-target risk + SELL |
|---|---|---|
| `RISK_ONLY` | Risk candidate; suppress BUY | Risk candidate; suppress SELL |
| `RISK_WITH_SELL_BLOCK_BUY` | Risk candidate; suppress BUY | Independent risk and SELL candidates |

“Candidate” still follows its own repetition policy. Unknown potentially conflicting risk/trade conditions must not be assumed false: hold the affected trade with `CONFLICT_INPUT_UNKNOWN`; known risk may still alert, and unrelated missing volume must not suppress it. Apply position checks only to trade candidates; missing holdings cannot hide pure risk. Unknown safety conditions affect only rules that depend on them. The synthetic ranges make same-target conflicts impossible with one valid close, but the complete policy remains a visible required choice, not an undocumented default.

## E06. Result, persistence and invalidation

Use a v3-only result variant `ExplicitEvaluationResult`, with `result_schema_version=decision-result-v2`, `execution_version=explicit-rules-v1`, existing market/evaluation identity facts, `activation_revision`, `inventory_revision` when consumed, manual-risk revision when consumed, `rule_results`, and `signal_intents` (0–3). Each rule result records condition/safety evidence, outcome, blockers, repeat status, suppression reason, exact action and next step. Do not broaden the old result's singular-intent validation in place. Shared snapshots may choose one primary display label, but all rule results/intents must remain queryable and all emitted alerts visible. State absent from this mode is absent, not a fabricated CLEAR legacy risk state or synthetic episode.

Live evaluation identity extends the existing key for new results with execution version and activation revision: `(plan_hash, symbol, INTRADAY, bucket_end, ta-v1, explicit-rules-v1, activation_revision)`. Persist the kind and full target. Reuse the canonical serializer's exact-number rules under the new `decision-result-v2` NUL-separated hash domain; all semantic fields and consumed revisions participate. Preserve `decision-result-v1` bytes and hashes for old results.

Durable rule state is keyed by `(plan_hash, activation_revision, rule_id)`. It records first emitted target (if any) and last processed target; it is not an episode. Alert dedup uses a distinct `explicit-rule-alert-v1` domain with `(plan_hash, activation_revision, rule_id, action_type, occurrence, quantity_or_null)`, where occurrence is `ONCE_PER_ACTIVATION` or the canonical bucket end. Keep the original triggering cutoff in the payload. A failed delivery retries the same eventId, not a fresh rule occurrence. Retain occurrence identity after alert retention so cleanup cannot rearm a rule.

The existing short unit of work must atomically claim evaluation, recheck active plan/hash/activation revision and R01 target validity, validate consumed inventory/manual-risk revisions, store result and rule state, advance projections, and enqueue **every** surviving intent. Any mismatch/partial failure rolls all of this back. Source/market I/O remains outside the transaction. Duplicate/out-of-order committed targets cannot produce new alerts or overwrite newer rule progress; corrected data cannot replay an already consumed identity as a new trade. A later unclaimed valid target is evaluated normally.

Activation, deactivation, replacement and expiry fence commits and delayed delivery using both target validity and current plan/revision. Preserve old events as historical, `currentActionable=false`, without automatic position prefill. Acknowledged events stay historical evidence. The R01 cross-day official-close `RISK_BREACH` delivery exception is legacy-only; v3 five-minute RISK_ALERT cannot enter it. Intraday catch-up across restart does not emit stale historical trades. Keep new-mode capability disabled if any codec, review, position, result, outbox or consumer cannot handle it; never fall back to legacy execution.

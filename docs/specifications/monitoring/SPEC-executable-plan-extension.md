# Spec: executable-plan-extension (R08 / F06)

> Canonical English; `SPEC-executable-plan-extension.zh-CN.md` is the equivalent Chinese review copy. Date: 2026-09-12. **Design for R09–R12; not an implemented or activated capability.**

## E01. Scope and authority

The approved R08 task permits this bounded extension to `plan-domain`, `decision-engine`, `strategy-state`, `ai-plan-drafting`, `notification-outbox`, and `local-web`. It does not change the original acceptance plan. The source-to-field and S01–S09 oracles are in [R08 mapping](../../../remediation/R08-mapping.md); version and historical compatibility are in [ADR 0005](../../decisions/0005-version-explicit-plan-rules.md). These documents amend the legacy-only statements in the existing specifications only for the new mode.

Keep the current scheduler, normalized bars, SQLite unit of work, review provenance, alert outbox, and position registration. Add bounded variants at their current boundaries. No new platform, rule scripting language, provider, broker, or autonomous trading is introduced. All examples are synthetic. Source omissions become visible `UNRESOLVED` review items, not implicit approval of a suggested value.

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

## E07. Draft review, hashes and API boundary

Keep the current `planHash=SHA256(canonical UTF-8 plan JSON)` unchanged for v1/v2 and use the same exact-document rule for v3. It includes `version` and metadata; therefore it is **not** the semantic content hash. Introduce server-computed `contentHash` only for new v3 review: domain `plan-review-content-v1`, NUL, canonical JSON of the v3 plan excluding exactly `version`, `name`, `metadata`, and `plan_id`. Include symbol, market, schema, execution version, activation, all quantities/conditions/flags/safety/repeat/conflict choices. No unknown field is silently dropped. Separately bind exact source UTF-8 `sourceHash`, mapping/issue snapshot hash `reviewEvidenceHash`, `planVersionId`, and review revision; identical content in a different source/plan cannot automatically gain approval.

Preserve R04 extraction snapshots and R05 `AI_EDITED`/`AI_REIMPORT`/`LEGACY_PENDING` evidence. Their old draft hashes remain exact-document hashes. A version-number increment may preserve semantic comparison, but no old row is relabeled as content-reviewed. R11 adds a trusted confirmation against the **current** server snapshot so an edited AI draft can actually complete re-review; copying resolved client issues never does this. A trade-content change resets approval. A name/metadata/version-only change leaves the semantic content hash equal, but activation still names the new immutable version and current activation revision. No cross-plan approval reuse.

V3 draft and executable models are distinct typed views. A draft may have typed nulls for missing required choices/parameters and server-derived `UNRESOLVED` issues; the executable model requires every value. Save/query can preserve a bounded partial draft under inactive `plan_version`; activation and runtime parse only the complete executable variant. Structural errors, unknown keys/enums or unsafe documents still reject save. Unsupported source semantics stay in review provenance, never as executable strings. Existing v1/v2 codecs and signatures keep their old behavior; add dispatch helpers instead of making old validators permissive.

Reuse existing `/api/v1/plan-drafts`, `/plan-imports`, `/plan-versions`, `/plan-activations` and extraction routes with discriminated v3 draft/read variants. Add only the following bounded command/read contracts where an existing command cannot express the intent (all paths have `/api/v1`):

| Boundary | Required request / response fields |
|---|---|
| `POST /plan-review-confirmations` | `planVersionId`, `contentHash`, `sourceHash`, `reviewEvidenceHash`, `expectedRevision`, explicit resolution records keyed by server `issueId`; response `reviewId`, bound hashes/version, `revision`, `confirmedAt`, unresolved issues and `canActivate` |
| `GET /position-inventory?symbol=...&asOfTradeDate=...` | Typed KNOWN/UNKNOWN inventory snapshot from E04; unknown numeric facts nullable; include confirmation and ledger revision |
| `POST /position-inventory-confirmations` | `symbol`, `asOfTradeDate`, `expectedRevision`, `totalQuantity`, `sellableQuantity`, `includedLotIds`, explicit complete-registration assertion; response authoritative snapshot plus any opening-balance identity and audit receipt |

All writes require existing `Idempotency-Key`/request-hash/revision machinery; identical retry returns the same receipt, different body under the same key returns 422, in-progress or stale revision returns 409. No approval or inventory state is accepted directly from model output. For initial v1 scope, opening confirmation may assert total=sellable or zero after subtracting included known lots; unknown remainder settlement blocks completion. No automatic repeated balance addition on retries or reconfirmation.

V3 activation requires `planVersionId`, `reviewId`, `contentHash`, `expectedRevision` (the active-pointer revision) and current server approval; it atomically increments the active revision. Draft completeness/review controls `canActivate`; inventory and manual-risk availability control a separate `executionReadiness` with missing reasons. An approved plan may be activated to wait for missing runtime inputs, but emits no dependent trade until they are known. The UI must show this distinction. Pending choices/unsupported meaning never activate. An implementation that cannot represent v3 at all reports capability unavailable, not merely “waiting for data”.

### Bidirectional evidence and trusted resolution

R11's v4 review envelope has `mapping_version=plan-mapping-v1`, `source_clauses` and `field_bindings`. Each clause has stable `clause_id`, Python Unicode code-point `start`/`end` offsets into the exact source, the matching excerpt, disposition `MAPPED|UNRESOLVED|UNSUPPORTED`, and destination `paths`. Each binding has a server-validated stored-plan path, typed value, unit (`FEN|SHARES|BARS|MINUTES|RATIO|NONE`), and `origin=SOURCE|USER_SUPPLEMENT|CONTRACT`. SOURCE references clause IDs; USER_SUPPLEMENT references a durable user-supplied value/choice and time; CONTRACT identifies a technical schema literal or server-generated identity. The UI shows origin labels. Contract literals and a human correction cannot cite an unrelated source substring as evidence.

Every material source clause must be mapped or visibly unresolved/unsupported; every non-null executable leaf must have one binding to its actual current value, including operators, inclusion flags, timing, quantity and policy. Rules and logical groups also retain structural bindings so AND/OR or wrong-parent edits cannot look covered merely through matching scalar numbers. Offsets, paths, types and equality are deterministic checks, not a claim that substring matching proves meaning. Human review of the complete source/mapping and the independent corpus remain necessary for semantic correctness. Missing/unreported clauses cannot be waived by a client-supplied empty list.

`reviewEvidenceHash` uses domain `plan-review-evidence-v1`, NUL and canonical JSON of mapping version, ordered clauses/bindings, durable user supplements and server-required issue identities/reasons. Resolution status and confirmation timestamps of the review itself are excluded so confirming does not change its preimage; the timestamps of source supplements remain included. A changed source/mapping/value/required-issue set invalidates review. Server issue IDs are stable within that snapshot; any client omission leaves a required issue unresolved.

Resolution records contain `issueId`, `resolution=CONFIRM_MAPPING|CONFIRM_POLICY|REPLACED_BY_REVIEWED_CONTENT`, and the referenced current binding/supplement. A value correction is saved as a new immutable draft before confirming that version. `REPLACED_BY_REVIEWED_CONTENT` requires an explicit human source supplement and supported replacement mapping, never just `resolved=true`; the original unsupported clause remains in history. A user-approved removal changes the plan's scope and cannot count as passing the unchanged original acceptance oracle. Reconfirmation checks all hashes, version and review revision transactionally before issuing `reviewId`.

## E08. Relationship to R07 manual risk

R07's `plan_hash` is actually the exact canonical plan hash (including version), not the new `contentHash`. Preserve that scope. Confirm only against the active exact planHash; do not migrate a clear assertion across version rotation just because `contentHash` happens to match. Same plan/hash restart retains a still-valid assertion; expiry, hash mismatch, missing record, or post-cutoff confirmation yields unknown. Activation revision independently fences work and repetition; it never implies fresh risk confirmation. Re-activation cannot revive an assertion for different exact content.

R09 must carry the consumed manual-risk revision into the v3 result/commit guard so a concurrent CLEAR -> RISK_PRESENT cannot commit stale BUY. If no rule declares this safety leaf, its absence/expiry does not block the explicit plan. Price risk, semantic plan review, actual-inventory confirmation, manual event-risk review, and alert acknowledgement remain separate concepts and API operations.

## E09. Errors and capability gates

Keep the existing API error envelope and `ValidationIssue(code,path,severity,message,activationBlocking)` shape; these are new domain reason codes, not arbitrary exception strings. V3 output variants must represent their additional readiness, review and rule detail consistently in OpenAPI, generated clients and projections.

| Code | Boundary and consequence |
|---|---|
| `UNSUPPORTED_PLAN_VERSION` / `UNSUPPORTED_EXECUTION_VERSION` | Import, activation, runtime or replay rejects unknown versions; no downgrade/fallback |
| `UNRESOLVED_EXECUTION_POLICY` / `UNMAPPED_MATERIAL_SOURCE` | Save bounded draft, `canActivate=false`; path identifies missing repeat/rearm, timing, history scope, conflict, activation or other meaning |
| `UNSUPPORTED_SEMANTICS` | Preserve source span; whole affected plan non-activatable, including unsupported sequencing |
| `REVIEW_CONTENT_CHANGED` / `REVIEW_EVIDENCE_CHANGED` | Renew current server review; stale confirmation/activation is 409 |
| `EXECUTION_CAPABILITY_UNAVAILABLE` | Required v3 consumer absent; deny activation/evaluation; never translate to old rules |
| `ROLLING_VOLUME_WINDOW` / `TRADING_CALENDAR` | Existing missing-input meanings, scoped to dependent rules |
| `POSITION_UNKNOWN` / `SELLABLE_QUANTITY_UNKNOWN` | Null facts and blocked dependent trade; never zero |
| `MAX_POSITION_EXCEEDED` / `INSUFFICIENT_SELLABLE_QUANTITY` | Known failed trade safeguard; exact requested quantity retained |
| `TRADE_RULE_CONFLICT` / `CONFLICT_INPUT_UNKNOWN` | Retain all rule evidence, suppress only affected trades |
| `RULE_ALREADY_EMITTED` | Visible repeat suppression, not a market-data failure |
| `STATE_REVISION_CHANGED` | Abort transaction and reevaluate fresh inputs; no half-committed event |
| `UNSUPPORTED_BACKTEST_PLAN_VERSION` | Reject v3 research-fill submission while the existing backtest runner is legacy-only |

## E10. Delivery slices and acceptance

R09 owns v3 domain/codec discrimination, legacy prompt preservation before any shared-model edit, exact mean/range evaluation, first eligible BUY, known inventory, repeat state, consumed-state fences and enough result/outbox plumbing to verify BUY offline. R10 adds ordinary SELL and pure RISK_ALERT, all reviewed conflicts/multiple intents and retained legacy risk regressions. R11 owns partial extraction, bidirectional mapping, current-content trusted re-review and v4 prompt release. R12 owns ordinary forms, explicit policy choices, complete preview and authoritative missing-state display. Until each required slice is implemented and validated, unsupported consumer/capability checks must block activation; slice tests may use explicit isolated trusted review inputs without claiming public review is complete.

Required test oracles, exact consumption sites and pending business choices are in [R08 mapping](../../../remediation/R08-mapping.md). R13 independently starts from the unchanged source and labels additional human-confirmation fixture input separately. Source-only extraction must remain blocked when policies are absent; a completed synthetic test fixture must demonstrate why each added policy is known. Offline replay does not place simulated research fills unless a separately versioned backtest contract supports this mode. R14 real provider/user-visible evidence remains separately authorized and unverified.

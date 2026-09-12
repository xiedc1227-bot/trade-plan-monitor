# R08: source mapping, implementation slices and review oracles

Date: 2026-09-12. Canonical English; `R08-mapping.zh-CN.md` is the equivalent Chinese review copy. Baseline: `main/beff0410150813e64a242a3821a299090d963e9b`. **R08-A design complete; R09–R12 implementation pending.**

## M01. Immutable source and status vocabulary

The acceptance artifacts remain unchanged at `C:/Users/xiedc/.codex/visualizations/2026/09/12/01a093fc-f8d3-73d1-b759-ad76c7451697/business-acceptance/`. `acceptance-report.md`, section 6 “Requested scenarios”, records the following target; this is the report's canonical wording, not a newly invented literal transcript of the user's original prose:

> The synthetic plan uses `003043.SZ` as its test identifier. Prices and quantities are acceptance-only synthetic values. The target is preserved in full: existing 100 shares sellable that day; maximum 300; buy 100 when a completed five-minute close is in inclusive [9.80,10.00] AND its volume is at least 1.5 times the arithmetic mean of the preceding five completed five-minute bars; sell 100 for a completed close in inclusive [10.80,11.00]; risk alert below 9.50 on a completed five-minute close; alerts and acknowledgements never change actual positions.

`baseline.md` and R00–R07 handoffs are historical evidence, not a new R08 execution pass. The design authority is [SPEC-executable-plan-extension](../docs/specifications/monitoring/SPEC-executable-plan-extension.md) E01–E10 and [ADR 0005](../docs/decisions/0005-version-explicit-plan-rules.md).

- `SUPPORTED_COMPONENT`: current code has the stated bounded behavior; this does not mean the whole v3 source plan runs.
- `IMPLEMENTATION_REQUIRED`: expressible by R08, requires the named later slice.
- `CONFIRMATION_REQUIRED`: source does not determine a needed choice/fact. Preserve typed null + server `UNRESOLVED`; no silent default.
- `UNSUPPORTED`: v1 explicit mode cannot express it. Preserve source, block activation, do not claim complete support.

## M02. Clause-to-field map

| ID | Unchanged meaning | Exact destination | Current status / owner |
|---|---|---|---|
| C01 | Test identity `003043.SZ` | `symbol`, validated `market=SZSE`; synthetic label is test metadata | `SUPPORTED_COMPONENT`; v3 dispatch R09 |
| C02 | Existing 100, sellable that day 100 | Independent inventory confirmation `totalQuantity=100`, `sellableQuantity=100`, explicitly selected `asOfTradeDate`; ordinary opening balance if no lots represent it | `IMPLEMENTATION_REQUIRED` R09 inventory / R12 form; never AI fill or target position. Registration date/complete-ledger assertion is separate trusted input. |
| C03 | Maximum 300 | `position.max_qty=300`, `inventory_scope=ALL_REGISTERED`, `lot_size=100` | Existing maximum/lot arithmetic is `SUPPORTED_COMPONENT`; known total including ordinary inventory requires R09 |
| C04 | Completed five-minute close in inclusive [9.80,10.00] | `rules[0].confirmation={kind:COMPLETED_BAR_CLOSE,timeframe_minutes:5}`; `condition.conditions[0]={type:COMPLETED_CLOSE_IN_RANGE,low_fen:980,high_fen:1000,include_low:true,include_high:true}` | Existing interval/completed-bar components; v3 direct rule `IMPLEMENTATION_REQUIRED` R09 |
| C05 | AND, preceding five completed bars, arithmetic mean, current >=1.5×, exclude current | `rules[0].condition.type=ALL`; second child `VOLUME_TO_MEAN_GTE`, `window_bars=5`, `minimum_ratio="1.5"`; current is never part of preceding window | `IMPLEMENTATION_REQUIRED` R09; median cannot substitute. `history_scope` review in Q03. |
| C06 | Buy 100 on the first eligible completed satisfaction under the reviewed repeat policy | `rules[0].action={type:BUY,quantity:100}`; repeat independent from quantity | `IMPLEMENTATION_REQUIRED` R09; no initial touch-only episode, core-first requirement or unmentioned MACD |
| C07 | Completed close in inclusive [10.80,11.00], sell 100 | `rules[1].condition={type:COMPLETED_CLOSE_IN_RANGE,low_fen:1080,high_fen:1100,include_low:true,include_high:true}`; same completion; `action={type:SELL,quantity:100,inventory_scope:ALL_REGISTERED}` | `IMPLEMENTATION_REQUIRED` R10; ordinary/CORE-only sellable inventory qualifies without pressure rejection |
| C08 | Completed five-minute close <9.50, pure risk | `rules[2].condition={type:COMPLETED_CLOSE_BELOW,price_fen:950}`; same completion; `action={type:RISK_ALERT}` | `IMPLEMENTATION_REQUIRED` R10; 949 true, 950 false; no quantity, daily wait, persistent official-risk latch or automatic sell |
| C09 | Reminder and acknowledgement are not fills | Separate `signal_intents` / outbox from inventory commands | Existing isolation is `SUPPORTED_COMPONENT`; extend proof to v3 BUY/SELL/RISK_ALERT and opening balance in R09/R10/R12 |
| C10 | No supplied episode, index, indicator, safety threshold or CORE/TACTICAL instruction | New `execution_mode=EXPLICIT_RULES`, no legacy policy fields; `safety_conditions=null` carries no added blocker | Contract-selected mode/absence must be visible, never cited as source prose or assumed user confirmation. R11/R12 show all additions. |

The supported condition/action content maps losslessly. The **source alone remains non-activatable** because the execution choices below are absent. This is not a change to S01's conditional expectation: with explicit reviewed test inputs and both predicates true, BUY 100 must occur; without those inputs, the source-only review must visibly remain incomplete.

## M03. Missing choices and unsupported semantics

| ID | Missing or additional issue | Treatment |
|---|---|---|
| Q01 | Repeat/rearm after an alert, including before an actual fill | Per rule `repeat_policy=null` + `UNRESOLVED_EXECUTION_POLICY`. Offer `ONCE_PER_ACTIVATION` or `EACH_QUALIFYING_BAR`; neither is selected by R08. Same-activation rearm/once-daily/wait-for-fill needs an unsupported marker. |
| Q02 | Effective dates and termination | `activation=null` until user chooses existing MANUAL/TRADING_DAY/DATE_RANGE. No inferred “today”, duration, or expiry. R01 validity rules remain mandatory once chosen. |
| Q03 | Window across lunch/prior trading date | Display `CONTIGUOUS_TRADING_BARS` with calendar adjacency and require explicit confirmation. No silent same-day reset; same-day-only variant is unsupported in v1. Intraday fixture cases alone cannot certify this unchosen edge policy. |
| Q04 | Simultaneous BUY/SELL and risk/trade conflict | `conflict_policy=null` until review selects the finite E05 policy. Source ranges are disjoint, but no global hidden priority is approved. |
| Q05 | Independent holdings completeness/as-of date | Explicit human registration identifies all current lots/balances and date. Source assertion does not prove the production ledger was initialized. Unknown stays null; known zero requires explicit zero. |
| Q06 | Additional/manual-risk safety requirements | None supplied in source; show that no extra safety tree is declared. If the user adds one, bind its value/path to user evidence and consume R07 only where declared. Do not insert a mandatory CLEAR prerequisite. |
| U01 | “First A, then B”, after a confirmed fill, false-to-true rearm, batching | `UNSUPPORTED`; v1 has no temporal automaton/cross-rule dependency. Do not translate to ALL, array order or the legacy episode. |
| U02 | Other timeframes, daily-reset mean, index/indicator/formula conditions in explicit mode | `UNSUPPORTED`; legacy supported plans can still use their explicit legacy/index contracts. Switching modes requires actual new review. |
| U03 | Partial/unknown settlement opening balances; unspecified cost/acquisition facts | Preserve facts and missing items. First release opening balance requires known fully sellable remainder; never invent cost/date or classify as TACTICAL. |
| U04 | V3 simulated research fills / portfolio backtest | `UNSUPPORTED_BACKTEST_PLAN_VERSION`; pure monitor replay remains possible. Existing historical legacy backtest data stays readable. |

One optional user question about Q01 was raised during R08. The coordinator explicitly confirmed that no global answer is required for contract completion; unanswered means unresolved. No response selecting a repeat policy has been recorded in this design. A later answer must be recorded as a scoped source supplement, not retroactively inserted into the untouched source. Other choices can remain visible pending fields without blocking implementation of their finite contract.

## M04. Reviewable draft example

This is a **partial synthetic v3 draft illustration**, not accepted by the current baseline parser, not an executable fixture, and not a real plan. `plan_id`, name, version and technical literals are test/contract metadata. `null` choices remain unresolved; `safety_conditions=null` means no extra tree is asserted, not that a user already reviewed its absence. C02 is intentionally outside this document.

```json
{
  "schema_version": 3,
  "execution_mode": "EXPLICIT_RULES",
  "execution_version": "explicit-rules-v1",
  "plan_id": "synthetic-f06",
  "version": 1,
  "symbol": "003043.SZ",
  "name": "SYNTHETIC F06",
  "market": "SZSE",
  "metadata": {},
  "activation": null,
  "position": {"inventory_scope": "ALL_REGISTERED", "lot_size": 100, "max_qty": 300},
  "monitoring": {"timeframe_minutes": 5, "indicator_formula_version": "ta-v1"},
  "rules": [
    {
      "rule_id": "buy-100",
      "condition": {"type": "ALL", "conditions": [
        {"type": "COMPLETED_CLOSE_IN_RANGE", "low_fen": 980, "high_fen": 1000, "include_low": true, "include_high": true},
        {"type": "VOLUME_TO_MEAN_GTE", "window_bars": 5, "minimum_ratio": "1.5", "history_scope": null}
      ]},
      "action": {"type": "BUY", "quantity": 100},
      "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
      "repeat_policy": null,
      "safety_conditions": null
    },
    {
      "rule_id": "sell-100",
      "condition": {"type": "COMPLETED_CLOSE_IN_RANGE", "low_fen": 1080, "high_fen": 1100, "include_low": true, "include_high": true},
      "action": {"type": "SELL", "quantity": 100, "inventory_scope": "ALL_REGISTERED"},
      "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
      "repeat_policy": null,
      "safety_conditions": null
    },
    {
      "rule_id": "risk-950",
      "condition": {"type": "COMPLETED_CLOSE_BELOW", "price_fen": 950},
      "action": {"type": "RISK_ALERT"},
      "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
      "repeat_policy": null,
      "safety_conditions": null
    }
  ],
  "conflict_policy": null
}
```

## M05. S01–S09 without weakening the original oracle

| Scenario | Original expectation retained | Baseline evidence / missing implementation | Required new evidence |
|---|---|---|---|
| S01 | Price alone must not buy; price AND mean-volume true on completion -> BUY 100 | Existing logical components; F06 remains `IMPLEMENTATION_REQUIRED` R09 | Nonuniform history; first eligible target; known original inventory; clearly separate Q01–Q05 trusted test supplement; full source-only draft remains blocked |
| S02 | 9.80/10.00 inclusive; exact 1.5 accepted | Range/median comparison components only; no mean pass inherited | 979/980/981/999/1000/1001 fen; volumes 299/300/301 with mean 200; no median substitute |
| S03 | Pre-close satisfaction followed by final failure produces no completed-bar alert | Existing completed/gapless market safeguards | Same v3 plan before completion, final close/volume failure, duplicate/incomplete target; no premature intent |
| S04 | Completed sell-range -> SELL 100; completed close <9.50 -> pure risk | Legacy pressure/official-close tests do not prove this; R10 required | 1079/1080/1100/1101; 949/950/951; ordinary and CORE-only sellable 100; no daily-close wait or fabricated quantity |
| S05 | Ambiguous “企稳后买入、放量突破” must not invent parameters | R04 closes API issue omission; semantic extraction remains incomplete | Null fields and retained source omissions; forged unrelated excerpts cannot establish review; R11/R12; real-model accuracy only R14 |
| S06 | AI errors/malformed/omitted content cannot activate or harm active plan | Existing parse/failure and R04/R05 barriers; unreported omissions/current edited-review completion still R11 | Complete and partial v4 candidates; server mandatory issue coverage; no activation on missing policies; current-content confirmation after edits; failed extraction leaves active pointer unchanged |
| S07 | Stale/unordered/duplicate/disconnected/partial data fabricates no signal; health visible | Existing data boundaries and R02 recovery; v3 consumption still required | Per-rule missing dependencies, all target/cutoff fences; risk visible despite unrelated volume gap; frontend recovery refreshes new alert variants |
| S08 | Retries/restart deduplicate; acknowledgement never changes actual holdings | Existing isolation/dedup components; no blanket v3 pass | Both repeat policies; per-rule causes; atomic two-intent risk+sell rollback/retry; no opening balance/lot changes on alert/ack; external at-least-once remains |
| S09 | Updates/disable/expire stop valid new old-version actions | R01 date/rotation fences; queued-alert query regression remains open before R09 | New execution/review/hash/active revision guards; expiry on target/current delivery date; historical labeling; no legacy cross-day risk exception for RISK_ALERT |

## M06. Consumer map and ordered R09 slices

All Python paths below are relative to `src/trade_plan_monitor/`. This is an internal refinement of R09-A/B, not new sidebar tasks or permission requests. Execute sequentially in the same R09 task; keep each change independently reviewable and commit after its focused checks. If a slice spans additional independent responsibilities, split it again without weakening gates. The coordinating task first owns the independent R01 outbox repair.

| Slice | Reuse / required new boundary | Acceptance before proceeding |
|---|---|---|
| R09.1 Compatibility and model boundary | `domain/plan_models.py`, `plan_codec.py`, `plan_hash.py`; sibling v3 types/dispatch; unchanged `ai/models.py::TradePlanDraft` and `ai/prompts.py` graph | Old plan bytes/hashes, all three schema/prompt digests, legacy replay payloads unchanged; explicit unsupported version errors; v3 partial draft cannot execute; schemas have parity |
| R09.2 Pure mean/range leaves | `decision/conditions.py` exact arithmetic, `_recent_bars`, calendar adjacency and logical helpers; v3 path-addressed evidence | T01–T04, including nonuniform mean, equality, exclusion of current, all-zero certified data, gaps, lunch/cross-day; no episode/indicator dependency |
| R09.3 Authoritative inventory | `state/models.py`, `repositories.py`, additive migration, `web/position_service.py`; independent complete inventory/opening balance and revision | T05/T06: unknown vs explicit zero, pre-existing sellable100/max300, no active-plan prerequisite, no fabricated cost/date, no double count, idempotency/restart; neither reminders nor plan edits mutate inventory |
| R09.4 V3 pure rule/result contract | `decision/models.py`, `engine.py`, optional small `decision/explicit_rules.py`; `ExplicitEvaluationResult`, direct BUY and repeat transition proposal | First qualifying target emits 100; ONCE/EACH before/after fill; no legacy latch; current inventory guard; retained evidence; deterministic new result hash and old result compatibility |
| R09.5 Durable rule/result/outbox participants | `state/repositories.py` and projection participants, `notifications/models.py`, `identity.py`, `render.py`, `outbox.py`; additive identity/payload constraints and rule occurrence state | Commit result/state/BUY alert atomically; rollback after enqueue retains no claim; restart/retry retains eventId and repeat suppression; legacy event/migration bytes unchanged; unsupported consumers explicitly deny capability |
| R09.6 Production dispatch and state fences | `runtime/production.py`, `production_context.py`, `service.py`; build only required explicit-mode evidence, consume inventory/manual-risk revisions, guard at commit | Temporary real SQLite/scheduler composition verifies S01/S02/S03 and expiry; concurrent activation/position/manual-risk edits cannot commit stale BUY; optional indicators/index/manual-risk absence not global blockers |
| R09.7 Local transport and integration checkpoint | Existing plan/position/alert DTOs, projections, `openapi.json`, generated client types; backend-authoritative v3 capability/readiness fields | Contract generation/check, source-only incomplete plan blocked, explicit trusted test review adapter labeled isolated, new BUY alert queryable, legacy focused regressions; public v3 activation remains unavailable until R11 review/R12 required consumers are ready |

R09.1–R09.2 implement the original R09-A intent. R09.3–R09.7 are necessary decomposition of R09-B, not evidence those features already exist. A BUY-only isolated fixture is a **derived subset**, never relabeled as the complete three-rule acceptance plan. Consumers may advertise supported actions independently; any plan asking for an unimplemented action must fail capability validation. The full source plan cannot pass R09 alone.

| Later step | Required consumption |
|---|---|
| R10-A | Extend direct action evaluator and current position closure path for ordinary SELL; settlement/insufficient quantity and existing bucket compatibility |
| R10-B | New pure risk leaf/action, explicit conflicts, multiple-intent result -> transaction -> payload -> query -> render; never reuse persistent official-risk transitions or the legacy historical delivery exception |
| R11-A | **Implemented and offline-verified.** `ai/models.py`, `prompts.py`, `extraction.py`, persistent review records and `web/plan_service.py`; separate v4 parser, partial draft, original-span-to-leaf and leaf-to-origin coverage, current edited-content confirmation |
| R11-B | **Implemented and offline-verified.** Independently fixed 20-case corpus: 8 explicit / 6 ambiguous / 6 unsupported, with expected and actual semantic outcomes recorded separately; no real AI call |
| R12-A/B | Existing plan forms and preview, inventory confirmation/closure forms, per-rule policy selection, original/current/diff/provenance, all rule outcomes/alerts, server-authoritative `canActivate` versus `executionReadiness`; no mandatory JSON |

## M07. Targeted test oracles

These are future tests, not tests run by R08. Reuse existing unit/replay/integration suites and temporary SQLite/Fake SDKs; no live AI, market, notification or trade. Test additional policies through a named `human_confirmed_test_supplement`, with explicit sourceHash/choice paths/values and confirmation timestamp. Keep original source-only extraction assertions separately. Fixture dates, cost (if a legacy lot fixture needs one), repeats and conflict choices must never be attributed to the original text.

| Test | Independent expected result |
|---|---|
| T01 | Prior [100,100,100,100,600] -> mean200, median100; current200/299 false, 300/301 true at1.5; mean excludes current; ambient Decimal precision does not change outcome |
| T02 | Buy fen979 false,980/981/999/1000 true,1001 false with qualifying volume; sell1079 false,1080/1100 true,1101 false; risk949 true,950/951 false |
| T03 | Incomplete target, missing one prior bar, duplicate/reversed/future/mixed-symbol bar or unavailable required calendar cannot emit a dependent alert; exact lunch/prior-open-day adjacency works only after Q03 test confirmation |
| T04 | Five certified zero volumes apply arithmetic threshold zero; missing volume never becomes zero; price-only false-volume ALL cannot buy; true ANY with missing alternative stays true |
| T05 | Missing inventory -> null and blocked BUY/SELL; explicit zero -> known0; original confirmed100 plus BUY100 -> unchanged actual100, allowed candidate; known200+100 reaches300, known300+100 blocks; unconfirmed unrelated source text cannot initialize it |
| T06 | Ordinary opening100 or CORE-only sellable100 satisfies SELL100; known insufficient quantity blocks, unknown settlement stays unknown; no cost/date invention, T+1 restriction and missing calendar respected; idempotent reconfirmation never doubles100 |
| T07 | ONCE emits on first eligible completed target; subsequent true/false/true/day-change/ack/fill/restart does not rearm. EACH emits once per distinct qualifying target even without fill; both retain actual inventory unchanged |
| T08 | Same-target BUY+SELL -> neither; risk+SELL obeys selected policy; already-emitted but still-true risk retains conflict effect; unknown potentially conflicting root blocks affected trade; pure risk unaffected by unrelated missing volume/inventory |
| T09 | Crash after one of risk+SELL enqueues rolls back both, result and rule state; retry creates both once with separate stable dedup identities; later delivery retry keeps eventId; retention cannot rearm |
| T10 | Concurrent inventory update or declared manual-risk CLEAR -> RISK_PRESENT between evaluation and commit aborts stale intent; retry reads current revision. Undeclared manual risk has no effect. |
| T11 | Price/operator/ALL-ANY/quantity/timeframe/repeat/conflict/safety/activation/execution-version edits change contentHash and invalidate review; name/metadata/version-only edits keep contentHash but require exact new-version binding. Source/evidence edits require renewed mapping review. |
| T12 | Changing version changes planHash and makes R07 confirmation unknown, even with equal contentHash; same hash restart preserves unexpired pre-cutoff confirmation; expiry/post-cutoff/missing remain unknown |
| T13 | Before-start/end+1/disable/rotation/stale active revision -> no new valid old-version trade; historical rows visible as non-actionable; v3 risk never uses cross-day official-close exception |
| T14 | V1/V2 document round-trip and result hashes; prompt v1/v2/v3 digests; deliberate old-schema mutation fails guard; wrong prompt/output schema rejected; new v4 has separate reviewed digest |
| T15 | Source-only synthetic draft retains all C01–C10 meanings and unresolved Q01–Q05; no full-support/activation claim. “企稳后买入、放量突破” has no invented thresholds. Unsupported ordering cannot resolve by generic acknowledgement. |
| T16 | Edited AI draft saves pending, then explicit current snapshot review can complete; stale/forged/omitted issue lists, reimport, and failed provider output cannot activate or replace active plan |
| T17 | Full offline source + separate supplements -> review/save/activate -> scheduler -> resultHash -> all eventIds -> browser display/ack -> no position mutation; repeat after restart and R02 snapshot recovery; no JSON edits required |
| T18 | Legacy backtest files/IDs/results remain unchanged; v3 research-fill submission fails explicitly before enqueue; pure v3 replay is labeled monitor replay, not portfolio backtest support |

## M08. Current-source review and outstanding integration issue

Checked actual code, not only old handoffs: `plan_models.py::TradePlan`; `plan_codec.py::_plan_json_data`; `plan_hash.py::plan_sha256`; `ai/models.py::TradePlanDraft`; `ai/prompts.py::_render_frozen_schema`; `web/plan_service.py::_resolve_server_review` / `_pending_edited_review`; `runtime/production_context.py::ProductionContextBuilder` / `_manual_event_risk_for_plan`; `decision/conditions.py::_median_volume_facts`; `decision/engine.py::_position_summary`; `decision/models.py::SignalIntent` / `_EvaluationResultPayload`; `runtime/service.py::run_intraday`; `web/position_service.py`; `notifications/outbox.py`; `backtest/runner.py` and `run_input.py`.

Important coupling: current context requires official history and computes indicators even for simple rules; current summary sums empty lots to zero; initial lot recording requires an active plan and a bucket/cost/date; result/outbox assume a single intent and targeted sell lot. These are implementation gaps for the new mode, not harmless stored fields. R09/R10 must address their actual consumption paths without changing legacy historical contracts.

`AlertOutbox._active_plan_for_event` currently returns `False` at both absent/mismatched active-plan branches, then callers dereference `.activation` under a `TradePlan | None` contract. **Both erroneous returns originate in R01 commit `099e41e`, not the original acceptance baseline.** Earlier R04–R07 references to an “existing baseline” mean their local post-R01 baselines, not the original review commit. The coordinator has reserved an independent R01 regression repair before R09. R08 does not fix it and does not count alert composition as green. The repair must retain no-current-plan/mismatched-plan historical labeling and fail-closed delivery, with focused regressions.

## M09. R08 completion boundary

R08 delivers bilingual design, exact mapping and implementation constraints. No v3 code, migration, real plan, holding or provider operation is performed. Missing source choices are faithfully represented as pending; no indispensable global business answer is required to finish this design. R09–R12 remain implementation work, R13 offline independent acceptance, and R14 separately authorized real evidence. Successor creation belongs exclusively to the coordinating task; this R08 task creates none.

# Specification: market-linkage-p0

Status: APPROVED — on 2026-10-24 the user approved all six decisions and specifications and explicitly authorized ordered implementation. Progress is governed by acceptance evidence; unfinished tasks are not shipped capability.
Implementation evidence is maintained in [the verification report](../../verification/2026-10-24-market-linkage-p0.md).
Canonical English; [Chinese review copy](SPEC-market-linkage-p0.zh-CN.md). [Implementation tasks](../../../tasks/market-linkage-p0.md).

## MLP01 — Objective and authority

Make the reusable trade-plan prompt's ordinary market-linked low-buy rules representable, reviewable, monitorable and replayable in the single `/plans` workflow. This specification covers approved P0 implementation and local acceptance. Live deployment and user-database migration are outside this work.

Source: [README prompt](../../../README.md#generic-trade-plan-prompt), [current workflow](SPEC-unified-plan.md), [index identity](SPEC-index-identity.md), [index facts](SPEC-index-data.md), [historical index conditions](SPEC-plan-index-conditions.md). Existing index facts and historical Schema 2 leaves are reusable infrastructure, not proof of current Schema 5 linkage support. Do not overwrite unrelated active plans or task lists.

## MLP02 — Capability map and build order

| Module ID | Scope / specification | Depends on |
| --- | --- | --- |
| `market-regime` | Exact board-index evidence and four-state classification; [spec](SPEC-market-regime.md) | Existing index identity/data and calendars |
| `relative-strength` | Aligned stock/index 5/20-session returns and stock MA20; [spec](SPEC-relative-strength.md) | `market-regime` evidence contract, existing stock daily data |
| `confirmation-selection` | Source-bound S0/S1/S2 composition and one selected route; [spec](SPEC-confirmation-selection.md) | `market-regime`, `relative-strength`, existing conditions |
| `quantity-policy` | Q0, reduction, legal quantities and immutable signal quantity; [spec](SPEC-quantity-policy.md) | `confirmation-selection`, existing inventory/lifecycle |
| `market-linkage-workflow` | Extraction, review, persistence, runtime, UI and replay; [spec](SPEC-market-linkage-workflow.md) | All four modules |

Build in table order, with extraction/review and focused verification alongside each module. These are logical boundaries, not separate services or new product workspaces. P0-5 runs through every slice; complete integration is a release gate.

## MLP03 — Scope and exclusions

P0 adds opt-in market policy to DAILY-confirmed ordinary BUY rules in TACTICAL. Existing unlinked conditions, ordinary SELL, technical exits, reminders and five-minute monitoring retain their meaning. P0 does not add index-driven SELL or liquidation. Higher-priority existing risks continue to block buys. Market improvement alone does not create a buy signal.

All six rows of the prompt's market table must be represented. Non-exception routes can become actionable; the weak-market minimum-lot exception and broken-market strong-stock exception remain explicit `P1_EXCEPTION_REQUIRED` with zero authorized quantity. They cannot be activated as automatically executable exception routes, deleted, or reclassified as human facts. P0 can review a plan containing these faithfully represented blocked routes while enabling its ordinary routes. Until this capability is implemented and accepted, the current prompt's blocked-A behavior remains.

Excluded: P1 exception approval, arbitrary formulas, dynamic Q0 inferred from volatility, CORE creation by ordinary buying, non-100-share simulation, broker integration, fundamental monitoring, automatic risk-line changes, extra providers and blanket certification of all boards. Existing unsupported provider/calendar scopes remain blocked; notably, BSE mapping alone does not establish BSE index or historical-calendar availability.

## MLP04 — Review decisions

| ID | decision | Reason / consequence |
| --- | --- | --- |
| MLP-D01 | New linked plans use `schema_version=6`, `execution_mode=CONDITION_PLAN`, `execution_version=condition-plan-v2`; existing Schema 5 plans remain supported unchanged | A variable quantity policy changes executable semantics; preserve historical bytes/hashes and avoid silent conversion. Internal versions are not a UI selector. |
| MLP-D02 | Linkage confirms only on completed official daily evidence for exact session D; execution is the next exchange session | Prevent intraday state flicker and lookahead. Original fixed five-minute rules remain supported. |
| MLP-D03 | Require all stock/index observations on the same scheduled sessions; do not fill suspended/missing stock days | Unknown relative strength grants no exemption. This is deliberately conservative and may reduce eligible days. |
| MLP-D04 | At confirmation compute the market-adjusted full quantity, then check available capacity; insufficient capacity blocks the whole quantity | Preserve existing atomic simulation. No automatic capacity clipping or partial substitute. |
| MLP-D05 | Freeze the selected route and quantity for a signal; later evidence changes invalidate authority rather than resize it | Prevent automatic enlargement, duplicate trades and silent strategy changes. A new signal needs its reviewed independent-signal policy; no extra delay for unchanged valid signals. |
| MLP-D06 | P0 never approves either strong-stock exception; display the eligibility evidence and persistent P1 block | Ordinary routes can ship without inventing a human exemption workflow. |

These six decisions and their implementation are explicitly approved. Strategy changes still require equivalent English/Chinese specification amendments.

## MLP05 — shared contract

Linked rules replace fixed `quantity` with `quantity_policy`; fixed rules retain `quantity`. The two forms are mutually exclusive. A linked BUY also carries `market_policy` and its explicit base `condition` (S0). A plan with linked rules carries server-derived `reference_market` using existing `AUTO_BOARD` and `board-index-map-v1`; supplied identity mismatch is rejected.

`market_policy.policy_version=market-linkage-v1`, `market_policy.base_confirmation=S0`, `market_policy.exception_policy=BLOCK_P1`. These identify the fully expanded, source-bound decision table, not hidden default trading rules. Thresholds, route predicates, quantity factors and confirmation groups must be traceable to source or a reviewed supplement. A mere S0/S1/S2 label without its definition is unresolved.

Module outputs share `decision_session`, `evidence_cutoff`, `source_hashes`, `formula_version`, operand values, outcome and reasons. The final projection contains `regime`, `relative_strength`, `selected_confirmation`, `base_quantity`, `quantity_factor`, `candidate_quantity`, `authorized_quantity`, `blocked_reasons`, and `signal_id` when one exists. `candidate_quantity` is nullable when calculation is impossible; `authorized_quantity=0` conveys no trade authority and is never a zero-quantity ordinary action.

Keep existing depth 4 and total 50 condition-leaf bounds; validate expanded S0/S1/S2 conditions without silently discarding leaves. Generated duplication may be normalized only with equivalent evidence and source bindings. No new dependency is proposed. Persistent evidence, projection and hash versions must be explicit before code changes; old serializers must not acquire new default fields.

## MLP06 — Timing and product invariants

One cutoff must govern stock data, index data, scoped facts and plan authority. A record must both describe a completed session and have been available by the cutoff. Do not fall back to an older day when D is missing. Source corrections preserve earlier evidence and invalidate affected pending authority; they never rewrite executed history. Same-session corrections are not new independent signals.

Live monitoring and frozen replay call the same pure policies. Historical index/stock revisions and adjustment basis must be frozen; later provider revisions cannot alter earlier decisions. Simulation inventory, actual holdings records and backtest portfolios remain isolated. Network I/O stays outside transactions. Review, activation, acknowledgement and reminders never alter inventory.

## MLP07 — Implementation conventions and verification

Use the existing Python 3.14, strict immutable Pydantic models, exact Decimal arithmetic, pytest, FastAPI/SQLite and Vue/TypeScript stack. Domain rules belong under `src/trade_plan_monitor/domain` and `decision`; index facts stay under `market_index`; adapters and Vue render server authority. Use snake_case and narrow pure functions, for example `classify_market_regime(evidence) -> MarketRegimeEvidence`; no implicit clock/provider reads in policy evaluation. Preserve existing quality checks; do not invent a new coverage threshold.

Verification commands from `trade-plan-monitor/` (actual results are recorded in the verification report):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_review.py tests/integration/test_market_linkage_runtime.py tests/integration/test_market_linkage_replay.py -q
.\.venv\Scripts\python.exe -m pytest -m "not live" -q
.\.venv\Scripts\python.exe -m ruff check src tests
npm --prefix web run test -- --run
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e -- tests/e2e/market-linkage.spec.ts
```

New test paths are implemented deliverables. Unit checks must assert independent expected arithmetic and branch outcomes. Integration uses real temporary SQLite and deterministic providers. Browser acceptance uses local synthetic data; no real provider calls or user-database changes are implied. Existing provider certification remains necessary for actual operation.

## MLP08 — Release criteria and document index

All module acceptance IDs MR-A01–MR-A05, RS-A01–RS-A04, CS-A01–CS-A05, QP-A01–QP-A05 and WF-A01–WF-A06 must pass, with task traceability and bilingual verification evidence. Cover all market rows, unknowns, equalities, alignment, atomicity, restart, future-data mutations, source corrections, repeated signal consumption and unchanged unlinked plans. No task is complete based only on a pure function test when it changes production composition.

Always preserve source meaning, frozen identities and paired documentation. Seek a specification amendment for P1 scope, extra providers/dependencies or changed strategy decisions. Never fabricate human approval, remove unsupported dependencies to pass review, bypass risk or claim live certification from offline tests. Implementation authorization must precede all code work.

This specification, five module specifications and the [task list](../../../tasks/market-linkage-p0.md) form the approved implementation package. The paired capability map, README prompt, API contracts, operations guide and verification report describe implemented support and its acceptance limits.

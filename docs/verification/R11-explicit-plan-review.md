# R11 Explicit Plan Review Verification

## Scope and corrected claim

This report verifies the R11 explicit-plan review boundary offline. No live AI provider, market-data provider, notification channel, trade endpoint, production database, credential, quota, or network request was used.

The initial report described the 20 passing cases in `explicit-plan-semantic-corpus-v1.json` as the fixed semantic corpus. That was too broad. Those cases bind an arbitrary source string to a generic risk-alert draft and assert only keyword-derived semantic codes. They are retained unchanged as useful lexical-classifier regression evidence, but **their 20/20 result is not semantic source-to-plan acceptance evidence**.

The corrective acceptance corpus is `tests/fixtures/ai/explicit-plan-semantic-acceptance-v2.json`. Every case contains its own source, independent expected typed fields and units, bounds, action, quantity, time semantics, logical structure, unresolved paths, unsupported-reason fragments, simulated provider partial response, and source mapping. The tests send that response through the real v4 provider boundary, parser, and server review builder. This is deterministic simulated-provider evidence, not a claim about real-model accuracy.

## V2 semantic source-to-plan results

`Actual` records what the provider/parser/server-review chain produced. `MATCH` means every oracle field value and unit, cited source excerpt, logical parent and children, unresolved path set, and semantic-code set matched—not merely the listed highlights.

| ID | Source | Independent expected meaning | Actual |
|---|---|---|---|
| SEM-EXP-01 | `003043.SZ` completed 5-minute close in CNY 9.80–10.00 inclusive; buy 100 shares | symbol; 5 `MINUTES`; 980–1000 `FEN`, inclusive; `BUY` 100 `SHARES`; no semantic blocker | MATCH; `NONE` |
| SEM-EXP-02 | Completed 5-minute close below CNY 9.50; risk alert | 5 `MINUTES`; 950 `FEN`; `RISK_ALERT`; no semantic blocker | MATCH; `NONE` |
| SEM-EXP-03 | Inclusive price range AND volume at least 1.5× the arithmetic mean of the previous 5 completed 5-minute bars; buy 100 | `ALL` with price and volume children; 980–1000 `FEN`; 5 `BARS`; 1.5 `RATIO`; `CONTIGUOUS_TRADING_BARS`; 100 `SHARES` | MATCH; `NONE` |
| SEM-EXP-04 | Completed 5-minute close in CNY 10.80–11.00 inclusive; sell 100 registered shares | 1080–1100 `FEN`, inclusive; `SELL` 100 `SHARES`; `ALL_REGISTERED` | MATCH; `NONE` |
| SEM-EXP-05 | Manual activation; below CNY 9.50 risk alert; once per activation | `MANUAL`; 950 `FEN`; `RISK_ALERT`; `ONCE_PER_ACTIVATION` | MATCH; `NONE` |
| SEM-EXP-06 | Buy rule, sell rule, and simultaneous trade conflict blocks both | `BUY` 100; `SELL` 100; `trade_conflict=BLOCK_BOTH` | MATCH; `NONE` |
| SEM-EXP-07 | Buy rule, risk rule, and simultaneous risk/trade conflict keeps risk only | `BUY`; 950 `FEN` risk alert; `risk_conflict=RISK_ONLY` | MATCH; `NONE` |
| SEM-EXP-08 | `003043.SZ`, maximum position 300 shares, buy 100 on the explicit range | symbol; 300 and 100 `SHARES`; explicit completed-bar range | MATCH; `NONE` |
| SEM-AMB-01 | Buy 100 after price “stabilizes” | preserve `BUY` 100; condition unresolved | MATCH; `UNRESOLVED_SEMANTICS` |
| SEM-AMB-02 | Buy 100 on “obvious high volume” | preserve `BUY` 100; volume threshold/window unresolved | MATCH; `UNRESOLVED_SEMANTICS` |
| SEM-AMB-03 | Sell 100 when an advance is “blocked” | preserve `SELL` 100; price condition unresolved | MATCH; `UNRESOLVED_SEMANTICS` |
| SEM-AMB-04 | Completed 5-minute close “stabilizes” AND “high volume”; buy 100 | preserve 5 `MINUTES` and 100 `SHARES`; combined condition unresolved | MATCH; `UNRESOLVED_SEMANTICS` |
| SEM-AMB-05 | Price “blocked” AND “obvious high volume”; sell 100 | preserve `SELL` 100; parent/children unresolved | MATCH; `UNRESOLVED_SEMANTICS` |
| SEM-AMB-06 | Completed 5-minute close “near CNY 10 and stabilizes”; risk alert | preserve 5 `MINUTES` and `RISK_ALERT`; numeric range unresolved | MATCH; `UNRESOLVED_SEMANTICS` |
| SEM-UNS-01 | “Effective breakdown” below CNY 9.50; sell 100 registered shares | preserve 950 `FEN`, `SELL` 100; confirmation unsupported | MATCH; `UNSUPPORTED_SEMANTICS` |
| SEM-UNS-02 | First stabilize, then high volume, then buy 100 | preserve `BUY` 100; terms unresolved and sequencing unsupported | MATCH; both semantic codes |
| SEM-UNS-03 | First buy 100, then sell 100 after a rise | preserve both quantities; cross-clause sequencing unsupported | MATCH; `UNSUPPORTED_SEMANTICS` |
| SEM-UNS-04 | Unqualified close below CNY 9.50; risk alert | preserve 950 `FEN` and alert; completed 5-minute confirmation unresolved | MATCH; `UNSUPPORTED_SEMANTICS` |
| SEM-UNS-05 | Buy 100 after breakout and subsequent pullback | preserve `BUY` 100; sequencing unsupported | MATCH; `UNSUPPORTED_SEMANTICS` |
| SEM-UNS-06 | After an effective breakdown, wait for the next close | preserve alert intent; threshold/time unresolved; sequencing and close qualification unsupported | MATCH; `UNSUPPORTED_SEMANTICS` |

Result: **20/20 v2 source-to-plan cases passed**: 8 explicit, 6 ambiguous, and 6 unsupported. This result covers the simulated-provider contract only. It does not replace separately authorized live-model evaluation.

## False-positive and adversarial evidence

- `SEM-CTX-01` proves that the global context “only monitor completed 5-minute bars” qualifies the following close clause without an unqualified-close false positive.
- `SEM-DEF-01` proves that bounded definitions of “high volume” (previous 5 completed bars, arithmetic mean, 1.5×) and “effective breakdown” (completed 5-minute close below CNY 9.50) do not trigger term-only blockers. Undefined uses remain blocked.
- Wrong business units are rejected as invalid provider output. Missing volume-window mappings and extra position limits produce `UNMAPPED_PLAN_FIELD`.
- Internally consistent but source-wrong quantity, action, `ALL`→`ANY`, and logical-parent clause attribution remain non-activatable and require exact source-mapping review.
- Removing the sell clause or risk-alert clause mapping from the historical derived three-rule fixture leaves that exact clause `UNRESOLVED` and its action field unmapped.

## Historical derived-shorthand API chain (not literal user source)

The historical `_ORIGINAL_SOURCE` is a derived three-rule shorthand, not the user's literal source. The previous claim that it was the unchanged full user source is withdrawn. It remains unchanged as regression evidence. Its partial save reports exactly six missing execution-policy paths: activation, conflict policy, volume history scope, and the three repeat policies. `safety_conditions=null` is optional and is not misreported as a missing policy.

The current-content edit adds those seven concrete policy values as durable `USER_SUPPLEMENT` records, separately from `SOURCE`. Before submitting confirmation, the test checks each source issue against the exact current typed value and cited server clause, and each policy issue against the exact supplement path/value. After confirmation, activation remains false because the combined current-position clause and the “alerts/confirmation are not fills” clause remain unresolved, and `symbol` remains unmapped rather than using that combined clause as partial proof.

This chain exposed and fixed a mapping-reconciliation variable-shadowing defect that had incorrectly changed unreferenced clauses to `MAPPED` during edits.

## Literal-source completion correction (2026-09-13)

`explicit-plan-literal-source-v3.json` stores the exact provided text including line breaks, its sole explicitly recorded substitution `测试股票` → `003043.SZ`, and separate field/unit/source-clause and human-supplement oracles. The simulated response crosses the actual v4 provider/parser boundary, then ordinary partial-save, read, edit and review APIs in temporary SQLite. The fixture is not a live-model accuracy claim.

| Boundary | Expected and observed |
|---|---|
| Source only | Six missing policy paths; no reviewId, content canActivate=false |
| Current edit | Eight explicit human test supplements: TRADING_DAY plus 2026-09-14, three repeat choices, two conflict choices, volume history scope |
| Current mappings reviewed, treatments omitted | Exactly two SOURCE_TREATMENT_REVIEW_REQUIRED issues remain; content canActivate=false |
| All current values and treatments reviewed | Valid reviewId; content canActivate=true; executionReadiness=NOT_EVALUATED; public activation returns409 |
| Inventory isolation | Save/edit/review leave UNKNOWN with null quantities; separate public confirmation registers100; same-key retry and new-key reconfirmation keep100 and the same opening balance |
| Runtime/alerts | Real isolated explicit runtime commits pure RISK_ALERT with UNKNOWN inventory; BUY/SELL/RISK alert enqueue and public acknowledgement/retries leave registered inventory unchanged |
| Compatibility | Reviewed/unreviewed old v1 records without source_processing survive restart and retain frozen pre-correction source/content/evidence hashes |

`INVENTORY_ASSERTION` preserves distinct symbol, quantity and settlement spans; `PRODUCT_GUARANTEE` preserves both exact clauses and binds only to `alert-position-isolation-v1`. The server re-derives every stored record, requires exact current confirmation, and never initializes inventory from text. The finite grammar and lexical-family boundary are specified in SPEC-source-treatment-review; arbitrary Chinese semantics still require human review.

Independent review found that the initial new acceptance test checked the extraction oracle but not edited current values. That gap was fixed before delivery: every confirmation now follows independent current-value, unit, structure, source-clause and supplement checks. Mutation probes for 970 instead of980, quantity200, ALL→ANY and wrong source attribution must fail before confirmation. Extra conditions, negations, forged quantity/sellability/contract/span, missing clauses/treatments, wrong resolution bindings, stale hashes and stored processing/resolution tampering also have negative coverage. Invalid submissions return422; stored corruption uses secret-free500 INTERNAL_ERROR.

## Automated evidence

- Prior focused v1/v2/provider/parser/review/API chain preserved: **69 passed**. Including 45 new treatment/literal-source/inventory/legacy tests: **114 passed**.
- Current complete backend unit suite: **1,382 passed**, with one existing Starlette `httpx` deprecation warning.
- Current related plan/SQLite/inventory/explicit runtime/transport/alert integration group: **189 passed**.
- The earlier **1,362 unit / 269 integration** results belong to the prior semantic-corpus correction, not this literal-source completion run.
- `ruff check` and `ruff format --check` pass for every changed Python file.
- Earlier R11 evidence remains historical context only: 433 release-gate, 29 legacy explicit runtime/transport, and 684 wider regressions passed at the initial implementation commit. The corrected claim relies on the fresh runs above.
- A best-effort all-tests invocation reached a long-running pre-existing integration segment and was interrupted without a result; it is not counted as evidence.

The frontend type-check still reports the pre-existing R10 alert-union errors in `AlertTable.vue` and `AlertsView.vue`. R11 does not modify or suppress those errors.

Reproduce from `trade-plan-monitor/`: `.venv/Scripts/python.exe -m pytest tests/unit -q`. The 114-case command selects `tests/unit/test_explicit_plan_semantic_corpus.py`, `test_explicit_plan_semantic_acceptance.py`, `test_ai_plan_extraction_v4.py`, `test_explicit_plan_review.py`, `test_source_processing.py`, and integration files `test_explicit_plan_review_api.py`, `test_source_treatment_review_api.py`, `test_source_treatment_inventory_isolation.py`, `test_source_treatment_legacy_compatibility.py`. The 189-case group selects integration files `test_plan_production_composition.py`, `test_sqlite_repositories.py`, `test_explicit_plan_review_api.py`, `test_position_inventory.py`, `test_explicit_transport.py`, `test_explicit_runtime_production.py`, `test_explicit_decision_persistence.py`, `test_alert_production_composition.py`, plus the three new `test_source_treatment_*` integration files. All use `-q`; these groups overlap and their counts must not be summed.

## Release boundary

The public capability remains `publicActivationAvailable=false`. A valid current review is necessary but deliberately insufficient for public activation because the R12 ordinary-plan forms gate is still absent. R12, live AI, import, notification delivery, trade execution, network access, push, and production deployment remain outside this correction.

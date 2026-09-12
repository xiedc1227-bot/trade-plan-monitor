# R13 requirements, scenarios and original findings

Date: 2026-09-13. Baseline `fa316833e8c5d4b427acef4f8500d1e9714a2dd1` plus the protected working tree. Canonical English; paired Chinese review copy: `R13-matrix.zh-CN.md`. Overall verdict: **NOT PASSED**; see [report](../docs/verification/R13-business-acceptance.md).

## M01. Evidence levels and requirement matrix

RUN means executed in this R13 task. STATIC means inspected implementation only. NOT_RUN means no executed evidence for that boundary. A passing simulated-provider case is not actual AI accuracy. A failure-reproduction pass/fail is not business acceptance success.

| ID | Business requirement | Result and level | Principal evidence / limit |
| --- | --- | --- | --- |
| Q01 | Existing natural-language plan enters AI conversion | Implemented, RUN offline | Exact literal JSON fixture, real HTTP adapter/parser and browser; actual provider NOT_RUN. |
| Q02 | Preserve price, quantities, AND, units, timing and missing policies | RUN for literal and case-specific v2 corpus | Original source/hash/mappings plus independent numerical oracle; general language correctness NOT_RUN. |
| Q03 | Ambiguous/unsupported semantics require explicit resolution | RUN bounded rejection | Server `ai/review.py:622` and semantic-v2 cases. Bounded grammar, not a universal semantic prover. |
| Q04 | Source treatment cannot set holdings or waive arbitrary material prose | RUN | `test_source_treatment_review_api.py`, inventory-isolation and compatibility files; literal browser inventory stays UNKNOWN. |
| Q05 | No activation before exact current-content review | RUN | Public capability read plus v3 missing/forged/stale reviewId/contentHash/revision cases; `web/plan_service.py:653`. |
| Q06 | Ordinary price/quantity/logic correction and renewed review | PARTIAL, RUN | Price/quantity re-review succeeds, stale approval rejected409. Logical edit fails; second edits unavailable: N02/F08. |
| Q07 | Active version is read by production scheduler | RUN | MonitorWebComposition → lifecycle → scheduler → production pipeline → coordinator → SymbolService → explicit evaluator. |
| Q08 | Valid completed market data and independent optional-index health | RUN offline | Literal SDK boundary and ten-symbol/market-index/explicit-condition tests. Fresh real data NOT_RUN. |
| Q09 | Inclusive price AND arithmetic mean threshold produces BUY100 | RUN | 24 independent production-pipeline cases plus scheduler browser checkpoints. |
| Q10 | General sellable inventory supports SELL100; five-minute risk has no quantity | RUN | Nine independent sell/risk neighbors and actual scheduler/browser. No legacy episode or daily latch substituted. |
| Q11 | Unknown inventory blocks dependent trades; reminders/read/ack are not fills | RUN | Separate browser registration and acknowledgement; inventory-isolation and T+1 tests. |
| Q12 | Atomic result/state/event/outbox and durable dedup | RUN persistence; delivery incomplete | Rollback/retry/rebuilt production-service tests; N01 rejects actual IN_APP event delivery. |
| Q13 | User-visible reminders, recovery and truthful delivery status | PARTIAL, RUN | Real Chromium visible BUY/SELL/RISK_ALERT and acknowledgement; recovery probes and N01/N04 limits. |
| Q14 | Replacement/disable/expiry fences old work and historical alerts | RUN offline | Three new API lifecycle cases; existing explicit scheduler/commit guards; literal disable10:25. |
| Q15 | Legacy schema/prompt compatibility and approved API contract | RUN gates | Schema1/2, prompts v1–v4, historical mapping hashes; fixed50-path OpenAPI digest. |
| Q16 | Full offline acceptance plus real-interface closure | NOT PASSED / NOT_RUN | Existing browser failures and new P1 findings remain. R14 requires bounded authorization. |

## M02. Original S01–S09 scenario records

### S01 · Price AND volume

- Input: unchanged three-rule plan, separate eight policies, known100/100/max300; price990, preceding volumes[100,100,100,100,600], current200/299/300/301.
- Expected: no BUY at200/299; BUY100 at300/301; unchanged holdings. Both predicates must hold.
- Actual: independent production pipeline agrees; ordinary browser299 gives0 alerts,300 givesBUY100. No median substitution or current-bar inclusion. RUN offline.
- Objects: `decision/explicit_conditions.py:198`, `decision/explicit_rules.py:269`, `runtime/service.py:2440`; `test_r13_independent_oracle.py:30`, browser10:05/10:10 and `lineage.json`.

### S02 · Boundaries and exact equality

- Input: price979/980/981/999/1000/1001 crossed with volume200/299/300/301; sell1079/1080/1081/1099/1100/1101; risk949/950/951.
- Expected: BUY only inclusive980..1000 AND volume>=300; SELL only inclusive1080..1100; risk only949; quantity null for risk.
- Actual: all33 independent numeric cases pass. BUY quantity100 and inventory100 preserved; separate sell/risk tests assert action and quantity. RUN offline; real quotes NOT_RUN.
- Objects: `test_r13_independent_oracle.py:30,144`; `test_explicit_conditions.py:61,100`; `test_explicit_rules.py:283,346`.

### S03 · Unfinished candle temporarily satisfies

- Input: partial10:04 bar with close990 and qualifying intermediate facts; final10:05 close1001; identical deadline retry.
- Expected: no premature completed-bar result; final price invalid, no reminder; retry produces no new result/event.
- Actual: incomplete deadline returns empty, final deadline persists one no-intent result, repeated deadline empty, alert count0. RUN offline.
- Objects: `test_r13_independent_oracle.py:192`; `test_ten_symbol_runtime.py:356`; `runtime/production.py:534`. Initial fake-history recovery failure is harness history, not this result or a waived restart gate.

### S04 · Sell and pure risk

- Input: source SELL100 on completed[1080,1100]; pure risk below950; inventory known100 or independently UNKNOWN for pure risk.
- Expected: exact SELL100 from registered ordinary inventory; RISK_ALERT has no forced quantity, fill, daily-close wait or inventory requirement.
- Actual: browser10:15 SELL100,10:20 RISK_ALERT/null; three acknowledgements leave100. Existing scheduler tests also exercise risk with UNKNOWN inventory. RUN decisions/presentation; mandatory IN_APP fails N01.
- Objects: `test_explicit_runtime_production.py:697,764,817,902`; `test_explicit_rules.py:283,319,346,397`; browser checkpoint/screenshot files.

### S05 · Undefined “企稳、放量” and unsupported semantics

- Input: v2 per-case sources include undefined ambiguous terms, sequencing/unsupported confirmation; provider response is a deterministic fixture, not the oracle itself.
- Expected: no invented deterministic parameters; server-required unresolved/unsupported issues remain and activation cannot be approved by generic acknowledgement.
- Actual: bounded ambiguous/unsupported cases retain blocking issues; each case checks fields, units, structures, source excerpts, unresolved paths and reason fragments. RUN offline corpus and server review; real-model behavior NOT_RUN.
- Objects: `ai/review.py:622`; `test_explicit_plan_semantic_acceptance.py:252,317,323,447,478`; source-treatment API forgery tests. The old lexical20/20 claim remains withdrawn. Safe rejection does not mean unsupported capability is implemented.

### S06 · AI failure, malformed or omitted output

- Input: after ordinary exact-source review and activation of version2, inject invalid JSON, duplicate draft keys, absent draft, HTTP503, truncated finish reason, and omitted risk rule with inconsistent mapping at the AI HTTP boundary.
- Expected: no new executable draft, no activation, no change to previous active pointer/content or inventory.
- Actual: five INVALID_OUTPUT and one PROVIDER_ERROR; draftPlanJson=null; existing active state, planJson and UNKNOWN inventory unchanged. RUN real HTTP adapter/parser/public APIs/SQLite plus browser setup; no business API mocking.
- Objects: `tests/browser/r13_fault_server.py`; `web/tests/e2e/r13-ai-faults.spec.ts`; `ai-faults-evidence.json`; existing v4/parser and server-owned-review tests cover additional shape/budget/forgery boundaries.

### S07 · Stale, unordered, duplicate, disconnected, missing and irrelevant-index data

- Input: missing current response despite cached minute; malformed/partial symbol batches; duplicate/order/future/gap windows; provider blocked/recovery errors; optional-index failures with independent conditions.
- Expected: unknown data never means satisfied; block only dependent symbols/rules; unrelated optional data cannot become a global prerequisite.
- Actual: shared production acquisition and scoped-health regression tests cover each listed bad-data class; explicit windows reject gaps/order/future/mixed symbols and accept documented calendar adjacency. Main browser still emits explicit reminders with unrelated index unavailable. RUN offline boundaries. Provider-network disconnect NOT_RUN; browser reconnect evidence is recorded separately.
- Additional RUN: `web/tests/e2e/r13-live-stream.spec.ts` holds the real alert page open, displays BUY automatically, disconnects the browser while SELL commits, reconnects and displays SELL, then risk, without manual refresh. All acknowledgements leave inventory100. See `stream-evidence.json`/`stream.png`; supplier-network failure remains NOT_RUN.
- Objects: `test_ten_symbol_runtime.py:388,435,505,587,673,853,887,922,1840,1970,2172`; `test_explicit_conditions.py:125,147,200`; `test_live_pipeline_acceptance.py:1282` and index-path tests.

### S08 · Retry, reconstructed service, acknowledgements and inventory

- Input: retry the same evaluation; inject second-enqueue failure; close and reconstruct production pipeline/controller, recover SQLite, replay target; acknowledge displayed reminders.
- Expected: atomic rollback and stable event identity; no duplicate reminder or implicit holdings mutation after rebuild/read/ack.
- Actual: persistence and rebuilt-production-service tests assert one original event, no new ALERT_CREATED on retry and unchanged inventory; browser acknowledgements leave100. RUN rebuilt service, not just a variable alias. Full installed OS-process browser gate is FAILED (N04) and does not certify active-process restart. IN_APP delivery retries fail N01; exactly-once external receipt is not claimed.
- Objects: `test_explicit_runtime_production.py:976` closes controller and constructs a new pipeline/runtime generation, then startup recovery; `test_explicit_decision_persistence.py:181,228,263`; `test_ten_symbol_runtime.py:2300`; browser acknowledgements and `lineage.json`.

### S09 · Replacement, disable and expiry

- Input: replace active plan during work; disable current plan; move market date beyond TRADING_DAY; query retained old event; browser disable then advance10:25.
- Expected: old plan produces no newly eligible action; old reminder remains historical and currentActionable=false; stale commit revisions fail.
- Actual: existing production/commit-fence tests reject invalid/replaced work. All three new lifecycle/API cases return one retained old event with currentActionable=false. Browser keeps three old events, no fourth after disable. RUN offline; no claim about actual supplier-driven expiry.
- Objects: `domain/plan_models.py:162`; `notifications/outbox.py:290,331`; `test_r13_independent_oracle.py:99`; `test_explicit_runtime_production.py:1143,1216,1340,1362`; `test_live_pipeline_acceptance.py:886`; `test_ten_symbol_runtime.py:1612,1702`.

## M03. F01–F09 disposition

| Original finding | R13 disposition | Specific closure evidence / residual |
| --- | --- | --- |
| F01 P0 expired buy | Closed for tested offline validity contract | Production target eligibility and commit fences, explicit ineligible deadlines, API expiry history false. No P0 counterexample reproduced. |
| F02 P1 alert cursor recovery | Original recovery defect closed offline; overall delivery remains partial | Two original recovery variants and actual unmocked-API browser disconnect/reconnect pass; useMonitorStream invalidates alerts after snapshot. Schema3 IN_APP defect N01 is a separate confirmed consumer gap. |
| F03 P1 provenance/review bypass | Server review bypass closed within the approved bounded contract | Required issues, exact hashes/current review, source treatments and stale/forged requests checked. Human semantic review remains necessary; arbitrary language or actual-model accuracy is not certified. |
| F04 P1 edits retain review | Closed for invalidation; correction completion partial | Price/quantity/logic each reset current review; old review409. N02 prevents ordinary logic re-review and repeated edits, without allowing stale activation. |
| F05 P1 no manual-risk input | Closed for tested offline declared-input path | Persistent public input, scope/date/revision/restart tests; dedicated normal symbol-page confirmation passes. Missing undeclared manual risk does not block original explicit plan. |
| F06 P1 source unexpressible | Core bounded operators implemented and RUN; full product acceptance withheld | Exact mean, inclusive ranges, ordinary SELL, pure five-minute risk run through production/browser. Unsupported semantics remain blocked; N01/N02 remain. |
| F07 P1 optional branch promoted globally | Closed for reproduced ALL/ANY regression | `test_decision_engine.py:5291` tests satisfied ANY volume alternatives without hidden structural blockers; explicit ALL numeric oracle passes. |
| F08 P1 ordinary corrections require technical editing | **OPEN** | Literal policies can be supplemented; price/quantity first correction works. ALL/ANY cannot complete review and USER_SUPPLEMENT fields cannot be edited again; N02. Technical enum/path labels also remain visible. |
| F09 P2 unversioned prompt drift | Closed for frozen-version gate | Old prompt/schema golden hashes and current generated/OpenAPI checks run; v4 remains separate. No old expected digest changed. |

## M04. Evidence ownership and residual levels

The original full-backend collection predates R13-added tests; its results and R13 regressions must not be summed as independent broad passes. Final per-command results, skip/deselect reasons and times are in `evidence/R13/commands.json`. `backend.xml` and `r13-regressions.xml` retain individual outcomes. `matrix-evidence.json` extracts scenario-relevant existing test outcomes from the final full run.

Production backend numeric/lifecycle evidence uses trusted isolated fixtures where stated. Only the explicit SQLite browser journeys claim unseeded ordinary business creation and public activation. The semantic-v2 corpus does not call an actual model. Browser screenshots prove displayed content at captured states; read/ack do not prove a trade. R14 actual interfaces, quota/cost and market-window branches remain NOT_RUN. Required failures are preserved as ordinary failing tests, without xfail, skip, threshold changes or business fixes.

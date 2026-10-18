# Generic plan inheritance verification

> **Semantic correction — 2026-10-17:** the fourth source excludes new positions from the old stop; it does not authorize whole-rule cancellation. The reviewer feedback used below was overbroad. This document records historical results, not acceptance of that cancellation. See the [risk scope audit](2026-10-17-risk-scope-audit.md) for the repaired validation and remaining scoped-execution limitation.

## GI-V01 — Status and acceptance boundary

The general extraction/merge fixes and source review are complete. Four actual sources now form a newly reviewed predecessor chain, and its fresh continuous replay completed with verified audit evidence (GI-V05). The running service and published production results have not been replaced.

The user explicitly authorized originals, reviewed predecessor strategies, previous unapproved candidates and correction diagnostics to the configured official `api.deepseek.com` endpoint (`deepseek-flash`). The earlier authorization blocker is resolved. No model response was edited into a passing plan. Source 3 and source 4 required reviewer-supplied semantic diagnoses followed by real model correction; this is **review-assisted acceptance**, not proof of fully autonomous interpretation or first-call success. Whole-plan review remains required.

## GI-V02 — General behavior implemented

- New successors request `monitor-loop-delta-wire-v3`: source-cited changes against the exact reviewed predecessor. Unmentioned values and provenance survive; equal values become retention. Historical frozen inputs retain their original contract.
- Explicit cancellation takes effect before final rule-count validation. Evidence indexes are remapped to surviving identities. A removed entry plus two new tranches no longer fails because an intermediate list contains three rules.
- Clause groups preserve complete source coverage, individual exceptions and explicit paths. Only uniquely resolvable missing collection indexes are normalized. Invalid identities/paths, empty mutations and invalid ambiguity references have separate processing diagnostics.
- Corrections carry previous unapproved proposals and classifications as untrusted data. At most two automatic corrections share the three-physical-call source-revision limit; cancellation, unknown outcomes and admission ownership still apply. Genuine ambiguity is not retried into a guessed answer.
- Authority distinguishes a concrete conditional transaction from a request to formulate another plan or decide whether to trade. Temporal intent requires `DAILY_PRIOR_CLOSE` for an earlier-session stage and `AFTER_RULE_COMPLETED` for later tranches. Unknown qualitative conditions stay unknown; optional suggestions are not mandatory predicates.
- Private `source-clause-pool-v2` deduplicates exact clause evidence and repeated path/ID lists. Round trips preserve the semantic candidate and provenance. Expansion stays bounded by 1 MiB; provider byte/node limits are unchanged. Old uncompressed/v1 candidates remain readable. Invalid references, expansion bombs and malformed storage shapes are rejected.
- Current-source scalar changes cannot hide behind inherited evidence. Truly ambiguous targets leave the reviewed policy unchanged (apart from the successor version number) and produce a confirmation item. Account facts never reset a later continuous ledger.

## GI-V03 — Regression and differently worded cases

- Full unit suite: **3275 passed**, including the four final malformed-input regressions. One existing Starlette deprecation warning remains. A separate in-memory mutation inverted the storage-reference guard; the round-trip regression failed as expected. Source files were not mutated.
- Final focused preparation/library/review/worker/API and live-response replay suite: **244 passed**; two additional live-authority cases passed separately. Generated types match both OpenAPI profiles. Four preparation UI files: **139 passed**; frontend type check passed. A preceding run using the shared Windows pytest temporary root had fixture setup permission errors; a dedicated workspace temporary directory resolved them.
- Six real paraphrases cover maximum holdings 300→500, first-order quantity 100→200, cancellation, negative cancellation, adding a non-trading alert and a genuinely unspecified cancellation target. The first five preserve all unrelated policy; the sixth remains unresolved without guessing. These responses were replayed unchanged after generic decoder fixes, so this is not a claim that all six initial live submissions passed.
- Two fresh v3 cases distinguish a conditional 100-share entry after an earlier close and a later explicitly specified daily low from a notification to reassess an undecided entry. The conditional case passed one call; the assessment-only case passed after one automatic correction. Both retain predecessor risk controls and the 300-share cap.
- An exploratory retest case without an explicit OHLC field produced a close-based range. It was not accepted as proof of low-price semantics. The explicit-low case is a separate new source, not an edit of a model response or of the actual four originals.
- Checked-in unedited response fixtures: `generic-live-four-plan-chain.json`, `generic-live-paraphrases.json`, `generic-live-authority-cases.json`. Tests verify actual prices, quantities, authority, cancellation, temporal order and unchanged provenance, not only schema readiness.

## GI-V04 — Four actual sources and review lineage

Effective dates are 2026-09-24, 2026-09-28, 2026-09-30 and 2026-10-09. Only the four TXT plans are used; `plans.json` and `entry-fields.json` are not plans. Inputs retain the previously checked earlier-source maximum-position/full-exit quotations and the user's separately labelled `RESUME_FIRST_CLOSE` confirmation. Funding is `POSITION_LIMIT_ONLY`; the first source establishes zero shares, and later descriptions do not reset the account.

| Source | Accepted interpretation | Unedited accepted response |
| --- | --- | --- |
| 1 | Maximum 300; conditional first 100; computable two nondecreasing closes remain a typed alternative; unquantified candle/volume criteria stay unknown. Below-line entry cancellation is an alert, not a fabricated sale. | `generic-live-final/http-response-1-2.json` |
| 2 | Cancel the old entry, keep low-buy inactive, pressure 26.40–26.70. Reclaiming 25.99 alone is a reminder. Preserve full exit with both targets zero and the confirmed suspension policy. | `generic-chain/http-response-2-2.json` |
| 3 | Retain source 2's complete exit branch; add conditional first 100 after an earlier close ≥25.99 and a later 25.50–26.00 retest. Keep unquantified rebound, volume and relative-strength predicates unknown. | `generic-reviewed-chain/http-response-3-1.json` |
| 4 | Modify the same first-tranche identity to a prior close >25.99 and later 25.70–26.00 retest; add second 100 after the first completes. Remove the old line-based exit and clear its risk-line fields. Do not mandate optional volume suggestions or invent a final 100-share purchase. | `generic-verified-chain/http-response-4-2.json` |

All folder names above have the prefix `2026-10-17-` under `data/verification/`. Root and second accepted sessions each replayed one prior unchanged response before a fresh correction. Third and fourth sessions used authorized reviewer diagnostics about omitted entry authority, order, optional conditions and risk demotion. Fourth then completed one automatic coverage correction. Earlier failed experiments remain in `2026-10-17-generic-*`; HTTP 200 is not counted as semantic acceptance.

Approved IDs are `generic-live-final-20261017-1`, `generic-chain-20261017-2`, `generic-reviewed-chain-20261017-3`, `generic-verified-chain-20261017-4`. Combined manifest: `2e16f05f193c641c8900919ba635b5bc7a8ece15e1406b7301b9af857457bf2c`. The chain uses exact predecessor hashes and the ordinary extraction, materialization, review and composition boundaries. No per-source candidate-field overrides were used.

## GI-V05 — Continuous replay and remaining limits

Fresh replay completed for 2026-09-24 through 2026-10-09 using the already frozen actual market store and the new reviewed chain. Evidence: `data/verification/2026-10-17-generic-verified-chain/continuous-summary.json`, `continuous-audit.ndjson`, `completed-job.json`, `diagnostics.json` and `diagnostics-verification.json`.

- Run ID: `b9c937a72b2bf572000c6402321f1e9516e0036ee7f3304f4358466eab888741`.
- Report hash: `8a7ea022c843627419f6d02052b085fb3008e94df7059c5dcab0f421bb98871b`.
- **1468 evaluations, 2961 verified events, 3 plan replacements, 6 reminders, 0 intents and 0 fills.** All four reviews passed, with buy-rule counts **1 / 0 / 1 / 2** and no extraction/validation processing-error category.
- Exact predecessor hashes and replacements on 09-28, 09-30 and 10-09 were verified. One position-limit-only account stays at zero shares; no cash cap or invented capital return. Return, equity and drawdown metrics remain unavailable by design in this funding mode.
- Two midnight evaluations retain `PRICE_BASIS_UNVERIFIED` because the current-session factor was not yet available. All such blockers are at midnight; trading-session daily comparisons are admitted. Source 3's bounded example list is sampled; the full audit is retained.

| Source | Verified no-fill evidence |
| --- | --- |
| 1 | 09-24 close 25.69 versus required >26.70; consecutive closes 26.62→25.69 fail the nondecreasing alternative. Qualitative candle/volume criteria also remain unknown. |
| 2 | Old BUY explicitly cancelled; no new direct entry authorization. Latest closes 24.44 and 25.05 do not turn the observation/reevaluation instructions into buys. |
| 3 | Required earlier close ≥25.99 is absent; available prior close is 25.01 on 10-08's evaluation. Retest lows 24.82 (09-30) and 24.86 (10-08) are outside 25.50–26.00. Qualitative rebound/volume/index criteria remain unknown. |
| 4 | No earlier qualifying close >25.99 within the new plan window; 10-09 close 25.35 is not an earlier-session confirmation. Low 24.36 is outside 25.70–26.00. Second tranche also lacks the earlier >26.40 prerequisite and completed first tranche. Retest/hold descriptions remain unquantified. |

These unmet numeric prerequisites independently prevent entry in this interval. The remaining qualitative unknowns are disclosed separately; zero fills are not being attributed solely to AI failure or solely to unquantified language.

Passing extraction checks cannot guarantee that a probabilistic model understood every source clause. In particular, qualitative rebound/volume/relative-strength descriptions remain unquantified. Unknowns do not authorize fills, and a zero-fill result must distinguish unmet prices from these unknown conditions. This work does not certify returns. The subsequent local service restart and browser check are recorded in GI-V06.


## GI-V06 — Local restart and browser verification

On 2026-10-17, rebuilt the frontend and started the updated local service at `http://127.0.0.1:8765`. Backed up the existing databases and appended this verified run to `data/backtest-results.sqlite3` through the normal verified-publication boundary; existing results were preserved. No new AI calls or replay were needed for this display check.

Opened `/backtests/b9c937a72b2bf572000c6402321f1e9516e0036ee7f3304f4358466eab888741?tab=summary` in the actual browser. Initial preparation entered `DEGRADED` and returned 503; explicit service retries recovered to `READ_READY` at generation 2. The initial exception was not exposed by the service, so its root cause is not established. A separate local composition check completed in 0.14 seconds. After recovery, the result and event details rendered successfully. A concurrent extra result request was rejected while a metadata query was occupied; the later sequential result request returned 200. No console warnings/errors were captured.

- The served report hash matches GI-V05. The four source IDs, dates and frozen versions match the verified chain; each later `baseHash` equals the immediately preceding `candidateHash`.
- All four diagnostic panels show passed review with no extraction/validation blockers. Numeric comparisons match GI-V05, including the distinction between the prior close 25.01 and latest price 25.14, and fourth-source low 24.36 versus 25.70–26.00. Qualitative unknowns and midnight-only data limitations remain separate.
- The browser shows 1468 evaluations and zero fills, the four-version calendar and the first page of causal event details. This check did not manually paginate all 2961 events; three replacements were verified in the retained replay audit.
- Display limitation: the result page shows the version calendar and execution details, not the complete retained/modified/added/revoked rule comparison. That comparison belongs to preparation review. This check does not claim that it is already displayed on the result page.

Evidence under `data/verification/2026-10-17-generic-verified-chain/`: `web-publication.json`, `web-run-response.json`, `web-summary-dom.txt`, `web-details-dom.txt`, `web-diagnostics.png`, `web-diagnostics-plan3.png`, `web-diagnostics-plan4.png`, and `web-restart.*.log`. The result tab was left open for the user.

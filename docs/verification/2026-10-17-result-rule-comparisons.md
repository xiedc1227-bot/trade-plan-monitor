# Continuous result rule comparison verification — 2026-10-17

> **Semantic correction — 2026-10-17:** the displayed fourth-source cancellation accurately reproduces the old frozen policy, but the policy overinterpreted a new-position exclusion as whole-rule cancellation. The checks below prove display fidelity only. See the [risk scope audit](2026-10-17-risk-scope-audit.md); no corrected continuous replay has been published.

## RC-V01 — Scope and immutable evidence

The updated local service displays complete retained/modified/added/revoked comparisons on the continuous result summary. This check uses the four actual reviewed plans and their final frozen executable policies. It does not call AI, change reviews, or repeat the simulation.

- Run: `b9c937a72b2bf572000c6402321f1e9516e0036ee7f3304f4358466eab888741`.
- Manifest: `2e16f05f193c641c8900919ba635b5bc7a8ece15e1406b7301b9af857457bf2c`.
- Report: `8a7ea022c843627419f6d02052b085fb3008e94df7059c5dcab0f421bb98871b`.
- URL: `http://127.0.0.1:8765/backtests/b9c937a72b2bf572000c6402321f1e9516e0036ee7f3304f4358466eab888741?tab=summary`.

The four live endpoint responses equal the expected frozen comparisons field for field. The full run response also equals the earlier saved response: **1468 evaluations, 0 intents, 0 fills**, with unchanged report and diagnostics. Individual comparison reads took 2.363–3.027 seconds in this check.

## RC-V02 — Four-source findings

Counts include policy sections and individual rules, not just order rules.

| Effective date | RETAIN | MODIFY | ADD | REVOKE | Verified content |
| --- | ---: | ---: | ---: | ---: | --- |
| 2026-09-24 | 0 | 0 | 11 | 0 | Initial rules, maximum 300 shares and conditional first 100 shares. |
| 2026-09-28 | 9 | 1 | 2 | 1 | Cancelled `first-tranche-100`; added ordinary full exit and reassessment alert. Core/tactical exit targets are both zero. |
| 2026-09-30 | 10 | 2 | 2 | 0 | Retained ordinary full exit, including first-resumption-close confirmation; added first-entry retest rule. |
| 2026-10-09 | 9 | 4 | 1 | 1 | First-entry low range changes 25.50–26.00 to 25.70–26.00; prior close changes ≥25.99 to >25.99 with a new start date; added second 100 shares after the first rule completes; cancelled the old ordinary exit. |

The browser was used to load each source and expand the third source's retained group. Previous/current values, unchanged fields within modified rules, cancelled content, fixed-price references in yuan, predecessor labels and all four classifications were inspected. The previous display gap recorded in GI-V06 is resolved. Existing no-fill evidence remains visible above the comparisons.

## RC-V03 — Regression and boundaries

Final backend verification passed **52 tests** across `test_result_rule_changes.py`, `test_monitor_loop_result_api.py`, `test_monitor_loop_contract.py`, `test_openapi_snapshot.py` and `test_generic_live_four_plan_chain.py` (151.91 seconds). The replay fixture exceeded the 45-second diagnostic threshold but completed successfully; it was not a failed assertion. Ruff and diff whitespace checks passed.

Coverage includes stable rule identity despite reorder, 300→500 position changes, endpoint binding and missing-source 404s, independence from the mutable preparation reader, offline replay of saved real AI responses, stale frontend responses, explicit retries, escaped source text, independent legacy labels, yuan conversion, and removal of redundant parent rows when nested fields are removed. Type checking and the production build passed. The full frontend suite passed 69 files / 1062 tests before the final additional checks; the final two focused component files passed 8 tests.

English/Chinese specification U20, operation ML-O17, task RC-01–RC-03 and this report are updated together. Read-only comparison supports the collection's variable source count; it is not special-cased to these four plans. Qualitative conditions remain unknown where the frozen plan has no reviewed definition.

## RC-V04 — Evidence files

Evidence root: `data/verification/2026-10-17-generic-verified-chain/`.

- `web-rule-comparison-expected-1.json` through `web-rule-comparison-expected-4.json`: projections of frozen policies.
- `web-rule-comparison-served-1.json` through `web-rule-comparison-served-4.json`: actual local API responses.
- `web-rule-comparison-verification.json`: equality, counts, durations and unchanged result assertion.
- `web-rule-comparison-dom.txt`, `web-rule-comparison-plan4.png`, `web-rule-comparison-price-change.png`: browser evidence.
- `web-rules-restart.stdout.log`, `web-rules-restart.stderr.log`: updated service startup.

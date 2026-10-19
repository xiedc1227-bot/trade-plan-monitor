# Automatic backtest data verification — 2026-10-18

Chinese copy: [2026-10-18-automatic-backtest-data.zh-CN.md](2026-10-18-automatic-backtest-data.zh-CN.md). Scope: [AD-01–AD-03](../../tasks/automatic-backtest-data.md), [U25](../specifications/monitoring/SPEC-unified-plan.md#u25-automatic-data-preparation-at-start-2026-10-18).

## AD-V01 — Implemented behavior

The history-data page no longer contains the four manual URL/sync/verification/cache-refresh controls or the scope form. It remains read-only with dataset filters, paging and task inspection/cancellation. Reviewed-source start automatically checks server-derived requirements, conditionally submits the existing durable sync job, follows progress, verifies again and admits replay. It uses the existing worker/admission/physical-drain boundaries, not another worker or an unbounded task queue. The data check has no execution/network authority. Final run admission still rechecks and freezes the exact reviewed manifest, boundary, account and evidence.

Valid cache causes no download. Missing data uses `allowNetwork: true` and `refresh: false`. Uncertain sync receipts preserve the original body/key before any retry; cancellation remains effective across receipt recovery and late completion. A rejected cancellation can be explicitly retried. Failed verification never starts replay, and a new explicit attempt checks already downloaded cache again. Leaving aborts reads and prevents follow-on commands, while an accepted server job remains accessible by its record; reloading does not silently continue it.

The actual trial exposed that report-owned frozen market copies were complete while mutable cache lacked minutes/limits. The generic repair now searches at most 20 matching first-plan inputs and requires matching schedule/review/account/requirements, coverage and exact cutoff, verifying every copied day/artifact hash. It binds a new submission/input/dataset to the new run without rewriting old objects. Different cutoffs cannot reuse the copy. This is generic cache reuse, not a four-plan data patch; no original text or reviewed rule was changed.

## AD-V02 — Regression and browser evidence

| Check | Result |
| --- | --- |
| Full frontend | 73 files / 1112 passed |
| Related backend: automatic checks, submission, input copies, datasets, sync, market storage, thread ownership, composition, data/run/service APIs and OpenAPI | 259 passed, 1 expected platform skip |
| Frontend type checking / production build | Passed |
| Both generated contract checks / changed Python lint | Passed |
| Existing actual-backend Chrome extraction/review/run and unknown-cancellation journeys | 2 passed |
| Missing-history Chrome journey through real sync worker, second check and full-day replay | 1 passed; 53.7 seconds |

The browser missing-data journey verifies no provider call before start, check outcomes false then true, exactly one sync and one run submission, progress/cancel visibility and no manual verification command. It uses a deterministic provider behind the production sync worker and preserves the whole 240-minute day. The previous 30-second result visibility wait expired at 212/244 events; the observer now allows the full day to finish. This is not a live Tushare certification. Obsolete manual-control tests were replaced by read-only-page/no-download/filter tests; automatic submission/cancellation/retry coverage lives in the new controller suite. Existing frozen-plan command, account and exact-cost assertions remain.

The cancellation mutation experiment deliberately reset cancellation during uncertain-receipt retry. The regression failed as expected, and exact source bytes were restored. Local logs/captures live under `data/verification/2026-10-18-automatic-data/`, including `frontend-accepted.log`, `backend-accepted.log`, `cache-final.log`, `cancellation-mutation.log`, `type-check.log`, `build.log`, `browser-focused/` and `browser-missing-final.log`. No raw source, configuration, credentials, screenshots or generated reports are added to Git.

## AD-V03 — Four actual plans

Actual continuous replay completed with 1468/1468 events. The accepted run is `5f64cdab2e88e76acdf78de0a3525e3ba09104158688ee66b41a93d61116497d`, with source dates `2026-09-24`, `2026-09-28`, `2026-09-30`, `2026-10-09`. All four original-source hashes match the protected baseline; the existing reviewed predecessor chain was used without another extraction or rule edit. The data check returned ready, automatically reusing the verified market copy, with no new download or AI request and exactly one final run submission.

The result page shows the four effective dates, predecessor comparisons, per-plan diagnostics and actual/required prices, 0 fills and 0.00 yuan total/realized/unrealized PnL through `2026-10-09`. The existing unquantified-rule and valuation limitations remain visible; this change does not reinterpret trading conditions to manufacture fills. The protected report `9050185da63d7961aa29228542fa024d127ac4d754af10e3066cbc26e09abeb2` is equal to its saved full API response, and all 47 saved input/day/artifact file hashes are unchanged. Completion inspection made no writes and recorded no browser page errors. The four-plan cached-data path and the separate missing-data worker/browser path together passed the scoped acceptance.

Local evidence includes `actual-verification.json`, `actual-four-plan-result.json`, `actual-four-plan-result.png`, `actual-completion2.log`, `baseline-run.json` and `baseline-artifacts.json` in the ignored verification directory. The start observer timed out while the accepted task was still running; completion was subsequently checked read-only, without restarting or resubmitting that task. During concurrent post-completion reads, one observation encountered temporary 503 responses; the existing read-only retry restored the result page. This is not a claim that result reads never return 503.

## AD-V04 — Limits and diagnosis retained

Follow-up: the post-completion 503 recorded in AD-V03 has a reproduced root cause and verified repair in [RR-V01–RR-V04](2026-10-18-result-read-isolation.md). Repeated expensive result verification blocked the shared metadata owner. The result read now verifies once in its own bounded owner and shares only overlapping identical work. All historical observations below remain part of the original verification record.

The first actual attempt found missing mutable cache and its automatic sync failed with the existing generic worker failure. It did not start replay or rewrite an old report. Diagnosis found an exact verified report-owned copy; generic reuse fixed this unnecessary dependency on downloading again. A synthetic provider-configuration stub also initially missed a timeout attribute and was corrected. Initial browser helpers encountered Chrome response-body retrieval errors, navigation before listener readiness and a cold-library read; those are retained as failed checks, not counted as successful acceptance. The start observer's 300-second limit is separate from worker completion; observation does not cancel/restart/resubmit the accepted job.

Historical API authority, cutoff defaults and old reports remain compatible. Unpublished current-day data, insufficient/provider-restricted historical data, damaged stored evidence, persistent service faults and genuinely unquantified source rules still fail explicitly; no invented facts, automatic AI or manual trade-rule supplement is used to mask them. Existing data retention/maintenance and the old functional-acceptance limits remain. The whole historical browser/capacity suite and a new paid AI/live-provider certification are outside this verification.

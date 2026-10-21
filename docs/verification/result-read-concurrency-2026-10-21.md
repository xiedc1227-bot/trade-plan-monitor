# Result-read concurrency verification

Date: 2026-10-21. Baseline: `cd5113b8bb92dabd2b6b133102e0751198dfd807`. Contract: [RRC specification](../specifications/backtesting/SPEC-result-read-concurrency.md). [Chinese review copy](result-read-concurrency-2026-10-21.zh-CN.md). Raw observations: [measurements.json](evidence/2026-10-21-result-read-concurrency/measurements.json).

## RRC-V01. Delivered scope

- P0: `LoopInputStore._read` requests at most 65,536 bytes at a time and continues after short reads, retaining the existing total limit, domain hash, root/link checks and all typed/canonical/binding/event-set verification.
- P0: the runtime root treats resolved backtest routes as one navigation surface. Initial route normalization, result tabs, list filters, history navigation and data browsing add no monitor refresh. Meaningful monitor navigation still refreshes and first withdraws obsolete actionable presentation. Expiry, heartbeat, reconnect, protocol checks and command preflight remain enabled.
- P1: historical index heads and payloads use one left-joined SELECT with 128-row ORM fetch batches. Every historical candidate still passes `_market_index_from_row`; missing payloads fail. Head/payload identity is checked before the existing verified `snapshot_rank` chooses a winner. Existing identities in the session are refreshed from the read snapshot.
- No schema/API migration, evidence rewrite, retention change, provider download, job submission/resume, new cache, timeout increase or extra worker was introduced. Existing edits and historical records are retained. The user subsequently authorized review, commit and push.

## RRC-V02. Comparable projection measurements

Windows, Python 3.14.7 with GIL enabled; same completed 39-day / 2,961-event run. SQLite measurement connections use `mode=ro` and `PRAGMA query_only=ON`. Warm paths alternate in one process against the same data. Complete response objects, including all diagnostics and identities, are compared for equality. The original method is extracted from `git show cd5113b:src/trade_plan_monitor/backtest/loop_input_store.py` and substituted only in the measurement process; the candidate is the implemented reader. These are local observations, not an SLA or p95.

| Full verified projection, seconds | Baseline | P0 |
|---|---:|---:|
| Round 1 | 4.2015 | 2.2295 |
| Round 2 | 4.2784 | 2.1791 |
| Round 3 | 4.9404 | 2.2030 |
| Median | 4.2784 | 2.2030 |

Median improves 48.5%, meeting the sample gate of at most 2.5 seconds and at least 30% improvement. CPU medians are 4.2500 → 2.1719 seconds. Complete responses match; `reportHash` remains `8a7ea022c843627419f6d02052b085fb3008e94df7059c5dcab0f421bb98871b`.

For the same 506-byte file, peak traced Python allocation is 295,242,058 → 198,540 bytes. File bytes and domain digest match. This is an isolated Python allocation measurement, not process RSS or total request memory. A genuinely large artifact can still occupy its allowed bounded size; this change removes giant read requests for tiny artifacts.

## RRC-V03. P1 gate and experiment ledger

After P0, the unchanged monitor path still takes 3.8813 seconds and 1,929 SELECTs for 1,928 candidates / 5 selected snapshots. Both the greater-than-1-second and N+1 gates hold.

| Monitor traversal, seconds | Baseline | Batch only | Batch + primitive fast path |
|---|---:|---:|---:|
| Round 1 | 3.8935 | 3.5305 | 3.6771 |
| Round 2 | 4.0062 | 3.4936 | 3.6571 |
| Round 3 | 3.9677 | 3.5447 | 3.5788 |
| Median | 3.9677 | 3.5305 | 3.6571 |
| SELECTs per traversal | 1,929 | 1 | 1 |

Batching improves the median 11.0%; complete selected records and their five hashes match. Keep batching. Moving exact primitives ahead of typed normalization makes this Decimal-heavy sample slower than batching alone; revert that experiment. `market_index/canonical.py` has no final behavior change. Literal canonical-byte, enum/subclass, Decimal, float rejection and timezone-boundary regression tests are retained.

Defer monitor in-flight sharing and any cache/process split. Navigation amplification is removed (RRC-V05); remaining dashboard/health/heartbeat validation is still expensive. Mixed-read contention remains material, but these observations do not establish safe equivalent authority/data fences for sharing independent monitor calls. Keep post-read authority checks and physical ownership; a separate sharing design needs generation/configuration/committed-data fences, bounded admission, cancellation and drain proofs. This is a measured limit, not a claim that all monitor contention is solved.

## RRC-V04. Real HTTP concurrency measurements

Same local service/configuration and two completed runs; two sequential rounds. GET-only scenarios include a lightweight service probe after 150 ms. Existing WebSocket/health traffic remains active; warm measurements above isolate the changed methods more tightly. The table shows scenario completion, including both observers where relevant.

| Scenario | Baseline seconds, rounds 1 / 2 | After seconds, rounds 1 / 2 |
|---|---|---|
| Single result | 4.789 / 6.127 | 2.254 / 2.210 |
| Same-run pair | 8.445 / 5.202 | 2.091 / 2.070 |
| Different-run pair | 9.074 / 8.461 | 3.819 / 3.895 |
| Result + dashboard | 18.597 / 11.741 | 9.576 / 9.509 |

All result responses return 200 with unchanged report identities. Existing same-run physical sharing, serialized different-run work and observer cancellation remain in place. Cancelling one observer at 0.261 seconds then retrying returns the same report in 5.370 seconds; this retry is slower than the earlier 3.679-second observation under different background contention. Do not interpret cancellation timing as proof of physical cancellation or universal improvement. After-change service probes take 46–186 ms; they are responsiveness samples, not a guarantee under every burst. No business writes occur.

Queue admission/timeout, exact physical execution counts, cancellation isolation and shutdown drain are established by deterministic thread-ownership tests; mutable revision rereads are covered by pinning tests. These are not inferred from HTTP completion timing. Validation CPU, method wall time, allocation and HTTP totals are reported separately; nested profile costs are not added. Process RSS and a production latency distribution were not measured.

## RRC-V05. Browser verification

Chrome for Testing 157.0.8103.6, real local service and historical data, list → result → provenance → summary:

| Observation | Before | After |
|---|---:|---:|
| Result-detail requests | 1 | 1 |
| Dashboard requests | 8 | 1 |
| Aborted dashboard observers | 7 | 0 |
| Result request duration | 29.550 seconds | 9.155 seconds |
| Business writes / page errors | 0 / 0 | 0 / 0 |

The after dashboard request completes in 13.047 seconds. The visible result is faster, but monitor validation/background CPU contention remains. This single journey is not a percentile metric.

The new runtime-root browser regression mounts the real `runtime-status/App.vue`, protocol/store/stream and result/list/data views with strict GET fixtures: initial canonical URL, tabs, back/forward, return, apply/clear filter and data browsing retain one dashboard read; monitor re-entry adds one fresh read. It checks zero writes, page errors, console warnings/errors and unexpected failed requests. Existing browser workspace tests cover 30-record pagination, focus return, version selection, slow reads, timeout/retry, exact equity tables, responsive widths 320/768/1024/1440, 200% font size and accessibility checks. All 8 focused browser cases pass across the final runs.

The local service was restarted with the same configuration only after verifying zero active jobs and physical drain. Read-only checks afterward still find 5 historical results, 8 reviewed sources and 2 timeline roots. No cleanup or migration was performed on these records.

## RRC-V06. Integrity and regression evidence

| Scope | Result |
|---|---|
| Frozen input/publication/retention/thread ownership/workspace reads/result API: 7 integration modules | 81 initially pass; 2 pre-existing fixture initialization failures reproduced with the baseline reader, then repaired and verified below. |
| Full input-store + projection repository + index canonical data modules | 42 pass after initializing the job repository in the two restart fixtures, matching production composition. Original assertions remain; migration checks are unchanged. |
| Bounded reader/index canonical/projection + index overview + runtime projection/routes/WebSocket/composition/official-close + index retention | 113 pass. |
| Final changed reader/canonical/projection modules | 35 pass, including all 130 candidate validations across the 128-row fetch boundary, historical canonical damage/missing payload/head identity mismatch, cutoff ranking over provider revision and display order. |
| `test_backtest_result_pinning.py` | 6 pass: revision changes, exact replay, conflict, expiry and unchanged report identity. |
| Frontend unit suite | 83 files / 1,204 tests pass. |
| Frontend type check and production build | Pass. |
| Focused browser suite | 7 existing workspace cases + 1 new runtime-root case pass. |
| Changed Python lint / whitespace check | Pass. |

Retained coverage includes same-size/same-timestamp tampering after a successful read, short reads, exact size boundaries, truncation/growth/replacement after stat, link/junction rejection before open, damaged report/input/event rows, foreign identities, audit omission/rehash attacks, expired details/events, pin replay/revisions, bounded retention and shared frozen-day preservation. Destructive fixture operations use isolated test storage. No validation was replaced by an mtime/hash-name cache.

A process-local mutation replaces `_market_index_from_row` with JSON decoding that bypasses integrity/canonical checks. The historical canonical-damage case fails with `DID NOT RAISE ProjectionError`, proving that this bypass is caught. The real implementation passes the same case. No production source is changed for the mutation.

Two initial restart failures were `LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION` and also occur with the original baseline reader. The isolated fixtures created a result store without the current job-table initializer. Add `BacktestJobRepository` initialization in those two tests; do not relax the migration preflight or change real storage. Browser harness development also required matching actual link names/current-page attributes and rendering placeholder components without runtime template compilation; the final harness passes strict audits.

The backend emits the existing Starlette/httpx deprecation warning; browser runs emit Node's existing color-environment warning. Neither is suppressed or treated as an application failure. Full repository backend testing was not run; the relevant modules above were run.

## RRC-V07. Reproduction and delivery

From `web/`: `npm run test -- --run --maxWorkers=4`, `npm run type-check`, `npm run build`, `npm run test:e2e -- tests/e2e/backtest-workspace.spec.ts tests/e2e/result-read-concurrency.spec.ts`.

From the project root, run `.venv/Scripts/python.exe -m pytest` on the named modules in RRC-V06 with a new isolated `--basetemp=.pytest_cache/<name>`; run `.venv/Scripts/python.exe -m ruff check` on changed Python files and `git diff --check`. The one-off read-only comparison scripts and detailed profiles remain in `.pytest_cache/result-read-concurrency-20261021/`; portable raw results are included in `measurements.json`. Benchmark results are observational artifacts, not timing assertions in the test suite.

Review confirms no removed integrity gates, altered financial/retention semantics, new API fields or dependencies. Remaining limits are synchronous full historical monitor verification and background CPU contention. Keep these checks; any future sharing/representation work must be measured and separately prove authority and evidence completeness.

## RRC-V08. Pre-push review

The subsequent review covers correctness, readability, module boundaries, evidence safety and performance. No blocking findings remain. The reader still checks the same total size and domain digest; the left join still rejects missing payloads and validates all historical candidates; scoped navigation retains fresh authority on monitor entry. No dependency or migration changes are included.

Pre-push reruns: 70 backend tests across the changed reader/index modules, full input-store module, result-thread ownership and pinning; 83 frontend files / 1,204 tests; all 8 workspace/runtime-root browser cases in one run. All pass. The two corrected restart fixtures pass in the full input-store rerun. Type/build/lint, paired-document identifiers/technical tokens/links, measurement consistency and staged-file scope are also checked before commit. The earlier broader integrity/retention/runtime regressions remain recorded in RRC-V06.

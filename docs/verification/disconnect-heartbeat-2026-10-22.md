# Disconnect-aware heartbeat P0 verification

Date: 2026-10-22. Baseline: `b323840`. [Chinese review copy](disconnect-heartbeat-2026-10-22.zh-CN.md). [Specification](../specifications/backtesting/SPEC-disconnect-aware-heartbeat.md), [tasks](../specifications/backtesting/TASKS-disconnect-aware-heartbeat.md), [portable evidence](evidence/2026-10-22-disconnect-heartbeat-verification/measurements.json).

## DHA-V01. Delivered scope

P0 adds a connection-local supervisor with exactly 1 receive child and 1 send child. A terminal signal prevents further heartbeat admission, replay and sends. Closing a socket cancels its health observer through existing ownership and joins both transport children. Repeated outer cancellation cannot discard child cleanup; original cancellation identity/arguments are preserved for Starlette/AnyIO. Cleanup failures remain failures. Each replay page yields because uncongested sends need not suspend.

Production changes are limited to `src/trade_plan_monitor/web/monitor_connection.py`, `src/trade_plan_monitor/web/websocket.py` and fixed diagnostic stage names in `src/trade_plan_monitor/diagnostics/read_tracing.py`. Two existing fake sockets gain a blocking receive interface; two new integration-test modules exercise the behavior. No frontend product, dependency, codec, database schema, read-owner, authority or proof-validator implementation changes are included.

## DHA-V02. Reproduction and correctness

The initial 18 regression cases on unchanged source produce 17 failures and 1 passing send-failure control. The implementation then passes the focused protocol/ownership/tracing suite. An additional fast-replay regression first reproduces 100 sends before consuming queued disconnect; the per-page checkpoint reduces it to 1 in that fixture. A further case proves that a cancelled health call's cleanup failure is not swallowed. All 20 new cases pass on the frozen candidate.

The temporary stopped-health reader remains owned by its original `finally` stop/drain, even after a second outer cancellation. Shared-proof tests cover leader, follower and all-observer departure with both valid and failed proofs. Surviving observers receive a fully verified result or the original rejection. Storage checkpoint/drain timeout retains its pause, rejects new reads and prevents premature database disposal; successful later cleanup releases only its proper pause. The existing actual checkpoint-failure recovery cases also remain in regression scope.

## DHA-V03. Real browser closure and admission

Both fixed main waves use the unchanged configuration, historical data, protocol and 20-second heartbeat cadence. Each covers 54 pages, 40 direct result reads, 20 received connected-control heartbeat frames, and bounded 2/8-page loads. The main after wave has genuine reconnects on 8 in-flight-closure trial pages: only 12 of its initial 20 trials have an owned read active at browser close. Exactly 12 additional trials were then declared, following the latest actual socket after recovery; all 12 qualify. All initial trials remain in evidence. After coverage is therefore 24 qualified in-flight closures out of 32 raw trials, compared with 20 out of 20 before. This supplement does not enter the original result timing comparison.

| First-heartbeat closure workload | Before | P0 |
|---|---:|---:|
| Pages closed before their first heartbeat | 20 | 20 |
| Heartbeat health attempts starting after browser close | 20 | 0 |
| Snapshot entries for those attempts, including retries | 22 | 0 |
| Sum of those snapshot threads' CPU seconds | 25.71875 | 0 |
| Direct result reads returning HTTP 200 in the main wave | 40 | 40 |
| Page-script errors / business writes | 0 / 0 | 0 / 0 |

The CPU sum counts each owned snapshot span once and does not add nested proof timings. It describes those abandoned-page attempts, not whole-service CPU or a prediction for every workload. Baseline lacks a receive-side terminal observation, so its server-known-close admission metric is unavailable, not zero.

All 74 socket roots from the main after wave and supplement have joined-child completion records. There are 0 health admissions after their observed terminal state. For the 20 first-heartbeat closures, terminal-to-child-drain median is 0.14675 ms, maximum 5.3551 ms. These are server scheduling boundaries, not browser-close detection latency or a universal shutdown SLA.

Already admitted physical work is deliberately separate. The 24 qualified in-flight closures record observer cancellation while owned reads can finish after the socket root. The maximum observed continuation is 3.5211112 seconds. This is retained physical ownership/cooperative unwind, not another newly admitted heartbeat or a successful partially verified response.

## DHA-V04. Result observations and remaining failures

All 80 direct result responses from the two main waves are HTTP 200 and have the same complete response hash. Timing is observational across actual-owner generations and background activity; it is not a controlled causal speedup claim.

| Main-wave result scope, 20 samples each | Before median / range seconds | P0 median / range seconds |
|---|---|---|
| Independently issued reads | 2.353 / 2.176–5.132 | 2.205 / 2.053–4.776 |
| Reads with connected monitor clients | 2.424 / 2.217–5.778 | 2.347 / 2.030–6.502 |

The mixed maximum increases despite the lower median; tail variability remains. Each wave retains 7 HTTP 503s separately: 5 dashboard and 2 job-list requests. These are protected admission failures, not fast successes. Bounds, waits and verification are not weakened to hide them. The supplemental browser run has 0 console/page errors and 0 business writes.

## DHA-V05. Authority and evidence invariants

The complete source hashes of `MonitorReadOwner`, `RuntimeStatusReadService`, `IndexEvidenceFlights` and `src/trade_plan_monitor/state/projections.py` match the before lock. Every successful connected owned read in the correlated traces has independent matching before/after authority-span counts. Per-read clocks/BEGIN snapshots, activation reread, plan/inventory/risk/calendar/evidence checks, the original 2-attempt budget, 8-read / 15-second cooperative waits, 1 physical validator / 1 distinct queued owner, 64 MiB retention and in-flight-only exact-input sharing remain intact.

Cancelled work may terminate at an existing checkpoint without returning a response; it never certifies a partial proof. No completed-health/proof cache, forced thread cancellation or early resource release is added. Integrity/retention/time-boundary tests remain on the original validators. Process-local mutations kill 5 new-boundary defects and 8 existing integrity/authority defects: admission guard, observer cancellation, child joining, cancellation identity, replay fairness; decoder envelope, canonical equality, event hash, set identity/count/hash, length prefix and authority token. Production files are not mutated for these probes.

## DHA-V06. Overhead, control noise and allocations

The first fixed 20 alternating rounds fail the overhead target: wall median 2.1765525 → 2.2941853 seconds (+5.40%), CPU 2.125 → 2.2578125 seconds (+6.25%). These samples are retained. A common timing step begins around round 11; median paired CPU difference is 0. The 6 instrumented attribution samples place most variation inside the unchanged snapshot worker; they are excluded from timing acceptance and do not uniquely identify hardware, scheduling or GC as the cause.

One prospective confirmation was fixed before its collection: exactly 10 A/A pairs followed by 20 ABBA/BAAB blocks, with no further extension. A/A CPU pair differences range from -7.78% to +15.57%, showing that the environment is noisy. The balanced comparison contains 40 before and 40 after reads; its wall medians are 2.6916485 → 2.69103075 seconds (-0.023%), CPU medians are both 2.6484375 seconds (0.00%). Paired-block median differences are -0.387% wall / -0.678% CPU. The confirmation point estimates meet the unchanged <=5% wall / <=2% CPU targets. This does not establish zero overhead or a tight confidence bound, and it does not erase the initial failed result.

All complete frozen heartbeat frames match. These measurements use a read-only 2008-candidate monitor copy, fixed clock and synthetic absent-owner authority, with an accelerated fixture clock and outer observer cancellation. They measure a complete validated read plus transport cleanup in isolation; they are not actual-owner/browser acceptance or real heartbeat cadence timings. The A/A controls and initial/confirmation designs remain separate, not selectively pooled to obtain a pass.

Separate 3-process allocation observations per variant show median Python allocation peaks of 42,889,248 → 42,895,625 bytes, an increase of 6,377 bytes (about 0.015%). Their profiled timings are excluded from overhead acceptance. This is Python allocation peak, not whole-process RSS or the validator's separate retained-evidence byte counter.

## DHA-V07. Final tests and browser checks

- Final backend: 460 passed, 1 existing Windows/POSIX ownership skip, 1 existing Starlette deprecation warning in 434.97 seconds.
- Final focused protocol/ownership/tracing run: 54 passed; the final 20 new cases also pass independently. The earlier broad candidate run has 459 passed / 1 existing Windows skip; the frozen-source final broad result above supersedes it.
- Browser regression: 25 passed in 1.3 minutes, including dashboard authority, responsive/accessibility boundaries, sequence-gap recovery, stream completion/caller cancellation and backtest flows. Type checking passes. Source/fixture changes to the parallel daily-inventory UI are outside P0 scope.
- Native page confirmation: provenance/summary switching, result refresh and return to monitor succeed; initial/refreshed results and dashboard are HTTP 200, monitor is RUNNING/STANDBY, with 0 script/console errors and 0 writes. Screenshots were inspected. This last confirmation uses a later non-tracing instance, so it does not claim fresh physical trace IDs; the fixed measurement waves retain their own original correlations.
- Scoped Ruff, whitespace, paired document IDs/numbers/technical tokens/commands/links and preservation checks pass. No test thresholds, integrity assertions or diagnostic limits are relaxed.

Final backend command, from the project directory:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_disconnect.py tests/integration/test_monitor_disconnect_ownership.py tests/unit/test_monitor_read_ownership.py tests/unit/test_index_evidence_flights.py tests/integration/test_websocket.py tests/integration/test_runtime_status_websocket.py tests/unit/test_read_tracing.py tests/unit/test_audit_read_integrity.py tests/integration/test_read_trace_ownership.py tests/integration/test_monitor_read_tracing.py tests/integration/test_monitor_evidence_sharing.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_runtime_status_projection.py tests/integration/test_runtime_status_composition.py tests/integration/test_backtest_startup_isolation.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_workspace_reads.py tests/integration/test_monitor_loop_result_api.py tests/integration/test_monitor_loop_retention.py tests/unit/test_loop_diagnostics.py tests/unit/test_monitor_loop_report.py tests/integration/test_monitor_contract_negotiation.py tests/integration/test_web_api.py -q --basetemp=.pytest_cache/dha-final-regression
```

Browser command from `web/`: `npm run test:e2e -- dashboard.spec.ts streamCompletion.spec.ts backtest-workspace.spec.ts backtests.spec.ts`; types: `npm run type-check`.

## DHA-V08. Operational events and preserved work

The initial probe reached an older service whose tracing window had expired; its uncorrelated samples are excluded. That owner was normally stopped/drained, then the fixed baseline and candidate windows were started using the same configuration. No historical records or storage fences were manually cleared.

After both fixed browser waves and the supplement had completed, the last confirmation initially encountered connection refusal. A different standard-entry service then occupied the port without tracing. No Python crash event or normal exit record established the earlier replacement's initiator. A duplicate start failed to bind and shut down; it is not counted as validation. The current owner was preserved. Normalized loaded-code signatures for 6 transport/authority functions match the frozen candidate. Its snapshot has 0 owned reads / retained evidence bytes; 2 transport children belong to its still-active client, not to the completed measurement sockets. Do not interpret that different instance's counters as a before/after performance measurement.

Initial parallel AI extraction files retain their fingerprints. Newly observed parallel changes in `src/trade_plan_monitor/web/daily_service.py`, `web/src/components/plans/PlanSimulationPanel.vue` and `web/tests/unit/dailySimulation.spec.ts` are also excluded and not edited by this task. Read-only inventory retains 5 historical runs, 19 preparations, 14,800 audit rows and 0 fills; nonzero-fill behavior is covered by fixtures. Configuration and inventory are unchanged and recorded in portable evidence. During execution, other work advanced repository HEAD to `729d56c`; those commits are outside P0 and are preserved. The implementation phase performed no commit or push; the later user instruction separately authorizes scoped publication after review.

## DHA-V09. Limits and remaining work

The admission guarantee begins at server-observed terminal state. A silent network failure cannot be detected before the transport reports it; already admitted work remains owned until actual completion. Active monitor reads still verify full historical evidence. Their CPU competition and the observed 6.502-second mixed result maximum remain possible; P0 removes abandoned-connection admission and does not claim to solve every live-reader tail. Canonical-byte P1, process isolation, larger pools, altered heartbeat timeouts and proof caches are not part of this change.

## DHA-V10. Pre-publication review

The follow-up review finds no blocking correctness, architecture, security or performance defect in the P0 diff. A fresh run covering disconnect/ownership, both websocket contracts, tracing, read ownership and evidence flights passes 72 tests in 10.60 seconds with 1 existing Starlette deprecation warning. Scoped Ruff passes. Fresh process-local admission, child-join and cancellation-identity mutations are all killed by their intended assertions; these are deliberate negative controls, not failures of the candidate. No production file changes are required by the review.

The 7 candidate source/test fingerprints still match the measured candidate, the 4 core ownership/verification files match the baseline, and all 8 initial AI file fingerprints remain unchanged. All 4 bilingual document pairs pass parity and link checks. The existing 460-pass backend and 25-pass browser results remain applicable to the frozen code; they are not represented as fresh reruns. Portable measurement evidence is preserved unchanged. Before publication, remote `main` already equals `729d56c`; prior AI extraction and daily-inventory commits are therefore outside this new push range. Only the explicit 17-file P0 allowlist is eligible for these commits.

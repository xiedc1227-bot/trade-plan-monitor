# Single-monitor verification implementation report

Date: 2026-10-21. Baseline: `ba4156e`. [Chinese review copy](single-monitor-verification-2026-10-21.zh-CN.md). [Specification](../specifications/backtesting/SPEC-single-monitor-verification.md), [tasks](../specifications/backtesting/TASKS-single-monitor-verification.md), [portable observations](evidence/2026-10-21-single-monitor-verification/measurements.json). P0 is implemented and verified; the specific P1 experiment is deferred.

## SMV-V01. Actual 503 and recovery

Correct version-2 dashboard and health requests return 503 before implementation. Observe the running process before restarting: read admission is not permanently closed, but has 1 storage pause; owned reads, active validators and retained input are all 0. The actual owner is STOPPING/STALLED. Its heartbeat fails with `runtime liveness changed`: expected revision 28033, durable revision 28034. Cleanup then fails at the actual WAL checkpoint with `(1, -1, -1)` and deliberately retains the pause. This is an invalidated-owner/failed-cleanup rejection, not a successful fast read or evidence of deleted history.

The retained exception establishes the version conflict and busy checkpoint, but cannot identify the historical competing writer/checkpoint owner. Current inspection finds no checked-out sessions or open transactions in that process. Do not infer who caused the earlier conflict or release its fence manually. Python 3.14's [official diagnostic API](https://docs.python.org/3.14/library/sys.html#sys.remote_exec) captures only curated categories, frames and counters; no credentials, evidence bodies or SQL parameters are recorded.

After confirming `READ_READY`, `physicallyDrained=true` and empty `authorizedJobIds`, request normal server shutdown. Its normal cleanup retry completes, including database close; only then start one standard module entry with unchanged configuration. No authority rule is modified. A new regression reproduces a stale heartbeat writer and a real SQLite reader preventing checkpoint completion, asserts 503/pause while cleanup fails, releases the isolated blocker and verifies normal cleanup retry and STOPPED health. The fixture proves the boundary, not the identity of the historical blocker.

Before canonical changes, 3 actual-owner dashboard reads succeed: 3.7509 / 3.7064 / 3.7028 seconds, RUNNING/STANDBY, 0 active symbols. Actual browser list → result → provenance → summary, then 2 result tabs plus health/heartbeats, succeeds with 0 business writes and 0 page errors. These successful reads replace the earlier 503 observations as the live baseline.

## SMV-V02. P0 boundary and equivalence

`canonical.py` has one private verification core returning a row-local canonical primitive tree. The existing public integrity function still returns `None`; the repository uses the new verified-JSON helper to encode the already verified tree for literal equality. Original public hash helpers retain their interfaces. Typed JSON parsing/model validators, exact snapshot/bar/tuple boundaries, bar ordering, request ordering, domain-separated hashes, formula/fact-formula checks, all row metadata/provider/schema bindings, head identity and ranking remain in place. No normalized history is retained.

Every historical candidate is still checked. All 2,008 frozen rows match the original decoder; 18 differential corruptions reject equally. Frozen workload: 72,280 embedded bars, 27,588,993 JSON bytes, no active plans/requests/facts. Separate tests cover 4 requests/4 facts, correctly reordered requests/facts, typed boundaries, canonical goldens and payloads approaching 16 MiB. The repeated-bar large fixture tests representation size and is not market-history validity evidence.

The read service, full independent authority comparison, observed time, plan/inventory/risk/calendar/proof checks, activation reread, 2-attempt budget, socket behavior and sharing coordinator are unchanged. Existing 8-read/1-validator/1-queued/64-MiB/128-row/15-second bounds remain. No cache of completed proofs, financial/API/schema/retention/worker/timeout change is introduced.

## SMV-V03. Timing and P1 decision

Use explicit-BEGIN transactions on the same frozen read-only database, a bounded pool, synthetic absent-owner authority and a fixed clock. This isolates historical verification and is not actual-owner acceptance. Each caller performs 2 independent authority calls; all complete dashboards/results match. Ordinary timings exclude profiling. Keep every round and both experiment scopes.

Final code, 10 alternating dedicated single-read rounds: wall median **3.6401 → 2.2290 seconds**, CPU **3.6016 → 2.1797 seconds** (38.8% / 39.5% improvement). This dedicated single-read scope passes >=30% wall/CPU improvement and <=2.5 seconds. Final code also passes complete-output/drain smoke checks with 2/8 monitors plus a result and staggered arrivals.

The earlier 10-round matrix interleaves single and mixed workloads:

| Workload | Wall median before → P0, seconds | CPU median before → P0, seconds |
|---|---:|---:|
| Single monitor | 4.6741 → 2.6352 | 4.6094 → 2.6094 |
| 2 monitors + result | 7.3657 → 5.6266 | 7.5156 → 5.7891 |
| 8 monitors + result | 8.8330 → 6.5476 | 11.5547 → 8.9531 |
| 2 monitors + result, 0.75-second stagger | 7.5063 → 5.5269 | 7.6484 → 5.7188 |

All mixed medians improve, meeting the <=10% regression bound. The interleaved single median **does not meet 2.5 seconds**; retain this limitation rather than selecting only favorable rounds. These measurements do not establish a sustained 2.5-second service guarantee or p95. The final dedicated run follows extraction of the common private core so integrity-only callers avoid an unnecessary final JSON encoding; both scopes and raw observations remain available.

Separate post-P0 worker profiling reduces recursive `canonical_value` calls from 3,701,644 to 1,236,442 and `canonical_decimal` calls from 1,328,368 to 447,344. Parsing still checks all 2,008 candidates. Profiled times are diagnostic and not latency results.

Do not ship P1 in this slice. A process-local experiment limits exact Decimal-tuple representation reuse to 64 entries / 128 KiB inside one physical validation and discards it at completion. In 10 alternating P0/experiment single-read rounds, wall median worsens **2.4693 → 3.2627 seconds**, CPU **2.4375 → 3.2266 seconds**. One validation has only 635 hits among 447,344 calls (about 0.14%); key construction and misses cost more than saved normalization. This rejects that variant, not every possible future representation strategy. No experimental cache enters production.

## SMV-V04. Memory

3 fresh processes per implementation measure process peak working set and committed memory; separate fresh processes measure traced Python allocations. The traced peak is 42,891,879 → 42,890,153 bytes. Median process peak working set is 284,057,600 → 283,934,720 bytes, and peak committed memory is 1,036,046,336 → 1,035,931,648 bytes. No measured regression approaches 10%. Traced timings are excluded from performance tables. The raw-input peak remains 30,826,621 bytes; retained bytes and owned work return to 0 after drain. This distinguishes total/transient memory from the coordinator's raw-input accounting. These memory results apply to the frozen workload; the near-limit fixture separately checks byte/integrity behavior.

## SMV-V05. Safety and regression

All 312 relevant backend tests pass in 509.61 seconds across the 27 modules listed in portable observations. Tests retain independent authority/time/activation/current-input checks, all-history tamper rejection, same-size/restored-time tamper, missing/BLOB/provider/formula/head cases, 90-second/target/date/clock boundaries, unreadable/STALLED/STOPPING authority, completion races, retained-head deletion, cancellation ownership, actual storage drain and admission limits. Active current-plan proof tests retain inventory/risk/calendar/proof binding. The existing Starlette/httpx deprecation warning is not suppressed.

New tests first fail for the missing verified-JSON interface, then pass against the common core, including nonempty facts and the near-16-MiB payload. A process-local mutation deleting the fact-formula gate causes the rehashed-fact regression to fail with `DID NOT RAISE`; an initial helper import-path collection error is corrected and is not counted as mutation detection. Production files are never changed for this experiment. Changed-file lint and whitespace checks pass.

Frontend type check and production build pass. All 8 strict workspace/runtime-root Chrome cases pass in 28.0 seconds, including route reentry, result/source/history navigation, slow/error/retry behavior and request/write audits. Frontend source is unchanged; a full frontend unit-suite rerun is not claimed.

Final code review finds no blocking correctness, evidence-integrity, ownership or scope issue. The complete independent-authority/read-lifecycle source is unchanged. The repository decoder retains typed parsing, every metadata/provider binding and literal string equality, delegating only the repeated canonical work to the common core. Reviewed limitations remain the interleaved 2.5-second miss and variable live result timing; no assertion or acceptance threshold is lowered.

## SMV-V06. Actual browser and preservation

The final standard module entry uses unchanged configuration. Actual version-2 dashboard reads return 200 in 2.3484 / 2.2850 / 2.2856 seconds, RUNNING/STANDBY, 0 active symbols; the 3-read median improves about 38.3% from 3.7064 to 2.2856 seconds. This is a short live observation, not a latency distribution.

Chrome for Testing 157.0.8103.6 verifies list → result → provenance → summary, 2 simultaneous result tabs plus health/heartbeats, and the actual monitor page. A separate observation waits for a real version-2 `heartbeat`, checks the visible connected state and captures the monitor as STANDBY. Result and monitor screenshots are visually checked and remain in the ignored observation directory. Final journey: 0 business writes, 0 page/console errors, both result tabs ready and all completed result requests 200. The lightweight service probe returns 200 in 45 ms.

Keep all real result observations: before single/pair requests take 4.405 / 6.344 / 6.344 seconds; the first P0 journey takes 3.205 / 5.003 / 5.000 seconds; the final full rerun takes 8.691 / 4.933 / 4.933 seconds. The first P0 attempt completes both result phases but its added monitor check uses the fixture heading instead of the actual installed heading and times out. Inspect the actual DOM, correct that observation-only locator, and rerun the full journey successfully. Preserve the initial attempt as well. The final single-result outlier prevents a blanket claim that every real page read became faster. Live data/background activity vary; frozen medians are the controlled comparison.

Read-only inventory retains 5 results, 8 reviewed sources and 2 timeline roots, matching the previous recorded inventory; preparation records are also retained (19). The service is READ_READY, physicallyDrained=true, with empty authorizedJobIds. No business write, job submission, real historical cleanup, evidence rewrite, manual fence release, configuration change, commit or push is performed.

## SMV-V07. Reproduction and limits

Use `.venv/Scripts/python.exe -m pytest` with fresh project-local `--basetemp` for the modules listed in portable observations. System temp permissions require that isolated project-local directory; this is not a test assertion failure. Run changed-file `.venv/Scripts/python.exe -m ruff check` and `git diff --check`. From `web/`: `npm run type-check`, `npm run build`, and `npm run test:e2e -- tests/e2e/backtest-workspace.spec.ts tests/e2e/result-read-concurrency.spec.ts`.

Ignored helpers/logs remain under `.pytest_cache/single-monitor-implementation/`; the original proposal/evidence and frozen copy are preserved. Full repository testing and a sustained latency SLA are not claimed. Full-history verification still grows with evidence bytes/bars. No commit or push is included in this request.

## SMV-V08. Pre-push review, 2026-10-22

The user subsequently authorizes review, commit and push. Review finds no blocking correctness, security, evidence-integrity, ownership or scope issue. Original canonical normalization rules and public hash helpers, metadata bindings, complete historical traversal and ranking match the baseline AST. The independent authority, physical-read ownership and in-flight coordinator source is unchanged. Source fingerprints match the implementation previously verified by all 312 tests; production code is not modified during this review.

Pre-push rerun: 152 targeted backend tests pass in 101.82 seconds, covering the common canonical core, nonempty facts and near-limit payload, tamper/time/authority checks, physical cancellation/drain, stale heartbeat/WAL busy recovery, retention and result ownership. All 8 strict browser cases pass in 26.1 seconds. Changed-file lint, whitespace, bilingual IDs/technical tokens/numbers/links and JSON validation pass; credential-pattern checks find no credential material in the selected changes. The fact-formula gate-removal mutation again fails its rehashed-fact assertion as expected. Existing Starlette/httpx deprecation remains unsuppressed.

The earlier performance observations and their limitations remain unchanged, including the interleaved 2.5-second miss, variable live result timing and the rejected P1 variant. Keep real data, configuration, temporary diagnostics, frozen databases, screenshots and build products out of the commits. Include only scoped source/tests, paired documents and portable observations. Commit messages follow the repository's Chinese Conventional Commit format, and use an ordinary push without rewriting remote history.

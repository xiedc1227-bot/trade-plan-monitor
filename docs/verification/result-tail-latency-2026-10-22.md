# Result-page tail latency: P0 verification and P1 decision

Date: 2026-10-22, Asia/Shanghai. [Chinese review copy](result-tail-latency-2026-10-22.zh-CN.md). [Specification](../specifications/backtesting/SPEC-result-tail-latency.md), [tasks](../specifications/backtesting/TASKS-result-tail-latency.md), [portable observations](evidence/2026-10-22-result-tail-verification/measurements.json), [rejected candidate patch](evidence/2026-10-22-result-tail-verification/rejected-p1.patch).

## RLT-V01. Delivered scope

P0 is implemented: opt-in bounded traces correlate browser requests, independent metadata admission, physical worker execution, shared observers, immutable-input/report/audit verification, explicit response validation and response handoff. WebSocket connection IDs correlate heartbeat/read children. Thread propagation binds diagnostic context only, never caller authority or session context. Async waiting does not claim other event-loop work as its CPU. Cancelling every observer does not release or erase owned physical work.

Trace `status` describes scope termination; use `http.headers.statusCode` for HTTP success, never treat scope completion as a successful read.

P1 is deferred after its fixed acceptance experiment; its candidate source is retained as a patch, outside production. Final audit decoding, ordered-set hashing, input/result reads and monitor snapshot/activation-read bodies match the existing `c3d16da` bodies after excluding diagnostic decorators: 8 function-body comparisons. Independent authority comparisons, per-request clocks/BEGIN snapshots, activation rereads, current plan/inventory/risk/calendar/proof checks, retry budgets, ownership, retention and in-flight-only sharing are preserved. No completed-proof cache, codec change, worker increase or relaxed deadline is shipped.

## RLT-V02. Original observation and newly captured timelines

The old 8.691-second browser observation still cannot be retrospectively assigned exact server stages. Its visible dashboard overlap is 3.543 seconds, followed by 5.148 seconds; this page's own first 20-second heartbeat occurs later. New measurements establish actual mechanisms without pretending to reconstruct that exact historical request.

The following successful HTTP reads use real historical results and actual runtime ownership, without server-side injected delay:

| Sample | Client seconds | Metadata observer | Result admission | Worker | Explicit response validation | Remaining network/response/scheduling |
|---|---:|---:|---:|---:|---:|---:|
| Dashboard overlap | 9.0828 | 0.0488 | 0.000021 | 9.0185 | 0.0018 | 0.0136 |
| Queued/abandoned-client scenario | 14.2567 | 0.0032 | 8.8241 | 5.3077 | 0.0009 | 0.1208 |
| Real 8-page stress | 20.5145 | 0.3323 | 17.7600 | 2.3774 | 0.0012 | 0.0435 |

The 9.0828-second sample spends 8.3427 seconds in audit verification/diagnostics, with 3.4688 seconds of thread CPU; the entire worker uses 4.1250 CPU seconds. There are 3 overlapping monitor reads. This supports execution contention, not a result-admission queue explanation for that sample. Wall minus CPU is not exclusively GIL wait: scheduling, I/O and GC are not individually separated. The queued samples demonstrate a different mechanism. Nested audit/worker times must not be summed, and logical monitor counts must not be added as physical CPU.

All 19 captured successful API requests >=8 seconds have physical-worker links and reconcile within 5%; the largest residual is 2.21%. Shared-worker intervals are clipped to each observer's own waiting interval. ASGI body times describe handoff, not remote receipt; framework serialization, middleware and scheduling remain a labeled residual, not exclusive serialization CPU.

Page readiness is a different clock boundary. For the 9.858-second real entry, navigation/initialization before the result request takes 2.1798 seconds, the API takes 7.4936 seconds, and body-to-locator-ready takes 0.1845 seconds. The request-before phase is recorded but not subdivided into asset delivery and JavaScript initialization. API first byte is at 7.4929 seconds, so body transfer is not the dominant delay. Do not label all page waiting as evidence verification.

## RLT-V03. Confirmed extra work after page closure

Connection IDs link 7 heartbeat attempts to already closed startup pages, starting 18.03–21.17 seconds after browser closure. Of these, 6 enter monitor snapshot verification, taking 3.27–10.93 seconds; 1 never enters a snapshot and is not counted as a successful fast read. These are direct browser/server correlations, not inferred solely from old access logs.

The existing `CommittedMonitorEventStream.serve` waits for publication/heartbeat cadence without a parallel disconnect receiver. At a heartbeat deadline it awaits the full current health read before attempting to send. A closed peer can therefore be discovered only after this work. This adds real CPU competition and may overlap result reads; it does not prove that every historical outlier has the same cause. The old claim that the new page's own heartbeat explains its first 8.691 seconds remains unsupported.

## RLT-V04. Before/after observations

Actual-service API waves retain all samples and separate failures:

| Scope | Before median seconds | P0 median seconds | Sample count per wave |
|---|---:|---:|---:|
| Independently issued result | 2.3497 | 2.3986 | 20 |
| Result plus dashboard | 4.8612 | 4.8149 | 20 |

Background clients and pending closed connections differ across these waves. They are not a controlled speedup estimate; independently issued does not guarantee no server overlap. P0 makes the wait explainable. A separate 10-round alternating, unprofiled, read-only full-result-route comparison measures instrumentation itself: wall 2.1224 → 2.1724 seconds (+2.36%), CPU 2.1016 → 2.1406 seconds (+1.86%). This meets the <=5% wall / <=2% CPU targets; complete response objects and hashes match. It is an isolated ASGI route/service comparison, not live-owner acceptance.

Real browser startup has 20 successful entries: readiness median 5.848 seconds, range 4.732–9.858 seconds. Both 2-page and 8-page stress show every result view ready; the maximum 8-page readiness is 24.293 seconds. Another 20 successful result reads overlap heartbeats from the same monitored browser page. The last request changes connection while reading; its overlap is correctly attributed to that page's previous connection, not its connection ID at return.

## RLT-V05. P1 acceptance and deferral

The initial process-local feasibility experiment improves wall 11.34% and CPU 10.94%, so a formal row-local byte-flow candidate was evaluated. It keeps all typed/envelope/canonical/ordered-set gates, bounds retained bytes including object overhead, falls back for oversized UTF-8 and releases each row before the next. No object-identity or completed-proof cache is used in that candidate.

Its first formal 10-round wall improvement is 9.998%, below 10% without rounding. Exactly 20 additional alternating rounds were then declared and all 30 were pooled; no initial samples were excluded and no further attempts were made to obtain a pass:

| Single result, pooled 30 rounds | Existing path | Candidate | Improvement |
|---|---:|---:|---:|
| Request wall seconds | 2.0877 | 1.8678 | 10.53% |
| Process CPU seconds | 2.0625 | 1.8594 | 9.85% |

The simultaneous >=10% CPU and wall gate fails, so production retains the existing path. The 10-round mixed scenarios show no >10% regression. Separate 3-process memory runs per variant show median Python allocation peaks 22,413,741 → 22,419,121 bytes; working-set/private peaks also remain within 10%. These favorable results do not override the failed CPU gate. The candidate's 55-test integration pass and mutation results are exploratory evidence, not a reason to ship it. The portable patch preserves its source/tests for review.

## RLT-V06. Tests and browser checks

- Final backend: 398 passed, 1 existing skip for POSIX ownership semantics on Windows, 1 pre-existing Starlette deprecation warning. Coverage includes authority changes, time boundaries, tampering, retention, publication, concurrency, cancellation/all-observer departure, storage pause/drain and startup recovery.
- Final production-path mutations: 8 killed — `decoder-envelope`, `canonical-equality`, `event-hash`, `set-identity`, `set-count`, `set-hash`, `length-prefix`, `authority-token`. A non-fixed-fraction timestamp specifically isolates canonical equality from typed time/hash validation.
- Browser regression: 18 affected cases pass after synchronizing 3 stale assertions with existing product behavior: removed coverage-date controls, advanced service disclosure and expandable equity table. The 5 unchanged isolated worker journeys pass in the initial run. All 23 distinct cases are covered; no product UI is changed or request/DOM/polling/accessibility thresholds relaxed.
- Real browser: 20 startup entries, 2/8-page stress and 20 heartbeat-overlap reads, all result responses successful. There are 0 page-script errors and 0 business writes. Normal startup/heartbeat phases have no console errors. Stress retains 16 network 503s separately: 15 dashboard and 1 job-list request. They are protected monitor/metadata rejections under overlapping load, not successful fast reads; result pages remain readable. Bounds are not raised to hide them.
- Native real-page confirmation: provenance/summary switching, refresh and return to monitor succeed with no console errors or writes. The monitor returns HTTP 200 and RUNNING/STANDBY. Initial and refreshed results have distinct physical reads, each with an audit-verification span. Final screenshots were inspected.
- Type checking and Ruff pass. `git diff --check` is applied to this task's paths. The initial proxy 502, missing-protocol-header 409, connection-before-listener startup race, interrupted candidate helpers and large automatic test-parameter-ID issue are excluded from success claims and retained in ignored diagnostic logs.

## RLT-V07. Operation, data and preserved work

Tracing is opt-in through `TPM_READ_TRACE_DIR`; unset creates no diagnostic sink/header. A window lasts 1800 seconds, admits <=1024 traces / <=64 active traces, keeps <=64 spans per trace / <=128 completed records in memory, and rotates 1 MiB files with 2 backups. Only fixed categories, opaque IDs, clocks, counts and byte lengths are accepted. Sink/init/overflow failures cannot authorize reads or change business results. Data bodies, SQL values, credentials and authority tokens are never logged.

From the project directory, after normal shutdown/drain of an existing owner:

```powershell
$env:TPM_READ_TRACE_DIR = '.pytest_cache/read-traces'
.venv/Scripts/python.exe -m trade_plan_monitor web --config config/app.yaml --host 127.0.0.1 --port 8765
```

Disable the variable before a later normal restart to remove diagnostics. Never start a duplicate owner or manually clear a storage pause. Actual tests used normal shutdown/drain and unchanged configuration; the final service remains available. Read-only inventory finds 5 historical runs, 19 preparation records and 14,800 audit-detail rows. Production data has 0 fills; nonzero-fill behavior is covered by isolated fixtures, not claimed as real historical trades.

Existing work is preserved, including the `c3d16da` filter change and `19cd05f` initialization-diagnostics commit. Concurrent AI extraction/contract work under `src/trade_plan_monitor/ai/plan_extraction.py`, `tests/unit/test_current_review_contract.py` and `tests/fixtures/ai/current-review-contract/` is outside this task's verification scope and remains untouched. The implementation phase performed no commit or push. The subsequent user instruction authorizes P0 review, commit and push; concurrent AI extraction code, tests, fixtures and verification documents remain excluded.

## RLT-V08. Next optimization proposal

Prioritize disconnect-aware heartbeat admission before further encoding micro-optimization. A bounded disconnect observer should stop a known-closed connection from starting a new health read. If closure occurs after admission, detach the observer through existing ownership; keep physical validation, cancellation checks, storage pause and drain until actual completion. Avoid treating an unconsumed socket-state property as proof of connection liveness.

Connected requests must still perform independent before/after authority and full evidence checks; keep frame/cursor/replay/cadence and all admission/deadline limits. Validate closure before the first heartbeat, closure during snapshots, all observers leaving, send/receive races, publication wakeups, 2/8 clients and cleanup failure retaining its pause. Compare post-close snapshot starts and result tail latency under the same workloads. This is the next proposal, not an unreviewed change shipped inside P0.

## RLT-V09. Pre-push review

The subsequent user instruction authorizes review, commit and push of P0 only. Review found no blocking correctness, privacy, ownership or verification regression. All 12 packaged source fingerprints still match; 8 verification function bodies remain unchanged. The rejected P1 production source remains absent. All 4 bilingual document pairs pass stable-ID, number, technical-token, command and local-link checks.

Fresh verification: 127 backend tests passed in 177.67 seconds, with 1 existing Starlette deprecation warning; 18 browser cases passed; type checking, scoped Ruff and whitespace checks passed. A process-local reversal of the newly added diagnostic expiry condition is killed by the tracing tests. This mutation changes no working-tree production file. The earlier 398-test acceptance and real-browser measurements remain valid for these identical source fingerprints; the new focused run does not replace or inflate them.

Backend review command, from the project directory:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_read_tracing.py tests/unit/test_audit_read_integrity.py tests/integration/test_read_trace_ownership.py tests/integration/test_monitor_read_tracing.py tests/integration/test_monitor_evidence_sharing.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_runtime_status_websocket.py tests/integration/test_monitor_loop_result_api.py tests/integration/test_monitor_loop_retention.py tests/unit/test_loop_diagnostics.py tests/unit/test_monitor_loop_report.py -q --basetemp=.pytest_cache/rlt-preship-review
```

Browser review command, from `web/`: `npm run test:e2e -- backtests.spec.ts backtest-workspace.spec.ts`; type checking: `npm run type-check`.

Use an explicit 27-file P0 allowlist, split into specification, tracing primitives, integration/tests and verification evidence commits. Exclude concurrent AI extraction source, unit tests, fixtures, verification reports and evidence directories from every new commit. Existing `c3d16da` and `19cd05f` commits contain no AI extraction changes. P0 is diagnostic attribution; known stress admission rejections and disconnect-aware heartbeat admission remain the separately documented next scope.

The archived candidate patch uses zero context to avoid trailing whitespace in blank context lines; applicability is checked with `git apply --check --unidiff-zero docs/verification/evidence/2026-10-22-result-tail-verification/rejected-p1.patch`. It is not applied.

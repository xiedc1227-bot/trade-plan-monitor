# Result-page latency variation: analysis and next proposal

Status: analysis only, 2026-10-22. Baseline: `87d85cc`. [Chinese review copy](PROPOSAL-result-tail-latency.zh-CN.md). [Portable observations](../../verification/evidence/2026-10-22-result-tail-analysis/measurements.json). [Previous verification](../../verification/single-monitor-verification-2026-10-21.md). No production implementation, service restart, commit or push is included.

Progress and acceptance are recorded in [Specification](SPEC-result-tail-latency.md), [Tasks](TASKS-result-tail-latency.md) and [Verification](../../verification/result-tail-latency-2026-10-22.md). This proposal retains the analysis snapshot.

## RLT01. What the 8.691-second observation proves

The historical browser record measures request start through response completion, not worker CPU, first-byte latency or complete page rendering. Use result-request start as relative zero:

| Observed event | Relative time, seconds |
|---|---:|
| Initial dashboard request starts | -0.658 |
| Result request starts | 0.000 |
| Dashboard response completes | 3.543 |
| Result response completes, HTTP 200 | 8.691 |

The visible requests overlap for 3.543 seconds; the result continues for 5.148 seconds after dashboard completion. Do not subtract the overlap as CPU or assume the remaining interval is pure result work. Hidden server work and waits are not recorded.

This page's own first heartbeat cannot explain that request: the socket opens after its initial snapshot, and the unchanged server heartbeat cadence is 20 seconds. The result finishes earlier. Other existing clients' heartbeats remain possible, not proven. The same service had already completed earlier result reads, so process cold startup alone is not established either; OS file-cache state was not measured.

The same final journey's two result requests each take 4.933 seconds and share in-progress result projection when their keys match. This is compatible with a faster pair than the isolated outlier: request count alone does not determine physical work or background overlap. Each caller still reads its own mutable result metadata. Historical browser spans lack server ingress, queue, worker, GC and response-stage timings, so the complete cause of the original 8.691 seconds cannot be reconstructed retrospectively.

## RLT02. Newly localized base cost

At analysis time, port 8765 had no listener. Do not substitute synthetic authority for live acceptance. Supplementary measurements use the real result database via `mode=ro` / `query_only=ON`, its existing immutable copied files, and the production result route/service/ownership/response-validation code in an isolated ASGI application. No providers, job execution or business writes are involved. The monitor competitor uses the previous frozen 2,008-candidate read-only copy, fixed clock and synthetic absent-owner authority; this tests CPU competition, not actual owner readiness.

One separate stage-instrumented full result request takes 2.2194 seconds:

| Inclusive stage | Wall seconds |
|---|---:|
| Metadata result lookup | 0.0017 |
| Result projection | 2.2149 |
| Input/report/diagnostics snapshot | 2.1554 |
| Copied input verification, including bundle and 39 days | 0.3587 |
| Full audit verification and diagnostics | 1.7585 |
| Raw copied-object reads, 41 calls | 0.0116 |
| Public response revalidation | 0.0007 |

Audit verification is about 79.2% of this request. These nested values must not be summed. The response is 15,559 bytes. Raw SQL component scans of all 2,961 audit rows / 3,199,278 payload bytes take 0.0183 / 0.0063 / 0.0063 seconds, without a cold-cache claim. The query already uses `ix_backtest_detail_retention` for kind/run identity. There is no measured justification for an index addition, larger page size, fewer evidence rows or weakened response validation.

Separate worker profiling locates 2,961 `decode_audit_record` calls, 15,295 backtest `canonical_json` calls and 2,263,592 recursive `canonical_value` calls. The profiled request takes 4.9291 seconds; that is profiler overhead, not ordinary latency. The dominant path normalizes stored payload into a typed event, checks event identity/hash, normalizes it again for payload equality, then normalizes the same event again for the ordered event-set digest. See [results.py](../../../src/trade_plan_monitor/backtest/results.py), [loop_publication.py](../../../src/trade_plan_monitor/backtest/loop_publication.py) and [loop_report.py](../../../src/trade_plan_monitor/backtest/loop_report.py).

## RLT03. Competition, GC and queue assessment

5 alternating complete-route observations, recording result completion separately from batch completion, retain identical full responses:

| Scope | Median result seconds | Median total process CPU seconds |
|---|---:|---:|
| Result alone | 2.2301 | 2.1563 |
| Result plus full monitor read | 4.3369 | 4.4688 |

The second CPU value includes both tasks. This confirms a CPU-competition mechanism, not the original outlier's exact attribution. The local interpreter has the GIL enabled; Python-heavy threads do not obtain unrestricted parallel execution. See [Python threading](https://docs.python.org/3.14/library/threading.html). More threads are not a demonstrated fix.

GC is observed without disabling it: maximum individual collection is 0.1092 seconds in these samples. This does not explain a multi-second residual here, nor rule out an unobserved historical pause. Ordinary metadata execution is cheap in isolation, but `get_run` first waits on the metadata gate and then may wait on the result gate. Heavy review-context reads also use the metadata path. Those queues are candidates for tracing, not proven contributors to the historical request. The existing 5-second metadata admission wait and 60-second result admission wait must not be raised.

The supplementary overview competitor does not reproduce a large slowdown on this frozen calendar/data selection. A calendar-unknown branch can traverse history, but the old request log alone does not prove it was taken. Do not blame all overview polling or change its observation semantics without a measured span.

## RLT04. P0: complete attribution before claiming a tail fix

First record paired implementation specifications/tasks. Add bounded, correlated observation across browser request/first-byte/body/ready, HTTP ingress/response start/body end, metadata admission and worker start, result admission/join/worker start/end, copied-input/report/audit verification, diagnostics, public validation and serialization. Distinguish logical callers from physical shared work; attribute a shared worker's CPU once. Capture cancellation/detachment and actual physical drain. Preserve original deadlines and strong ownership.

Use monotonic wall time and worker-thread CPU separately; process CPU includes competing tasks. Record stage/category/count/bytes/generation and an opaque request correlation identifier, never credentials, source text, plan bodies, SQL parameters or every audit row. Retain only a bounded diagnostic window and cap events/bytes; observation failures must not authorize data or change request results. Compare observation enabled/disabled, targeting <=2% CPU and <=5% wall overhead. Use [Python clock semantics](https://docs.python.org/3.14/library/time.html#time.thread_time) and keep [profiling](https://docs.python.org/3.14/library/profile.html) outside ordinary timings.

When the actual service is intentionally available, confirm success/readiness before measurement. Capture at least 20 successful observations per isolated, startup-dashboard overlap, existing-client heartbeat, staggered and queued/abandoned-observer scenario, plus bounded two/eight-reader stress. Keep failures separately with categories; never treat 503 as fast success. For newly captured requests >=8 seconds, reconcile stage intervals to within 5% of end-to-end time or explicitly retain an unattributed gap. Publish medians, ranges/maxima and all samples; do not infer p95 from a small run or claim the historical request has been reproduced if it has not.

## RLT05. Conditional P1: remove duplicate event encoding, keep the whole proof

After P0, evaluate a row-local verified canonical representation shared only by the immediate payload-equality check and ordered event-set digest. Keep one verification core and existing public helper behavior. Preserve typed model validators and event hashes, storage content domain/hash, SQL-to-payload identity, version/authority/time bindings, sequence/run membership, count, ordered length-prefixed event-set hash and report/input/frozen-day/diagnostic checks. Continue traversing every required retained row; EXPIRED/NOT_RECORDED handling stays truthful and must not resurrect evidence from memory.

An ignored process-local feasibility experiment reuses the already encoded text only for the exact same owned immutable event's next encoding, bounded to 1 event / 256 KiB and cleared at physical completion. 5 alternating observations give median result 2.0852 → 1.8925 seconds and CPU 2.0625 → 1.8438 seconds (about 9.2% / 10.6%). Each traversal saves 2,961 encodings, retaining at most 8,419 UTF-8 bytes in this sample; full response objects and response hashes match. This is not production code, a completed-proof cache, a transient/process-memory acceptance measurement or an integrity/tamper acceptance result. It does not promise to eliminate the original multi-second fluctuation.

Production design should pass verified bytes directly within the row-verification/stream-digest flow, rather than introduce a general object-identity cache or an externally supplied preverified flag. Account for object/string overhead, release each row promptly, preserve all existing type/size/Decimal/timezone/canonical rules and fail closed. Do not switch codecs or JSON modes to save a traversal. No run-id/report-hash/mtime/data-version-only trust, latest-only read or background verification after responding is allowed.

Proposed implementation acceptance: at least 10 alternating unprofiled rounds on the same 2,961-event sample; >=10% median CPU and wall improvement as a target, <=10% peak-memory regression, and no >10% regression in existing mixed scenarios. The current 9.2% exploratory wall result does not yet meet that proposed 10% target. Keep only a production variant whose repeated evidence clears its chosen gate; do not lower the gate to fit this prototype. Include zero/small/large trails, both event schemas, nonzero fills/receipts, Unicode/Decimal/timezone boundaries, altered SQL/row/event/report/ordered-set hashes, missing/reordered/extra rows, retention/pin/publication changes, cancellation/all-observer abandonment and real storage drain. A mutation removing each relevant gate must be caught.

## RLT06. Conditional later work and protected boundaries

If P0 shows heavy review-context work blocking cheap metadata, separately assess routing that read through existing bounded result ownership. Preserve each caller's fresh membership/pin/retention checks and do not add a CPU worker pool. If CPU contention still dominates after measured duplication is removed, process isolation requires its own transaction, IPC-copy/memory, cancellation, child-failure and physical-drain specification; it is not a quick configuration change.

Do not change the independent monitor authority-before/after comparisons, per-request clock/BEGIN snapshot, activation reread, current plan/inventory/risk/calendar/proof checks or retry budget. Preserve monitor admission/sharing limits, socket cursor/replay/heartbeat cadence and result in-flight-only sharing. No completed response/proof cache, positive TTL, dropped old evidence, shortened retention, worker/timeout increase or deferred authority check is proposed.

## RLT07. Delivery and uncertainty

The confirmed findings are visible startup overlap, substantial audit-verification CPU and measurable full-monitor/result CPU competition. The unknown is how the original remaining elapsed time divides among unobserved other clients, queues, scheduling/GIL, file waits, GC and response transport. No exact full root cause is claimed. An initial interrupted helper run is excluded from successful summaries; subsequent complete runs and all scope limitations are retained.

Only this paired proposal and sanitized portable observations are added. This analysis makes no source, real-data, configuration, service-state or Git mutation. Final repository inspection found an existing `c3d16da` commit above the measured `87d85cc` baseline, changing run-list filters and their docs/tests; the backend paths analyzed here are identical across those commits. That work is preserved. Ignored helpers remain under `.pytest_cache/result-latency-analysis-20261022/`. No implementation, service restart or push was performed.

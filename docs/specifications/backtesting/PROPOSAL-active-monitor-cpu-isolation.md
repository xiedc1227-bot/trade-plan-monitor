# Active monitor/result CPU contention: next-step proposal

Status: analysis and proposal only, 2026-10-22. Analysis HEAD: `7a7ac88`. [Chinese review copy](PROPOSAL-active-monitor-cpu-isolation.zh-CN.md). [Previous verification](../../verification/disconnect-heartbeat-2026-10-22.md). [Reconciled observations](../../verification/evidence/2026-10-22-active-monitor-cpu-analysis/observations.json).

This preserves the original analysis phase. The subsequently authorized P0 implementation follows the [specification](SPEC-active-monitor-cpu-isolation.md) and [verification report](../../verification/active-monitor-cpu-2026-10-22.md); its measured buffered process variant is P1 no-go because aggregate input copies exceed 64 MiB.

## AMC01. Conclusion and scope

The retained 6.502-second result request spends 99.678% of its server interval inside the result worker. It overlaps an actual monitor HTTP read, rather than a disconnected socket heartbeat. The result worker consumes 2.578125 CPU seconds while the monitor snapshot consumes 2.6875 CPU seconds. Active CPU contention is supported; its entire elapsed-time penalty cannot be attributed exclusively to GIL waiting. The independent authority path also has substantial elapsed time with little thread CPU and needs finer attribution.

Recommend P0 attribution plus an isolated feasibility experiment, followed by conditional P1 isolation of the pure index-evidence validator. Keep authority capture and every request's transaction/assembly in the parent. Do not move the whole monitor read or authority provider into a process or arbitrary worker thread. This proposal changes no production code, service state, configuration or historical data and performs no commit/push.

## AMC02. The specific 6.502-second request

Client phase: `live-monitor-overlap`, round 18. HTTP trace: `8a948dc26ee245bb88e8a21f9ac847c4`; result physical trace: `05dab05cb6e84445932c0e3a574b8f09`. HTTP 200, 15,559 bytes; first byte and body completion both round to 6.502 seconds. Its complete response hash equals the other 79 direct result responses in the retained before/after waves.

| Recorded interval | Wall seconds | Thread CPU seconds | Interpretation |
|---|---:|---:|---|
| Server HTTP root | 6.5004245 | unavailable | Different clock boundaries from client timing |
| Result admission | 0.0000109 | unavailable | No material result-gate wait in this request |
| Result worker | 6.4794775 | 2.578125 | Main location of elapsed time |
| Publication verification, inside worker | 1.1374665 | 0.390625 | Includes copied-input and report stages |
| Audit verification, inside worker | 5.2498022 | 2.109375 | Dominant result computation |
| Overlapping monitor snapshot | 4.50968 | 2.6875 | Actual competing validated read |
| Monitor authority before + after | 1.2695246 | 0.09375 | Independent checks; waiting source not subdivided |

The worker begins 0.0139714 seconds after HTTP ingress and ends 0.0069756 seconds before HTTP completion: only 0.020947 seconds lies outside it. Thus frontend rendering, body transfer, public response validation and result admission do not explain this particular server tail. Metadata physical execution is 0.0036911 seconds. The worker's wall-minus-thread-CPU difference is 3.9013525 seconds; it includes scheduling/GIL, file/SQLite or other waits, GC/runtime and observation effects, not a measured GIL-wait counter. Nested intervals must not be added; monitor CPU is not an elapsed-time partition of the result request.

Monitor read `fe460d73d12c4f2581e0012e657fb308` starts at +0.325215 seconds and ends at +6.113304 seconds relative to the HTTP root. Its parent `21def0b9a9d34b88b84d1fc9632efc5e` is `http.monitor`, not `monitor.heartbeat`. The retained trace does not establish its exact endpoint or initiating client. Its authority-before span takes 1.0056665 seconds / 0.03125 CPU seconds; authority-after takes 0.2638581 seconds / 0.0625 CPU seconds. Source inspection finds synchronous delivery-health SQL and configuration/semantic checks reachable from the loop-owned authority provider; their individual contribution is unknown. Do not move or bypass those checks based only on these inclusive spans.

## AMC03. Coverage and remaining uncertainty

Offline reconciliation covers all 80 direct result responses and their physical links. In the after wave's 20 `live-monitor-overlap` samples, only 10 actually overlap a captured `monitor.read`; their result median/range is 3.7745 / 2.258–6.502 seconds. The other 10 have median/range 2.246 / 2.030–2.621 seconds. The phase label means clients were connected, not that every result overlaps CPU verification. This distinction matters when evaluating the next change.

An independently issued after-wave request still takes 4.752 seconds without a captured monitor overlap. Capture coverage is bounded; even records with 0 dropped spans do not prove every competing thread/process/request was traced. The current evidence cannot uniquely divide GIL, OS scheduling, SQL/file waits and GC. Small negative wall-minus-thread-CPU values in fast samples are retained as clock/accounting granularity effects, not clamped into exact waits. The waves have different owners/background activity; do not infer a causal speedup or population p95 from these groups. Both waves' 7 protected HTTP 503s remain separately recorded in the original evidence.

## AMC04. P0: bounded attribution and feasibility

Before implementation, create equivalent English/Chinese specifications and tasks. Preserve the current source and frozen evidence fingerprints. Add default-disabled, aggregated diagnostic stages, within the existing 1800-second / 1024-trace / 64-active / 64-span / 128-completed / 1 MiB + 2-backup bounds:

- Split authority into loop-owned capture, health/delivery SQL, configuration/semantic checks and dependency/progress capture without changing their order or result. Record bounded event-loop lag and optional GC duration; no per-row spans or SQL/body/credential logging. Synchronous instrumentation must not yield within an authority capture or change its atomicity.
- Separate index collection/scan, exact-input comparison, leader/follower wait and physical typed/hash/canonical validation. Record wall and worker CPU, candidate/byte counts, join/miss/fallback, cancellation, queue age and physical completion. Link logical callers to one physical proof; count its CPU once.
- Reconcile every captured result request >=5 seconds to within 5% of server elapsed time, retaining any unassigned gap. Preserve original submit/start/admission/publication/audit/headers/body stages. Attribution-enabled/disabled overhead targets remain <=2% CPU / <=5% wall; profiling runs are separate.
- Run an ignored, isolated experiment against the same immutable input: existing validator in its thread versus that exact pure validator in 1 Windows-spawned process. Measure cold start/import, warm execution, parent encode/decode/copy CPU, IPC latency, child CPU and combined memory. Preserve every original row/type/canonical byte and compare complete validated output. No production authority, ORM/session/engine, live clock or configuration object crosses IPC. A frozen absent-owner fixture is a feasibility control, not real-owner acceptance.

Do not restart the real service merely for this analysis or attach a profiler to user traffic. Later actual-owner measurement must use an intentionally available owner and a bounded diagnostic window, preserve readiness, normal shutdown/drain and historical data, and distinguish fresh collection from the retained 6.502-second observation. P0 should end with a measured go/no-go decision; process isolation is not yet an accepted implementation.

## AMC05. Conditional P1: isolate only pure index verification

The existing `RawIndexCandidate` contains frozen literal SQL columns and original payload bytes. `IndexEvidenceFlights` already collects bounded input, compares each follower's own fresh scan and owns one physical validator. This is the narrow candidate boundary: the admitted leader invokes the existing `_latest_index_records` verification core in 1 owned child, then resumes each caller's original parent assembly. Result audit verification stays on its current path.

Parent responsibilities remain unchanged: each caller's authority-before, observed time, BEGIN snapshot, fresh exact-input scan/comparison, namespace/activation/current-input checks, assembly and authority-after, including all existing comparisons and at most 2 attempts. The child validates every supplied candidate, including corrupt unselected history, using the existing typed models, domain hashes, metadata/head/provider/formula binding, literal canonical equality and verified ranking. A closed internal IPC envelope binds the submitted flight identity, ordered full input, counts, semantic version and completion to the returned immutable output; that envelope supplements, and never replaces, existing evidence checks. Missing, truncated, duplicate, foreign-flight or failed child output must fail closed.

Retain 1 physical validator, 1 distinct queued owner, 8 owned reads, 15-second cooperative wait/checkpoint budget, 64 MiB retained-evidence limit, current metadata/result gates and in-flight-only exact-input sharing. No generic process pool or larger queue. Parent ownership covers submitted child work until actual completion/acknowledged exit, result consumption and cleanup; an observer leaving cannot release the permit or bytes early. One follower leaving must not cancel a live leader/follower proof. All-observer abandonment uses cooperative cancellation and physical drain; do not forcibly terminate a worker as an ordinary cancellation shortcut. Shutdown, child crash/hang and storage-cleanup failure retain their pause/fence and cannot authorize database disposal or a successful response. Repeated cancellation must still join cleanup and preserve original cancellation identity.

IPC introduces additional copies outside the current raw-input counter. P0 must measure them; the P1 specification must fix a combined input/copy budget before implementation, account for parent/serialized/child/output/transient objects, and preserve the existing 64 MiB bound rather than applying it independently to every copy. If a complete buffered transfer cannot fit, assess bounded streaming separately or keep the current fully validating thread path for that request. Pre-submission fallback must be explicit and included in performance statistics; child failure must not silently create duplicate work or reset deadlines. Retain no completed proof or response for later callers. Windows spawn entry safety, lazy child ownership and physically drained child teardown require dedicated tests; Python futures cannot cancel a task that is already running.

If authority subspans remain the dominant stall, handle that as a separate change with an explicit authority-consistency design. Moving the entire provider to `to_thread`, caching a previous authority/health result, or checking authority only after returning is outside this proposal.

## AMC06. Measurement and acceptance proposal

Fix sample counts/order before collection; keep failures, fallback, warm/cold startup and incomplete overlap qualification. Use the same input and boundaries, with 10 A/A control pairs and 20 alternating ABBA/BAAB blocks (40 observations per variant) for isolated and deliberately staggered mixed feasibility cases. Track result completion separately from whole-batch completion. Record actual overlap and fresh before/after authority pairs, not just connected-client counts. Synthetic gates/delays are deterministic race tools and are excluded from real-latency claims.

For actual-owner acceptance, predeclare 100 attempts per variant for the primary active-monitor HTTP/result workload; separately exercise live heartbeat, staggered arrival, queued/cancelled observers and bounded 2/8-client loads. Keep all HTTP failures in the denominator. Report conditional success latency plus rejection/cancellation/timeouts, wall/CPU partitions, total parent + child CPU, event-loop lag, child counts, retained bytes and combined RSS/private peaks. Report medians/ranges/maxima for small groups; make a p95 performance claim only with >=100 successful observations per variant and uncertainty disclosed. Do not extend a run until it passes.

Proposed go/no-go gates: >=20% improvement in controlled mixed result median wall time; >=20% improvement in primary real mixed p95 only if the required successful sample count is met; <=5% regression in isolated result median; <=10% regression in monitor completion median and total parent + child CPU. Require no worse protected rejection rate, no new timeouts/leaks and no weakening of authority/evidence assertions. Fix an absolute combined-memory budget from P0 before production; do not describe parent CPU reduction as total CPU reduction. These are proposed targets, not measured gains or a guarantee that every request falls below 6.5 seconds. A miss or memory/lifecycle failure means defer P1 and retain current behavior.

Correctness matrix: old/unselected and same-length/time-restored tamper, invalid typed payloads, head/provider/formula/row/hash/canonical mismatch, missing/reordered/extra input, retention/pin/publication changes, activation/generation/configuration/progress changes, date/target/90-second boundaries, near-limit payload and byte fallback, leader/follower/all departures, cancellation before submission/during IPC/validation/return, repeated cancellation, child failure/hang, stop/checkpoint/close races and cleanup failure retaining the correct storage pause. Mutations deleting the canonical/integrity, authority, flight-binding, child-completion and drain gates must be caught. Browser validation must cover result/provenance/refresh/return-to-monitor and live heartbeat/reconnect, with complete responses and no business writes.

## AMC07. Alternatives and ordering

| Alternative | Assessment |
|---|---|
| Add threads, raise waits or increase evidence/read limits | Does not remove GIL-bound work and can increase contention; excluded |
| Global serialization or result-first CPU priority | Can move delay to monitor/queued results and starve checks; not the default next slice |
| Share whole health/authority or retain completed proofs | Changes freshness and accepted sharing boundaries; excluded |
| Repeat rejected Decimal memo or result canonical-byte P1 | Existing experiments failed their gates; no new evidence justifies reopening them |
| Pure index validator in 1 process | Recommended feasibility boundary; plausible concurrency benefit, with unmeasured IPC/memory/lifecycle costs |
| Move authority I/O after finer attribution | Separate conditional work; retain loop ownership and explicit consistency contract |

Python documents the GIL limitation of CPU-heavy threads and the isolation offered by separate processes: [threading](https://docs.python.org/3.14/library/threading.html). Running futures cannot be cancelled by ordinary executor cancellation, and process work has serialization/import constraints: [concurrent.futures](https://docs.python.org/3.14/library/concurrent.futures.html). Abandoning a thread waiter does not stop its physical work: [AnyIO threads](https://anyio.readthedocs.io/en/stable/threads.html). These support the boundary choice and ownership requirements, not a performance forecast for this application.

## AMC08. Analysis verification and preserved work

The analysis recomputes 80 request-to-worker links, all complete-response hashes, the outlier partition and its overlapping monitor ancestry from the preserved portable evidence. The original evidence remains unchanged. The new observations retain raw related records, all sample summaries, source fingerprints and limits; no new service/browser/performance experiment is claimed. Check paired IDs, thresholds, technical tokens, local links, JSON validity and whitespace before delivery. Existing `.tmp/` and parallel AI extraction/daily-inventory work are untouched. Only this paired proposal and sanitized offline-analysis artifact are added; no production tests or browser rerun is needed for these documentation-only changes.

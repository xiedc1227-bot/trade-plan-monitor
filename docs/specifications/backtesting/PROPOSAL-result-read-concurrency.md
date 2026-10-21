# Result-read concurrency diagnosis and optimization proposal

Status: Analysis only, 2026-10-21. Baseline: `cd5113b`. [Chinese review copy](PROPOSAL-result-read-concurrency.zh-CN.md). No application code, running service configuration or historical evidence was changed. Read-only experiments used SQLite `mode=ro` and `PRAGMA query_only=ON`; candidate substitutions existed only in isolated measurement processes.

This is the historical analysis record. Statements about unchanged application code refer to that analysis phase. Approved implementation and final measurements are recorded in the [specification](SPEC-result-read-concurrency.md) and [verification](../../verification/result-read-concurrency-2026-10-21.md).

## RRC01. Findings and measurements

Sample: the same completed run, 39 frozen day files and 2,961 audit events. The complete API response is 15,559 bytes. Measurements are local observations, not production latency guarantees; profiled times include instrumentation overhead and nested costs must not be added.

| Observation | Evidence | Implication |
|---|---|---|
| A single result remains expensive | Two HTTP reads: 4.789 / 6.127 seconds. Separate unprofiled projection: 5.263 seconds wall / 5.219 seconds CPU. | The expensive path is CPU-heavy, not primarily response transfer. |
| Frozen-file reading has disproportionate temporary allocation | `LoopInputStore._read` requests 295,108,609 bytes per `read`; 41 files total only 3,077,749 bytes. The profiled buffered reads cost 2.389 seconds. | A roughly 281 MiB per-call read size causes avoidable allocation overhead on this Windows/Python environment. |
| Audit projection is the other main result cost | Instrumented `_loop_diagnostics`: 2.792 seconds. The profile records 15,295 canonical JSON calls and roughly 2,260,000 recursive canonical-value calls across the result projection. | Preserve event validation; reduce repeated representation work only after the allocation fix is measured. |
| Result SQL and response validation are comparatively small | SQL execute/fetch cost 0.0283 seconds across the instrumented and profiled projections combined. Route response validation: 0.0007 seconds; JSON encoding: 0.0001 seconds. | New result indexes or weaker response validation would target the wrong cost. |
| Different results queue | Two different-run pairs finished around 3.981 / 9.074 and 3.896 / 8.461 seconds. | The existing result reader serializes physical result projections. |
| Monitor projection is an independent expensive reader | `list_latest_market_index_snapshots` reads 1,928 historical snapshot payloads using 1,929 SELECTs to return 5 current snapshots: 3.728 seconds wall / 3.672 seconds CPU. | A historical fan-out and repeated integrity/canonical checks compete with result projection. |
| Mixed reads slow each other | Result + dashboard: 9.373 / 18.596 seconds, then 11.741 / 9.307 seconds. Light service probes remained around 31–200 ms. Python reports GIL enabled. | CPU contention is supported; a universal event-loop deadlock or one shared SQL write lock is not supported by these observations. |

The current monitor database has no plan-version/active-plan rows, so scanning a large plan library is not the explanation for this sample. It has 1,928 index heads and 3,599 immutable index snapshots. The profile identifies index snapshot validation and canonical serialization as the monitor hot path.

## RRC02. Amplification and existing protections

- `BacktestResultReadThread` already isolates expensive reads, coalesces identical in-flight keys and physically drains cancelled observers. It admits at most 8 readers and permits up to 60 seconds of queue waiting. Merely adding another instance of these mechanisms is not a new optimization.
- Same-run HTTP pairs finished together at roughly 8.445 and 5.202 seconds. Cancelling one read observer at 0.265 seconds and retrying returned the same report in another 3.679 seconds. These observations are consistent with existing sharing; they do not establish exact physical invocation counts.
- `runtime-status/App.vue` watches `route.fullPath`; `monitor.navigation()` invalidates the protocol epoch, cancels the snapshot observer and starts another dashboard read. Backtest filter/page/tab changes therefore trigger monitor work unrelated to the selected result. Browser cancellation does not prove the server's already running work stopped.
- A real browser trace of list → result → provenance → summary completed with 1 result-detail request but 8 dashboard requests. 7 dashboard observers were aborted; the last was still pending when the bounded observation ended. The result request took 29.550 seconds, including almost all of that time before response arrival. A dashboard observer reached the 20-second timeout and retried. This trace had zero business writes and zero page errors. One service read also took 1.159 seconds during the initial burst; the small controlled HTTP probe range above is not a universal responsiveness guarantee.
- `RuntimeStatusReadService.get_health()` assembles the complete monitor projection. WebSocket heartbeats call this health path on the default 20-second cadence. Authority changes may cause up to 2 projection attempts. Multiple tabs/connections and navigation can multiply the same expensive work.
- A 30-second result UI timeout and a 60-second server queue limit are different limits. Raising either deadline does not improve throughput. Thread count increases can worsen CPU and temporary-memory contention.

## RRC03. Isolated candidate result

Only `payload = file.read(_MAX_OBJECT_BYTES + 1)` was substituted with a 64 KiB chunked reader in an isolated process. Existing root/link/size checks, domain-separated hashes, typed decoding, canonical equality, input/report bindings and event-set validation stayed in the execution path. The production reader was not edited.

| Alternating warm full projection | Existing, seconds | Candidate, seconds |
|---|---|---|
| 1 | 4.4478 | 2.0983 |
| 2 | 4.3525 | 2.1009 |
| 3 | 4.2942 | 2.0679 |
| Median | 4.3525 | 2.0983 |

This is a 51.8% reduction in the measured full projection median. The complete response objects, including report identity and diagnostics, matched in all comparisons. It is not an API/concurrent-load acceptance result.

A 506-byte day-file read peaked at 295,243,578 traced Python bytes with the existing read size, versus 198,540 bytes with chunking. These are isolated Python allocation peaks, not process RSS or a per-request production memory guarantee. Seven reader-boundary cases matched: empty, one byte, below/exact/above the maximum, bad hash and missing file. The empty-byte case tests only the byte reader; downstream typed artifact validation still applies. Symlink/junction, concurrent file replacement/growth and full corruption/retention regressions remain required before implementation acceptance.

## RRC04. Recommended delivery order

| ID | Priority | Change | Integrity and validation boundary |
|---|---|---|---|
| RRC-T01 | P0 | Replace the giant requested read length with bounded 64 KiB chunking. Stop at EOF or the existing maximum plus one byte. | Keep `_MAX_OBJECT_BYTES` unchanged; reject oversized data before decoding; compute the same domain-separated digest on all returned bytes; retain every downstream check. Promote the isolated candidate into regression-tested code only after approval. |
| RRC-T02 | P0 | Scope monitor navigation refresh to meaningful monitor surfaces, rather than every backtest query/tab change. | Keep protocol mismatch handling, command preflight, generation/sequence checks, observation expiry, reconnect and visibility recovery. Entering a monitor action surface must establish fresh authority before actionable UI appears. Never relabel an old snapshot as current. |
| RRC-T03 | P1 | Replace monitor historical N+1 reads with bounded batched head/payload reads; reduce duplicate canonical work within that one verified traversal. | Preserve validation of all candidates, missing-payload failure and the existing `snapshot_rank`: cutoff, LIVE preference, fact-request count, observation time, hash. Use a left join or equivalent missing-row check; an inner join must not silently hide a corrupt/missing head. Do not substitute maximum revision or SQL metadata ordering for verified payload semantics. |
| RRC-T04 | P1 | Measure and, if still necessary, coalesce equivalent concurrent monitor projections with bounded in-flight ownership; reuse verified representations within one read. | Bind authority generation/configuration/token, relevant committed identities and data fences; retain the post-read authority check and bounded retry. A cancelled observer must neither cancel other readers nor release physical work early. This is not a cross-request TTL cache. |
| RRC-T05 | Later, only if measured necessary | Consider a separate CPU process or a reusable verified typed-object cache. | Process ownership, shutdown, errors and snapshot consistency need their own design. A cache must re-read and verify current bytes/identities before reusing typed objects, and must not conceal missing/corrupt evidence or retention/pin changes. |

Start with RRC-T01 and RRC-T02, remeasure, then decide RRC-T03/RRC-T04 scope. Do not immediately expand the worker pool, raise timeouts or introduce a long-lived result cache. The lower-risk changes remove measured work and unnecessary requests first.

## RRC05. Evidence-integrity acceptance gates

1. Keep typed schemas, canonical Decimal/time representation, input/plan/dataset bindings, artifact domain hashes, row envelope checks and event-set completeness/order/digest checks. No `reportHash` or original artifact bytes change.
2. Keep summary/availability/pin/retention facts consistent with the read snapshot. In-flight sharing keys must account for mutable revisions where relevant; do not reuse a stale revision merely because `runId` and pin boolean match.
3. Tamper after a prior successful read and verify failure on the next read: same-length/same-timestamp replacement, damaged day/report/event payload, foreign row identity, missing file, truncated/oversized file and missing index payload. Prior validation or a matching filename is insufficient.
4. Keep missing, expired, unrecorded and unavailable evidence distinct. Browser reads never download data, resume a task or rewrite stored evidence.
5. Historical index corruption currently detected during candidate traversal must remain detectable. Selecting only the newest row without preserving this contract would weaken validation and is outside this proposal.

## RRC06. Measurement and rollout gates

- Use the same 39-day / 2,961-event sample; alternate warm baselines/candidates and separately label cold reads. Compare exact responses and every evidence identity, not just visible PnL.
- Candidate target for RRC-T01: full verified projection median at most 2.5 seconds and at least 30% below the comparable baseline. This target is scoped to this sample/environment, not a universal SLA.
- For RRC-T02, count dashboard requests during initial route normalization and backtest list/result/tab/filter navigation. Backtest-only query changes should add zero dashboard reads; monitor re-entry and expiry must still demand fresh authority.
- For RRC-T03, reduce 1,929 index SELECTs to bounded batches while retaining the same 1,928 candidate validations and 5 selected identities for this snapshot. Report SQL and validation CPU separately.
- Repeat single read, same/different-run pairs, result+dashboard, observer cancellation/retry and browser navigation. Record queue wait, physical execution, validation, serialization, CPU, allocation/RSS and lightweight service responsiveness separately. Do not publish p95 from two samples; a later performance gate needs sufficient repeated measurements.
- Run existing artifact/input/publication/tamper/retention/pin tests, result-thread sharing/drain tests, monitor authority/protocol/heartbeat tests and real-browser navigation checks before shipping. Analysis experiments are not a replacement for these checks.

Local measurements are retained under `.pytest_cache/result-read-concurrency-20261021/`: `http-measure.json`, `store-profile.json`, `monitor-profile.json`, `io-experiment.json`, `io-boundary-check.json` and `browser-trace.json`, with their one-off scripts. They are ignored local evidence, not production code or portable regression fixtures. No source changes are proposed as already implemented; the next step is a paired specification/task update for approved implementation scope.

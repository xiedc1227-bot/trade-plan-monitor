# Validator lifetime and independent scan admission

## VLS01. Decision

Continue isolated P0 work on two separately measured candidates: validator representation lifetimes and bounded SQL scan concurrency. P1 remains NO-GO. This analysis follows `72bd925`, changes no production code, and authorizes no implementation or push. Prepare paired specifications/tasks before implementation. Preserve existing and parallel AI extraction/daily-inventory work.

The [previous report](../../verification/evidence-representation-2026-10-22.md) still fails valid-large-input availability, concurrent CPU/latency and native memory bounds. New [sanitized evidence](../../verification/evidence/2026-10-23-validator-lifetime-analysis/analysis.json) contains measurements, limitations and reproducible probe sources. Its frozen monitor database remains byte-identical. The observations below identify candidates, not a passed integration gate.

## VLS02. Where memory overlaps

The current path is `RawIndexCandidate.decoded()` → `MarketIndexSnapshot.model_validate_json()` → `canonical_value()` → domain hashes → final canonical serialization → stored literal/scalar comparison → ranking. The raw flight bytes remain owned during proof. Decoded JSON, parsed models and a normalized tree coexist. Domain serialization adds temporary strings, UTF-8 encodings and concatenated hash input. The final canonical string is produced after domain hashing; these separate phase peaks must not be added together.

A process-local boundary probe used the supported 16,472,833-byte fixture, with 480 bars and 8500 decimal digits. The unchanged validator accepts it. The JSON includes a Chinese display name: the decoded string occupies 32,945,708 bytes for 16,472,825 characters. It is not an all-ASCII JSON document despite its predominantly ASCII decimal content.

| Boundary | Traced live bytes | Cumulative peak bytes |
|---|---:|---:|
| Before model parsing | 32,946,766 | 32,947,060 |
| After model parsing | 57,247,373 | 98,838,172 |
| Before model dump | 57,247,913 | 98,838,172 |
| After model dump | 57,475,187 | 98,838,172 |
| Before first domain encoding | 73,973,570 | 98,838,172 |
| After snapshot-domain encoding | 106,921,559 | 115,068,947 |
| At snapshot SHA-256 entry | 90,449,062 | 156,340,002 |
| After full validation/ranking | 7,841,664 | 156,340,002 |

The dump boundary increases live memory by only 227,274 bytes in this fixture. Decimal normalization and whole-document representations matter more than that dictionary alone. The largest peak, about 149.10 MiB, occurs between snapshot-domain encoding return and hash entry, while constructing hash input. Attribute the exact split among encoding temporaries, Unicode caches and concatenation with finer/native profiling before assigning byte savings. Parsing already reaches about 94.26 MiB; removing the final string alone cannot solve every peak.

These are Python traced allocations after the raw fixture was built, with wrapper overhead. They exclude prebuilt raw input and do not bound native allocation or process working set. The normalized bar lists and snapshot payload dictionary largely share references; counting each as a deep copy would overstate memory. Selected latest models legitimately remain in the output. The loop may additionally retain a preceding candidate/model while the next is validated; test that lifetime explicitly, including exception tracebacks.

## VLS03. Sequential CPU costs

The actual monitor requests `ALWAYS_ON_INDEX_CODES`: 5 indexes and 2008 historical candidates in the frozen fixture. An initial 1628-row dashboard-only probe is excluded from the published timing evidence. The aligned probe uses independent explicit read transactions and 3 rounds; the table reports medians without profiling enabled.

| Timed region | Wall seconds | Thread CPU seconds |
|---|---:|---:|
| Complete metadata preflight | 0.0269 | 0.03125 |
| Ordered payload scan, excluding preflight | 0.0389 | 0.03125 |
| Ordered payload scan and exact comparison, excluding preflight | 0.0464 | 0.046875 |
| Unchanged full validator/ranking, excluding SQL | 1.8468 | 1.84375 |

Scan and scan-plus-comparison are alternative measurements, not additive phases. Windows CPU sampling is quantized. A separate instrumented pass identifies repeated work: 2008 shapes plus 2008 `dataclasses.replace()` calls, 4016 shape constructions, and 2008 exact comparisons and retained-size calculations. Comparison still checks all 19 selected fields and storage types. Avoid treating the few-millisecond sequential difference as the explanation for seconds of concurrent latency.

The full-validator profile records 1,236,442 `canonical_value()` calls, 447,344 `canonical_decimal()` calls and 892,736 Decimal `as_tuple()` calls. Model validation also enforces Decimal expansion and bar relationships. This makes normalization/type dispatch a later CPU candidate, but does not authorize dropping either validation layer. Profile cumulative times overlap and are distorted by instrumentation; do not divide them by the unprofiled 1.8468-second measurement.

## VLS04. Concurrent scans amplify CPU

Without a physical validator, 8 simultaneous independent preflights already consume a median 4.15625 CPU seconds and 0.7118 wall seconds, versus 0.03125 CPU seconds for 1 preflight. Complete metadata-plus-payload-plus-comparison batches consume 7.015625 CPU seconds and 1.3345 wall seconds. Thus proof execution is not necessary to reproduce the scan-side amplification. These measurements cannot be added to prior full-cohort timings: the scheduling and overlap differ.

A separate sensitivity probe keeps 8 requests, each with its own complete transaction, metadata preflight and exact payload comparison. Only simultaneous scan count changes. Across 3 alternating rounds, every setting completes 24/24 comparisons successfully.

| Simultaneous scan slots | Batch wall median, seconds | Process CPU median, seconds |
|---:|---:|---:|
| 8 | 1.3226 | 6.765625 |
| 4 | 0.8226 | 2.515625 |
| 2 | 0.5361 | 0.921875 |
| 1 | 0.5893 | 0.59375 |

Prefer evaluating 1 and 2 slots before micro-optimizing equality. In this sample, 2 slots give lower latency and 1 uses less CPU; this is not enough to select a production default. SQL/Python boundary transitions, GIL reacquisition, native allocator/mutex contention and scheduling remain hypotheses for the precise amplification mechanism. The probe establishes sensitivity to concurrency, not attribution to a specific lock.

The sensitivity gate is deliberately acquired before opening its transaction and uses independent experimental budgets with prebuilt uncharged leader input. It does not exercise the shared flight, authority checks, global byte ledger, cancellation or cleanup failures. Production cannot simply copy this wrapper around the full read/flight: a leader holding the only slot while waiting for funded followers would deadlock.

## VLS05. Memory candidate sequence

1. **Reduce representation overlap without changing the model contract.** Trial direct UTF-8 byte input to the existing model parser while retaining the original SQLite TEXT/BLOB distinction and strict invalid-input behavior. Compare against the old decode-plus-parse path. Remove only demonstrably unnecessary decoded text and prior-iteration references; retain selected output models and raw proof ownership. Do not replace JSON validation with `model_construct()`, `json.loads()` plus permissive validation, or a latest-only path.
2. **Remove whole-document hash copies.** First trial domain-separated incremental hash updates instead of concatenating the full domain and payload. Then evaluate incremental canonical serialization for all domain hashes and a chunk-by-chunk comparison with the stored literal, including exact end-of-input. Preserve byte order, escaping, separators, sorted keys, Decimal formatting, datetime precision, request/bar ordering and every existing formula/hash check. Keep the existing string-producing public API for callers that need it; specify any private proof interface separately.
3. **Bound the producer, not just its consumer.** `JSONEncoder.iterencode()` yields pieces but does not promise a maximum piece size. Slicing an already allocated large token does not prove preallocation safety. Charge encoder tokens, UTF-8 expansion, sort references, comparison buffers, model/native parser work and retained generations to their existing accounting categories. A bounded emitter needs maximum-token evidence or a correctly specified streaming scalar encoder. Never move previously charged input text outside the 64 MiB ledger to make the gate pass.
4. **Only then consider direct model traversal.** A schema-aware canonical walker could avoid the normalized tree and repeated generic dispatch, but is a larger equivalence change. Cover serializers, aliases, field additions, exact model types, optional values and all scalar policies before considering it. Prefer deferring it if the earlier changes suffice. Preserve finite/expansion checks; do not add an unbounded cross-request normalization cache.

Each candidate is measured independently before combination. Small incremental hash updates can increase Python call/GIL overhead, and a Python streaming encoder can lose the current fast encoding path. Evaluate buffer size under the existing byte budget; memory reduction alone is not a CPU win. The parser and native allocation may still prevent the large row from fitting. Keep P1 blocked if supported input still fails rather than increasing limits or calling a failed-admission path a successful fallback.

## VLS06. Independent scan CPU admission

Introduce an experimental scan permit separate from reader admission and physical-proof admission. Preserve 8 admitted readers, 1 physical validator and 1 queued owner. Initially compare fixed 1 and 2 scan slots, not an adaptive scheduler. Each request still performs its own complete metadata sizing and literal comparison in its original transaction; no shared preflight certificate, common transaction or completed-proof cache.

Define the resource order before implementation. Acquire/reserve all byte leases required by a SQL stage before its scan permit, outside coordinator/database-cleanup locks. Once granted, that stage must not wait for further byte resources. Close its cursor and release the permit before waiting for flight publication, funded-cohort completion, a queued owner or a proof result. A leader must release the payload-scan permit before waiting for funded followers. Reservations and pending followers remain bounded; starvation, old-generation borrowers and leader progress require explicit tests. Do not hold a scan permit across the whole `Flights.run()` call.

Permit waits use the original deadline and cancellation/stop signal. They do not refresh authority, observation time or proof eligibility. Preserve existing transaction boundaries when adding the permit; measure the WAL/transaction lifetime effect of waiting inside a read transaction. The earlier acquire-before-transaction probe is not evidence that moving production authority or transaction boundaries is safe.

After measuring admission in the complete cohort, consider eliminating the second shape allocation, combining fixed-field sizing loops, or byte-admitted fetch batches. Keep all type, cardinality, order and actual-size checks. Do not replace exact content comparison with stored hashes, metadata equality or Python tuple equality that conflates scalar types. Any batched fetch requires bytes reserved before fetch, including driver lookahead and simultaneous previous/current rows; fixed row-count buffering is insufficient.

## VLS07. Integrity and lifecycle invariants

Every request retains independent before/after authority checks, activation reread, its original transaction/observation clock and 2-attempt behavior. Preserve the 15-second wait deadline and 90-second eligibility boundary. Sharing is limited to a still-running pure proof after full equality. Validate all historical candidates, missing payloads, head identity, scalar/storage types, canonical literals, bar/request/snapshot hashes, per-fact formula hashes and existing model constraints. No trusted stored hash or latest-only shortcut.

Cancellation removes an observer or unstarted admission; it does not refund live SQL buffers, raw pins, parser/encoder work or submitted worker transport. Retain ownership until actual physical drain and `DRAINED` or supervised worker exit/bridge cleanup as applicable. A follower cannot cancel another reader's proof. Cursor/worker cleanup failure retains byte debt and the storage fence across generations; a semaphore release must not falsely declare storage cleanup complete. Stop wakes both byte and scan waiters without reopening admission.

Required cases include valid near-limit ASCII/Chinese/supplementary Unicode rows, huge Decimals, large non-JSON columns, old/new rows and exception retention; malformed UTF-8/BLOB/NULL/numeric storage; every hash and scalar tamper, missing/extra/reordered rows, noncanonical escapes, duplicate keys and trailing content. Test producer chunk boundaries and memory before allocation, not only final output equality. Cover equal/changed inputs, fast proof/slow comparison, late arrival, deadlines on both sides of the boundary, authority changes while waiting, follower/leader cancellation, stop, and cursor/worker cleanup failure. Deterministic equal overlap must retain 1 proof and 7 joins without accepting completed proofs.

## VLS08. Delivery and decision gates

1. **P0-A contract and attribution:** paired specifications/tasks; reproduce the full 2008-row scope; trace parse/normalize/encode/hash/literal comparison separately and SQL execute/fetch/sizing/compare/permit waits with thread CPU. Capture native allocation, parent/child peaks, user/kernel CPU and resource ownership. Keep instrumented attribution separate from timing acceptance.
2. **P0-B validator lifetimes:** trial byte parsing, reference release, incremental domain hashing and bounded canonical comparison in separate variants. Differential-test the complete old validator on valid and tampered input. Specify a new walker only if needed and justified by measurement.
3. **P0-C scan admission:** compare 8, 2 and 1 scan slots in the complete funded cohort under the same global ledger. Verify the wait graph, independent authority, physical drain, cleanup failure and valid large/mixed workloads before considering combined results. Only then assess sizing/fetch micro-optimizations.
4. **P1 decision:** retain the frozen 64 MiB input limit, 768 MiB working-set and 2560 MiB private-commit experimental ceilings, native/ownership proof and availability gates. Sampling is not a hard-bound proof. Restore process transport only after prerequisite thread correctness/availability gates pass. Any failed hard gate stops fixed performance acceptance.

For passing candidates retain 10 A/A pairs and 20 ABBA/BAAB blocks, unchanged/changed 1/2/8-reader inputs, mixed result reads, late arrivals and fallback. Retain the process-integration requirement of at least 20% mixed-result improvement, at most 5% isolated-result regression and 10% monitor/total CPU regression, with no worse rejection/timeout rate. Report all attempts and equivalent completed work. Real-owner/browser validation follows an approved integration candidate, with 100 attempts per variant and no p95 claim below 100 successes.

## VLS09. Sources and analysis limits

Python documents incremental [hash updates](https://docs.python.org/3.14/library/hashlib.html#hashlib.hash.update), [JSON encoding pieces](https://docs.python.org/3.14/library/json.html#json.JSONEncoder.iterencode) and the scope of [traced Python allocations](https://docs.python.org/3.14/library/tracemalloc.html). Pydantic accepts byte input through [model_validate_json](https://pydantic.dev/docs/validation/latest/api/pydantic/base_model/#pydantic.BaseModel.model_validate_json) and explains the extra intermediate dictionary in [parse-then-validate workflows](https://pydantic.dev/docs/validation/latest/concepts/performance/). These document APIs, not application equivalence or memory bounds.

The measured runtime is Python 3.14.7, Pydantic 2.13.4, SQLite 3.50.4 and SQLAlchemy 2.0.52. Only proposal documents and sanitized analysis evidence are added. No service restart, runtime/test change, browser acceptance, commit or push occurs. The measurements are 3-round diagnostics and boundary probes, not proof that the previous real-page tail latency is fixed. Precise native contention attribution, enforceable memory bounds and combined lifecycle correctness remain open.

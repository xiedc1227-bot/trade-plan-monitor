# Native allocation coverage and physical ownership

## NOA01. Decision

After `e688dba`, artifact reproducibility is established for the measured R/I configurations; native bounds and legal-large-row admission are not. Next, qualify Python and the actual SQLite allocator, then reconcile physical ownership and backing allocations before revising reservations. Keep production integration and P1 disabled. This proposal and its [tasks](TASKS-native-owner-accounting.md) authorize no runtime replacement or budget reduction.

The [previous report](../../verification/native-artifact-determinism-p0-2026-10-23.md) remains the performance baseline. This analysis adds [counter evidence](../../verification/evidence/2026-10-23-native-owner-accounting-next/analysis.json) from a fresh disposable process using only an in-memory database, with 3 sequential rounds. No allocator was replaced, service restarted, production database accessed, or application code changed. Exclude AI extraction, daily inventory and README changes.

## NOA02. Why the gates still fail

- `native_alloc_observer.rs` counts process-wide Rust requests, not Python objects, SQLite buffers, backing-heap capacity or physical owners. Its lifetime peak cannot certify a request envelope.
- `native_allocation_child.py` constructs input and runs the independent reference validator before candidate timing, retaining the reference result during candidate validation. The allocator peak therefore includes reference/input history and overlapping expected output. Later SQL fixture preparation also occurs in that process. Keep those historical measurements; do not relabel them as isolated candidate peaks.
- `ByteScan._byte_shape` removes driver Unicode storage but deliberately retains both generations and worst-case validator decoding. SQL still requests `197697036 B` / `145472808 B` against `67108864 B`, before any payload query. Those are availability failures, not measured OOMs.
- The earlier hypothetical decoded-text removal still left a `69195268 B` progress bundle, exceeding the input limit by `2086404 B`. Native coverage alone does not eliminate that overlap or prove the rest fits.
- Existing application leases own reserved categories and cleanup debt; they do not map allocator pointers to owners. Closing a cursor or returning from validation cannot prove that returned bytes, models, errors, arenas or caches have been physically released.

## NOA03. New observed boundary

The actual runtime is CPython `3.14.7`, GIL enabled, with SQLite `3.50.4`. Loaded module identity, source ID, compile options and DLL/driver hashes are retained in the evidence. Options include `SYSTEM_MALLOC`, `OMIT_AUTOINIT`, `THREADSAFE=1` and `DEFAULT_MMAP_SIZE=0`; do not infer that memory mapping can never be enabled.

| First round phase | SQLite current bytes | Python traced current bytes |
|---|---:|---:|
| Python-only allocation of 8388608 bytes | 0 | 8388929 |
| In-memory SQLite table with an 8388608-byte BLOB | 9072792 | 2808 |
| Python row fetched and retained | 9072792 | 8392247 |
| Connection closed, row still retained | 0 | 8390025 |
| Row released and collection completed | 0 | 1608 |

SQLite's first-round high-water mark reached `17477816 B` during fetch. It is not simultaneous with the Python sampled peak and must not be added to it as an exact total. Later rounds retain the SQLite lifetime high-water mark. Tracing includes probe bookkeeping and excludes some native memory; this is a coverage/lifetime counterexample, not a production profile, allocator-hook qualification or all-input bound. An in-memory table is not the real file-backed workload.

The matched [CPython cursor source](https://github.com/python/cpython/blob/v3.14.7/Modules/_sqlite/cursor.c) creates a Python bytes object from SQLite BLOB data. Therefore returning bytes avoids Unicode decoding but is not an end-to-end zero-copy promise. The observed connection/row split requires distinct owners, not an early refund at cursor close.

## NOA04. P0-A: controlled launcher and Python coverage

Build a small native launcher/observer in an isolated directory, binding Python DLL/import library, SQLite DLL, driver, core R/I, CRT and observer identities to the run. First prove the launcher changes no valid output, canonical bytes or failure categories with observation disabled. A changed runtime or observer requires separate reproducibility checks; do not reuse the old I identity.

Use native wrappers around the existing RAW/MEM/OBJ allocator functions and observe arena allocation/free. Prefer installing after preinitialization and before full interpreter initialization; account for earlier allocations as baseline ownership. Keep the actual allocator policy. All wrappers must be thread-safe and preserve zero-size/reallocation/failure semantics. Do not use Python callbacks or switch `PYTHONMALLOC` to manufacture simpler numbers. The matched [CPython memory contract](https://github.com/python/cpython/blob/v3.14.7/Doc/c-api/memory.rst) requires wrapping the existing allocator after full initialization. Its default small-object arenas and larger RAW fallbacks require nested-call and arena deduplication.

Test small/dense objects, large bytes, strings, Decimal normalization, errors and cycles. Distinguish logical object release, retained pools/arenas and actual backing release. `tracemalloc` is a cross-check only. A pointer table must identify pre-hook allocations rather than silently treating them as current-proof frees. If the public hooks cannot establish arena membership/retention, stop the bound claim and evaluate a narrowly scoped version-matched CPython instrumentation build separately; do not claim coverage by disabling arenas.

## NOA05. P0-B: actual SQLite coverage

Resolve the exact DLL that the driver will use, install a native wrapper through `SQLITE_CONFIG_GETMALLOC` / `SQLITE_CONFIG_MALLOC` before SQLite initialization, then verify that the imported driver uses that same module. Retain and delegate the full `sqlite3_mem_methods` contract, including sizing, rounding, initialization and shutdown. The [SQLite contract](https://www.sqlite.org/c3ref/mem_methods.html) describes these methods; [configuration rules](https://www.sqlite.org/c3ref/c_config_covering_index_scan.html) require checking return codes and initialization order.

Do this before importing `_sqlite3` or application modules: the matched [module initialization source](https://github.com/python/cpython/blob/v3.14.7/Modules/_sqlite/module.c) calls `sqlite3_initialize`. A late-install negative control must fail. Never call shutdown/reconfiguration in an active service, and never count a separately loaded SQLite library as driver coverage.

Observe the actual metadata query, ordered payload query, TEXT-to-BLOB expression, column conversion, statement cache, page cache, lookaside, sorting/temp storage and connection disposal. Keep SQL and snapshot semantics unchanged initially. Cross-check global/connection statistics where available, without interpreting SQLite counters as driver/Python coverage. Assign cache backing to connection/pool owners and suballocations to logical users without double charging. Identify externally supplied page/lookaside buffers and any mapping/VFS/CRT allocations outside the selected hook. Default mmap settings alone do not prove absence. Test real file-backed fixtures after the small canary.

## NOA06. P0-C: physical owner ledger and reconciliation

Maintain separate logical-domain and deduplicated backing ledgers. Do not sum Rust requests, Python objects, arena capacity and SQLite backing as independent memory when they describe the same allocation. OS working-set/private-commit readings are an independent envelope check; an unexplained difference remains an unqualified remainder, never a measured coefficient to subtract.

| Owner | Holds | Release or funded transfer boundary |
|---|---|---|
| Runtime/pool | Baseline schemas, arenas, connection/statement/page caches | Proven pool release or an explicitly funded retained pool |
| Independent scan | Metadata, SQL step/conversion, driver row and follower comparison | Cursor and row references released; retained cache stays charged |
| Physical proof | Raw input, parser/model/error graph, normalized form, encoder scratch, transport | Physical completion plus cleanup; selected results transfer with funding |
| Returned result | Selected models and serialized/exported output held by observers | Last holder releases; completion of proof alone is insufficient |
| Cleanup debt | Cyclic failures, failed close/drain, unresolved buffers | Actual cleanup acknowledgement; failure fences later generations |

Use a native preallocated bounded table keyed by allocation identity and reuse generation, storing domain, physical owner and size. Thread-local entry context assigns allocation ownership; free/realloc uses the saved owner, including cross-thread frees. Pass owner tokens explicitly at thread/child handoffs; `ContextVar` or thread ID alone is not enough. Shared immutable aliases refer to one allocation with holder counts; copies in different processes are separate allocations. Pool arena sharing must not be assigned entirely to its first request or erased when that request ends.

Charge observer tables/buffers before use. No hook performs Python callbacks, dynamic logging or unbounded allocation; record overflow/unknown ownership/accounting loss as an invalid run and retain unresolved debt. Hooks must not unwind or block on the application budget. Reallocation reserves possible old/new overlap before the backing call, preserves old ownership on failure, and transfers only after success. Cleanup/owner locks have an explicit order; no callback may reenter a coordinator lock held across allocation.

First move reference validation and fixture construction into separate oracle/setup processes. Compare complete outputs and canonical streams outside the measured candidate; hashes identify fixtures but never replace runtime evidence comparison. Measure cold initialization separately from warm retained pools, retaining both in the process envelope. Validate result transfer, follower departure, late cross-thread free, pointer reuse, unknown ownership and cleanup failure before attempting new admission math.

## NOA07. P0-D: derive and test a genuinely funded large-row path

Only after coverage/ownership gates pass, derive source-supported bounds for simultaneously live allocations in each phase. Use metadata available before allocation and proven maximum schema/shape expansion; observed peaks alone cannot establish an all-input maximum. The input budget remains `64 MiB`, aggregate working set `768 MiB`, private commit `2560 MiB`; do not move input copies into another category to manufacture fit. Observer storage and retained pools remain included in the proper aggregate envelope.

Reserve a complete progress bundle atomically before payload, then subdivide it across SQL capture, parsing, normalization, encoding and cleanup. Never hold a raw lease while waiting for an unfunded encoder upgrade. Bind admission to the exact qualified uninstrumented runtime; evidence for I cannot lower the installed wheel's budget automatically.

Optimize only proven coexistence: release previous driver/raw generations before advancing where ownership permits; reuse identical immutable bytes; bound canonical-encoder batches with the existing C fast path; serialize only the unfunded portion of concurrent scan/comparison work. Do not omit history, skip follower equality, replace full validation with token counts, or stream SQL chunks into a parser that still needs a whole row without counting that reconstruction. If one row cannot fit even in a completely validating fallback, record availability failure and keep P1 disabled.

## NOA08. Acceptance and stopping rules

| Stage | Required evidence | Stop condition |
|---|---|---|
| P0-A | Pinned launcher, allocator canaries, behavior equivalence | Unexplained Python allocation/arena behavior or runtime identity |
| P0-B | Exact SQLite module, early setup, real-query coverage | Wrong DLL, late hook, external buffer or driver gap |
| P0-C | Per-owner conservation, result/pool transfer, backing reconciliation | Lost events, unknown current-proof ownership, early refund or deadlock |
| P0-D | Source-supported funded path, valid large/dense rows, bounded concurrent reads | Oversize row, worse refusals/timeouts, unbounded native remainder |
| P1 | All previous gates and real service/browser comparison | Any unresolved gate |

Retain the [BIR08 contract](PROPOSAL-native-build-instrumentation.md): every request independently checks authority before/after and rereads activation. Validate all historical evidence, `19` raw fields/types, dependencies, strict models, canonical UTF-8/EOF, bars/requests/roots/formulas and per-fact values. No completed-proof cache or trusting stored hashes.

Observer cancellation detaches the observer or prevents unstarted work. Physical validation, returned objects and transport remain owned until released or transferred to another funded owner. The last observer leaving does not authorize synchronous-worker termination or debt refund. Allocation-failure injection runs only in supervised disposable children; an aborted child produces no proof, and parent debt remains until exit/transport drain is confirmed. Failed cleanup fences new generations.

Exercise dense errors, legal large rows, old/rehashed tampering, Unicode/NUL/type differences, allocator failures and overflow, result survival after cursor close, retained arenas/caches, cross-thread free, leader/follower/final-observer cancellation, time boundaries and storage cleanup failure. Keep `1/2/8` readers, `1` physical proof, `1` queued owner, `15-second` waits, `90-second` eligibility and `2` attempts; retain small-row `1` proof plus `7` joins.

Failed gates permit `3` diagnostic rounds only. Qualified performance retains `10` A/A pairs, `20` ABBA/BAAB blocks, `20%` mixed-process gain, at most `5%` result and `10%` monitor/total-CPU regression, with no worse refusals/timeouts. Measure observation overhead separately from R performance. Browser acceptance retains `100` attempts and `100` successes per variant before p95 claims, and `20%` mixed-p95 improvement. This analysis ran no service/browser acceptance and claims no performance gain.

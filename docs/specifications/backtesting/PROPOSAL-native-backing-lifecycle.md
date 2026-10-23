# Native backing allocation lifecycle proposal

Status update — 2026-10-23: PAUSED at the user's request. Preserve this proposal and all existing experiments as research evidence. Do not advance native accounting, allocator instrumentation or dependent admission work. The active direction is to remeasure current production result/monitor reads and select a minimal optimization with explicit benefit and stopping criteria.

## NBL01. Decision and scope

Planning only, based on `c7ba0d4`. P0 remains `NOT_QUALIFIED`; P1 remains `NO_GO`. First qualify nested-domain identity, startup provenance and in-progress allocation/release accounting; only then derive a different large-row reservation. Correcting an inflated counter is not itself a memory saving. No runtime, allocator policy, input limit or production validation changes are proposed for immediate deployment.

This refines the unfinished coverage/ownership work in the [previous proposal](PROPOSAL-native-owner-accounting.md) and [report](../../verification/native-owner-accounting-p0-2026-10-23.md). It does not mark those gates complete or overwrite other plans. Use the paired [tasks](TASKS-native-backing-lifecycle.md); update the paired specification before implementation. AI extraction, daily inventory and README work remain outside scope.

## NBL02. What the reviewed evidence actually establishes

The [analysis](../../verification/evidence/2026-10-23-native-backing-lifecycle-next/analysis.json) recomputes existing review measurements and fingerprints inspected inputs. It runs no new native experiment.

| Observation | Evidence | Consequence |
|---|---|---|
| Returned row counted twice | After SQL close, an `8388608 B` row leaves owner accounting at `16778428 B`; after row release it is `2524 B`, in all `3` reviewed rounds | RAW and OBJ views cannot be added as distinct backing blocks |
| Unknown releases remain | End-of-child counts are `182`, `182`, `175`, despite no lost records in ordinary rounds | No provenance proof; a missing record is not automatically a startup allocation |
| Error stage includes initialization | Owner retains `15624682–15625406 B`, including `5242880 B` in observed arenas; the stage imports Pydantic and creates TypeAdapter | These values do not prove an error-graph leak or its cleanup cost |
| Observer has a substantial fixed cost | `262144` records occupy `10485760 B` after the generation fix | Fund all bookkeeping; expanding the record layout is not free |
| Admission still refuses before payload | `197697036 B` / `145472808 B` requested against `67108864 B` | Availability remains failed; these are not observed OOMs |

The row snapshots contain probe allocations; domain differences are not exact per-pointer traces. Equality between summed domain and owner totals only regroups the same records, so it is not an independent physical-memory check. Historical child wall medians are `0.266607 s` without hooks and `0.280583 s` with hooks, including startup/imports. They establish neither CPU attribution nor service performance.

Current `release`, `arena_free` and `sql_free` remove ledger entries before calling the underlying allocator. Current `resize` and `sql_resize` register the new allocation only after the call returns. The generation fix prevents deleting a reused address's new record; it does not cover these temporal gaps. It also does not propagate the saved realloc owner into nested callbacks while the underlying call executes.

## NBL03. P0-A: distinguish views from backing blocks

Use separate logical-view, unique-backing and reservation records. Proposed identity fields are `allocation_id`, `generation`, `operation_id`, `parent_operation_id`, `backing_id`, `origin_owner`, `charge_owner`, `epoch` and `state`. A bounded native operation stack correlates callbacks; thread identity is not allocation ownership.

The version-matched [CPython allocation source](https://github.com/python/cpython/blob/v3.14.7/Objects/obmalloc.c) routes unsuccessful small-object allocation through RAW and uses internal allocation/free calls during object realloc. This supports the observed duplicate explanation, but is not proof of the installed binary's complete build provenance.

For a proven OBJ/MEM-to-RAW fallback returning the same allocation, keep the logical views and charge the backing block once. Require the callback relationship, allocator identity, address/range and generation to agree. Do not suppress all nested RAW callbacks: allocator metadata can be a different live allocation. Small objects inside an arena are logical occupants, not additional arena backing. Independently allocated copies, even of identical content, remain separately charged.

Use deterministic native fixtures with a backing allocator that records actual live blocks independently of the observer. Verify alias, distinct nested metadata, cross-thread free, address reuse and wrong-generation retirement. Deliberately remove deduplication and generation matching to demonstrate detection. Passing these fixtures qualifies bookkeeping only, not the actual allocator or CRT envelope.

All maps, pending-operation slots, per-thread stacks and output buffers have declared capacities and checked arithmetic. Capacity/depth/generation exhaustion invalidates the run without changing allocator delegation. Do not grow tables or perform Python callbacks/logging in hooks. Fund new structures before use and retain an explicit accounting-loss condition.

## NBL04. P0-B: startup provenance without hiding unknown memory

Build an inert native launcher first and compare it with the current executable using identical configuration and full outputs. Record Python DLL, SQLite DLL/driver, CRT, core, launcher, observer, allocator configuration, compiler inputs and hashes. Changed artifacts require their own reproducibility/behavior evidence.

Evaluate these installation points sequentially:

1. Wrap after `Py_PreInitialize` and before `Py_InitializeFromConfig`, producing a control with a documented earlier-allocation gap.
2. For the captured compatible configuration, wrap before preinitialization with `PyPreConfig.allocator = PYMEM_ALLOCATOR_NOT_SET`. The [version-matched initialization contract](https://github.com/python/cpython/blob/v3.14.7/Doc/c-api/init_config.rst) expressly permits this case. Use native static/bootstrap storage; do not invoke Python allocation APIs before preinitialization.

Verify wrapper function/context identities after each initialization stage. [Preconfiguration source](https://github.com/python/cpython/blob/v3.14.7/Python/preconfig.c) shows that environment allocator selection and development mode can trigger allocator setup. Detect incompatible settings or overwritten hooks; do not silently disable settings or change allocation policy to pass. Preserve the [allocator contract](https://github.com/python/cpython/blob/v3.14.7/Doc/c-api/memory.rst), including wrapping existing allocators and thread safety.

Maintain separate bootstrap, runtime initialization, schema/cache, proof, returned-result and observer epochs. Transitions never reset live bytes, generations or outstanding operations. Free/realloc consult saved provenance; the current caller does not inherit old storage ownership. Warm pools stay charged across requests. Classify allocations into known pre-hook records, known post-hook records and unresolved records; timestamps alone cannot classify a later unknown free as baseline.

Earlier hooks still do not observe everything: DLL/CRT startup and non-swappable/default or direct allocator paths need a coverage inventory. Retain an unresolved bootstrap liability until a source-supported bound or earlier observation establishes it. Unknown current-proof ownership still fails qualification even if a conservative amount remains charged. Never subtract a sampled startup working set as an all-input bound. If public hooks cannot establish coverage, specify the smallest version-pinned native instrumentation point and its build-equivalence test; do not claim total coverage or replace the service runtime.

## NBL05. P0-C: arena ownership and completed release

Maintain a bounded interval registry with arena address, extent, generation and lifecycle. Associate proven member blocks with that arena without reading arbitrary pool headers. Charge arena capacity to a funded shared runtime/pool owner; keep request occupancy separately. Include free slots, alignment, headers and retained capacity within the arena allocation, and charge separately allocated metadata separately. A request ending cannot refund a shared arena or an allocator free-list entry. Existing arena backing is not added again to the aggregate envelope when logical occupants are reported; input-copy categories remain unchanged.

CPython can retain an empty arena, and the Windows arena callback delegates to `VirtualFree` through a void interface; the source does not propagate its result. [Windows documents a success/failure return value](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualfree). Therefore distinguish callback completion from confirmed OS release. An after-call snapshot alone can also race address reuse.

First retain arena release as pending until the callback returns. For backing-release qualification, capture the native release result and allocation generation at the actual call site in a separately identified instrumentation build, or retain the unconfirmed amount as debt. Do not change allocation policy or infer success from object count becoming zero. Ordinary heap free returning only ends caller ownership; allocator-retained pages still belong to the backing envelope.

Tests cover shared occupancy, last logical object release with retained arena, new request reuse, arena address reuse, blocked release and native release failure. Use barriers to observe the middle of the call. Unknown arenas or unconfirmed release prevent a reduced reservation based on the claimed upper bound; they cannot disappear through a transfer to an unfunded pool.

## NBL06. P0-D: account for operations before they finish

The proposed state machine is `LIVE -> REALLOC_PENDING/FREE_PENDING -> LIVE/RELEASED/DEBT`. At operation start, preserve the old allocation identity, size and owner in a separate bounded pending record. Move its existing charge without refunding it. Permit a new generation at a reused address while the old generation remains pending. No ledger or application budget lock is held across an allocator call.

For realloc, reserve a source-supported upper bound for additional destination/scratch capacity before delegation, while retaining the old capacity. Nested callbacks inherit the operation's saved owner and consume that operation's reservation rather than add an independent reservation. Materialized destination bytes replace the corresponding pending allowance atomically. Failure preserves the original allocation and releases only unused destination allowance; successful move retires only the old generation. In-place shrink cannot imply backing capacity shrank without evidence. Preserve each domain's zero-size, null-pointer, overflow and allocation-failure semantics.

Track pending malloc/calloc/arena allocation too: a large allocation can exist inside the underlying call before its wrapper records the return. For free, retire the saved generation only after the relevant release boundary; keep unconfirmed backing as debt. A callback must never wait for an application lease. A later admission experiment reserves the complete progress bundle outside allocator hooks; the observer only verifies consumption and invalidates insufficient coverage.

The upper-bound ledger must use disjoint categories: live unique backing including pending release, unmaterialized operation allowance, unresolved liability and observer storage. Do not add the same reservation again after it becomes a live block. This is a conservative accounting design, not an exact sampled peak. `xRoundup` and `xSize` describe the [SQLite allocator interface](https://www.sqlite.org/c3ref/mem_methods.html); neither alone proves CRT metadata, retained heap pages or transient scratch bounds. [CRT realloc semantics](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/realloc?view=msvc-170) also require distinguishing failure from zero-size release at the relevant layer. Unbounded remainder keeps qualification failed.

Tests must observe blocked allocation/free/realloc, successful move, in-place result, failure, small-to-large transitions, nested ownership, old-address reuse, concurrent operations and repeated overflow. Include mutation controls for early refund and missing pending destination charge. An event trace without these intermediate states is insufficient.

## NBL07. P0-E: isolated lifecycle measurement and conditional admission

Separate fixture creation and independent reference validation from the measured candidate process. Keep complete expected outputs/canonical streams outside it and compare them externally. Hashes identify artifacts; they do not replace evidence validation. Split cold imports/schema creation, warm retained pools, SQL capture, validation success/failure, returned output and physical cleanup. Snapshot construction uses funded observer storage and does not contaminate request ownership.

Repeat the real file-backed metadata and payload paths with the exact SQLite module; include TEXT-to-BLOB conversion, returned-row lifetime, cache backing and dense invalid inputs. First report coverage and accounting loss, then per-phase wall/CPU, lock/callback cost, unique backing, pending peak, retained pool/debt and process memory. Preserve original historical measurements. A reduced deduplicated total must be labeled an accounting correction unless actual allocations/lifetimes also change.

Only after all coverage/lifecycle gates pass, reconstruct the full simultaneous progress bundle from source-supported bounds. The existing `197697036 B` / `145472808 B` reservations are not halved because the probe double-counted a row. They were derived separately. Charge SQL, raw generations, parsing, models/errors, normalization, encoding, follower comparison, retained output and cleanup in their existing categories. Preserve atomic admission and fully validating fallback; no raw lease followed by an unfunded upgrade. If a legal row still cannot fit, report availability failure and stop P1.

## NBL08. Acceptance and unchanged safety contract

| Gate | Pass requires | Failure consequence |
|---|---|---|
| P0-A | Independent backing oracle detects duplicate/missing charges and reuse errors | No backing total |
| P0-B | Stable early hooks, provenance inventory, funded unresolved baseline | No whole-runtime coverage claim |
| P0-C | Shared arena accounting and justified release acknowledgement | Retain debt; no early refund |
| P0-D | Intermediate operation bounds, saved ownership, bounded bookkeeping and no deadlock | No reservation reduction |
| P0-E | Actual-query/validator lifecycle coverage, source bounds and legal-row progress | P1 stays disabled |

Passing an earlier gate does not imply the next one passed. Any unbounded bootstrap, CRT, Rust, VFS/mapping or retained-result remainder prevents whole-process qualification, even when Python domain accounting is correct.

Retain [BIR08](PROPOSAL-native-build-instrumentation.md): each request independently checks authority before/after and rereads activation. Verify all historical evidence, `19` raw fields/types, dependencies, strict models, canonical UTF-8/EOF, bar/request/root/formula and per-fact values. No completed-proof cache or trust in stored hashes.

Cancellation detaches observers or prevents unstarted work. Pending allocator operations, SQL/validation workers, returned results and transport remain owned until actual release or funded transfer. Cleanup failure retains debt and fences later generations. The last observer leaving cannot refund in-flight memory or terminate a synchronous worker prematurely.

Keep `64 MiB` input, `768 MiB` aggregate working set, `2560 MiB` private commit, `1` physical proof, `1` queued owner, `8` readers, `15-second` waits, `90-second` eligibility and `2` attempts. Cover `1/2/8` readers, both sides of time boundaries, late/rehashed tampering, leader/follower cancellation, last-observer departure and cleanup failure. Diagnostic failures allow `3` labeled rounds; qualification needs `10` A/A pairs and `20` ABBA/BAAB blocks, `20%` mixed-process gain, at most `5%` result and `10%` monitor/total-CPU regression, and no worse refusals/timeouts. Browser acceptance remains `100` attempts per variant, `100` successes before p95 claims and `20%` mixed-p95 improvement. No new performance or browser acceptance is claimed by this proposal.

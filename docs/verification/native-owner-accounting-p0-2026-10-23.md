# Native owner accounting P0 results

## NOA-V01. Decision

P0 is NOT_QUALIFIED; P1 is NO_GO. The isolated native extension now observes Python RAW/MEM/OBJ, newly allocated arenas and the actual SQLite allocator. This is a logical-domain feasibility slice, not completed backing-memory or owner qualification. Production source and dependencies remain unchanged. Existing AI extraction, daily inventory and README work is excluded.

## NOA-V02. Implementation and evidence

The compiled extension wraps existing Python allocators after interpreter initialization. SQLite configuration occurs before driver import; the loaded DLL path is checked. Native pointer/domain entries preserve allocating owners for cross-thread free and successful realloc. The fixed table has 262144 entries and occupies 8388608 bytes, separately counted as observer storage. Overflow freezes unreliable accounting and marks the run invalid; callbacks continue forwarding allocation/free. The experiment is disposable-process only and never uninstalls callbacks.

See [measurements](evidence/2026-10-23-native-owner-accounting-p0/measurements.json), [build](evidence/2026-10-23-native-owner-accounting-p0/build.json), [manifest](evidence/2026-10-23-native-owner-accounting-p0/manifest.json), [admission](evidence/2026-10-23-native-owner-accounting-p0/admission.json) and [summary](evidence/2026-10-23-native-owner-accounting-p0/summary.json). Initial compiler-path resolution and console encoding failures were corrected; the latter occurred after a successful compile. No binary reproducibility claim is made for this new observer.

## NOA-V03. Before/after

| Item | Before | Current evidence |
|---|---|---|
| Python/SQLite | Missing from Rust observer | Native logical-domain events observed |
| Cross-thread release | No pointer/owner ledger | 8388608 bytes refunded to original owner in each of 3 observed rounds |
| Actual SQLite | Read-only global counters | Hook records 9072792 bytes with the table/row alive and 0 after connection close |
| Dense errors | No Python domain observation | All 20000 errors retained in validation semantics; newly observed arenas reach 5242880 bytes in first observed round |
| Large-row admission | 197697036 / 145472808 bytes requested against 67108864 | Unchanged refusal before payload in 6 checks; final ledger usage 0 |
| Synthetic child wall median | 0.295276 seconds without hooks | 0.304061 seconds with hooks |

The 3 alternating rounds per variant include process startup, imports, SQL and error work. These wall times are diagnostic overhead, not CPU attribution, qualified performance or service speedup. Table exhaustion and late-install controls each pass in a separate child. Late SQLite configuration reports error 21. The overflow child takes about 33 seconds; this exposes bounded storage without proving acceptable worst-case lookup cost.

## NOA-V04. Failed gates and deferred dependent work

Nested Python domain calls double-count physical storage: after SQL close, owner totals retain roughly twice the 8388608-byte row. There are 182 unknown frees by the end of the first observed child, including pre-install objects. Arena backing is attributed to the allocating context, not reconciled across pool users. Post-call realloc records preserve logical ownership but do not capture transient old/new backing overlap. Rust direct allocations, CRT/heap fragmentation and complete pool/result transfers are not covered by this extension. Aggregate logical conservation is not physical conservation.

These concrete failures stop source-derived budget changes and funded legal-row integration. The preinitialization launcher, full oracle/candidate lifetime separation, real file-backed query coverage qualification, backing reconciliation, allocator-failure injection and a qualified large-row candidate remain unfinished. Existing full-validator regressions do not substitute for those new native gates. Keep the original leases and cleanup debt; do not deploy this observer as an admission allocator.

## NOA-V05. Verification

All 8 canary children completed with assertions: late setup, overflow, 3 baseline and 3 observed rounds. Observed rounds test native cross-thread release, exact SQLite DLL selection, returned-row lifetime, logical-domain/owner totals and dense validation errors. Existing tamper, deadlock/concurrency, time-boundary, storage-cleanup, failure-recovery and cancellation/drain selections pass 166 tests in 27.85 seconds, with an existing FastAPI warning. Three rounds of each large-row admission preserve safe refusal and zero final debt. No service/browser acceptance, new production upper bound or improved availability is claimed.

## NOA-V06. Submission review

Fixed an address-reuse race: realloc can free an old address before a different thread reuses it. Removing by pointer/domain alone could delete the new allocation record. Records now have monotonic generations; retirement requires the saved generation, and a mismatch invalidates observation without deleting another owner's record. Unknown pre-install realloc pointers cannot retire newly tracked storage. Realloc failure retains its old record. Accounting-loss updates use the same lock; pointer-result construction failure releases its raw allocation.

The native test executable passes 5 ledger scenarios. Removing the generation condition in an isolated mutant causes exit 22 as expected. The changed record layout costs 10485760 bytes; this observer overhead does not change application budgets. All 8 final canary children and 166 related regression tests pass; the latter took 28.21 seconds. Ruff passes. Original measurements/manifests remain historical evidence; reviewed native/source hashes and results are recorded separately in [submission review](evidence/2026-10-23-native-owner-accounting-p0/submission-review.json), [native tests](evidence/2026-10-23-native-owner-accounting-p0/native-review-tests.json), [review build](evidence/2026-10-23-native-owner-accounting-p0/review-build.json) and [review measurements](evidence/2026-10-23-native-owner-accounting-p0/review-measurements.json). No qualified performance claim or native-bound approval follows from these review fixes. P0 remains NOT_QUALIFIED and P1 NO_GO.

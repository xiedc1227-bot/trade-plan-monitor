# Evidence representation, sharing and scan follow-up

## ERS01. Decision and evidence

Continue isolated P0 experiments; P1 remains blocked. This proposal follows `850d904`, preserves production and parallel AI extraction/daily-inventory work, and authorizes no implementation or push. Restore paired specification/tasks before subsequent implementation. See the [previous report](../../verification/global-byte-admission-2026-10-22.md), [frozen gates](SPEC-global-evidence-byte-admission.md) and [read-only analysis](../../verification/evidence/2026-10-22-global-byte-admission-followup/analysis.json).

| Observed gate | Original | P0 | Implication |
|---|---:|---:|---|
| Valid JSON input | 16,472,833 bytes accepted | 296,534,034-byte work bound rejected | Availability fails; bound is not measured allocation |
| Thread, 8 readers, 5 rounds | 5 proofs / 35 joins / 40 successes | 15 proofs / 0 joins / 15 successes | Revalidation and queue rejection defeat sharing |
| Thread, 8-reader batch median | 2.530 s | 8.398 s | Scheduling/CPU regression |
| Process, 8-reader CPU median | 3.797 s | 11.438 s | Sharing alone is insufficient |
| Payload SQL per scan | 1 | 666 | Small batches amplify SQL work |

The process path still completes 40/40 requests in that workload, with 5 proofs and 35 joins, but its batch median is 2.836 s. Earlier diagnostic samples are not performance acceptance or p95 evidence.

## ERS02. Large-row overlap

For JSON length N, `shape()` reserves approximately `2 * (4N + N + 4N)`: driver text, encoded bytes, decoded validator text and overlapping generations. Thus the near-limit fixture receives about 18N plus scalar/container overhead, or 282.80 MiB. This combines real lifetime overlap with conservative Unicode sizing; it does not establish that this ASCII fixture actually allocates 282.80 MiB.

Trace the live objects first: SQL row, original text, encoded bytes, retained flight row, comparator locals, decoded row, previous validator iteration and exception traceback. Separately measure parsed models, canonical trees/strings, selected outputs and native allocations. They remain relevant to the process-memory gate even when outside the input ledger; do not silently move an existing charged input category outside the 64 MiB limit.

First candidate: capture JSON as UTF-8 bytes while retaining its original SQLite storage type. Followers compare bytes and scalar types directly, without decoded JSON. Decode only for the unchanged full validator. Eliminate driver-text-to-bytes round trips and release query/carry-over references before advancing. A lease transfer needs a single physical owner; duplicated references must not cause either duplicate allocation claims or premature refunds. Do not remove the generation factor until actual producer/consumer lifetimes prove it unnecessary.

Evaluate typed byte capture on a dedicated, explicitly owned read path: conditional BLOB projection or a controlled driver adapter. Do not mutate `text_factory` on a shared pooled connection. Preserve TEXT versus BLOB, NULL, numeric types, invalid UTF-8, embedded NUL, noncanonical JSON and every selected scalar; unsupported shapes fail closed without becoming valid canonical text. Metadata equality remains insufficient for sharing.

Whole-row capture may still fail for valid near-limit Unicode or multiple retained generations. Then assess read-only incremental access on the same connection/transaction for byte comparison and pre-submission streaming. SQLite incremental handles support TEXT/BLOB values on rowid tables, but require capability, encoding, expiry and cleanup tests. Neither `substr` nor a small returned chunk proves bounded native allocation. Chunking the read also does not make the unchanged full JSON/model/canonical validator incremental. If that validator cannot satisfy the frozen memory/availability gates, stop and specify a separate lifetime/streaming-validation design; do not silently raise the budget, reject supported input or weaken validation.

## ERS03. Sharing failure and bounded coordination

Production waits for collection-time comparisons before starting CPU validation. P0 removed that coordination to avoid a byte-wait cycle: after publishing input it validates immediately. Followers obtain workspace and perform the full scan, but join only if equality is established before `future.done()`. A proof that finishes first forces another owner attempt. The single queued-owner slot then rejects competing requests. Process execution provides a different comparison opportunity, but is not evidence that its scheduling contract is sufficient.

Current `mismatches` counts both unequal input and lost completion races. Therefore the measured count is not a corruption count, and the exact fraction caused by completion races still needs a timeline. Record collection, workspace wait/grant, publication, compare start/end, actual equality, physical start/end, queue admission/rejection and release. Separate unequal content, scope mismatch, completion-fence loss, deadline/cancellation and budget waits. Never log payloads.

Candidate: a finite cohort of comparisons funded before physical validation. Reserve leader collection/feeding/drain progress first; include old-flight borrowers and metadata in the same ledger. At publication, atomically choose and fund eligible collection-time followers whose declared workspace fits. Only those funded tokens can delay physical start. Close cohort membership, let these comparisons finish or cancel within existing deadlines, then validate. Requests still waiting for bytes are not barrier members; late arrivals cannot extend the barrier. No sleeps to manufacture overlap and no completed-proof grace period.

Do not hold coordinator/database cleanup locks across byte waits. A comparison owns its workspace before pinning raw input; it releases cursor, temporary rows and pin before waiting for the single queued-owner slot. Scope equality alone never admits a join. Every follower scans its own transaction and compares all ordered literal inputs. A mismatch revalidates the complete input, not a suffix. Keep 8 reader admission, 1 physical validator and 1 queued owner; reduced comparison concurrency must not be presented as reducing supported readers. If valid concurrent cases now time out or reject, the availability gate still fails.

## ERS04. SQL amplification

New read-only inspection on SQLite 3.50.4 finds 2008 candidates split into 666 payload queries: group sizes range from 1 to 18, with median 2. The original, metadata and first payload query all choose the head composite index on mapping/index identity plus payload hash lookup. The payload query does not choose direct head rowid lookup despite its locator filter. Repeated range traversal/filtering is therefore a concrete concern, not a missing-index assumption.

One payload-only instrumented pass returned the same ordered locators: approximately 64,300 VM instructions for the original query versus 3,253,800 for P0, about 50.6 times. Observed durations were 0.03549 s and 0.06207 s. These exclude metadata, Python sizing/comparison and full validation; order/cache and instrumentation are uncontrolled. This probe supports SQL work amplification but cannot explain seconds of total latency or establish a speedup target. Query-plan text is diagnostic, not a stable application API.

Preferred candidate after lifetime sizing: one complete metadata preflight plus one ordered payload cursor in the same explicit transaction. Preflight computes total retained-input reservation and the maximum simultaneous row/conversion workspace across all selected columns. Reserve that workspace before execute and keep it through cursor closure. Use a driver path whose fetch/lookahead is bounded and measured; never restore unbudgeted 128-row ORM buffering. The cursor can then advance through the existing ordered index without reconstructing a query for every tiny group. This targets 1 metadata query plus 1 payload query, excluding encoding checks; it is a hypothesis, not a measured achievement.

Validate execute-time lookahead, current/next-row overlap, sort materialization and native page caches. A payload cursor must not sort or prefetch unreserved large values. Preserve identical cardinality, missing joins, scalar types and order. If the runtime cannot establish the required bound, compare byte-admitted keyset pages or bounded locator-driven joins; charge any page/sort buffer and prevent skipped/duplicated rows. Do not retain unbounded metadata, add an index without plan evidence, or skip the initial complete preflight merely to remove a query. Benchmark metadata cost separately from payload execution and exact comparison.

## ERS05. Unchanged correctness and lifecycle contract

Every request retains independent authority-before/after checks, activation reread, original transaction/observation clock and 2-attempt behavior. Preserve the 15-second wait deadline and 90-second eligibility; no wait refreshes time. Sharing covers only a still-running pure proof after complete literal equality, never authority or completed results.

Validate every historical candidate, including old rows, missing payloads, head identity, canonical bytes and all existing domain hashes/formula checks. No latest-only shortcut, trusted stored hash or metadata certificate. The leader uses the full existing validator; any later validator refactor needs its own equivalence specification and differential tests.

Cancellation removes only the observer/unstarted work. Live SQL/byte access, comparison references, transport and submitted validation remain owned until actual cleanup. Preserve `DRAINED` or supervised child exit and bridge cleanup. A follower cannot cancel another request's proof. Stop/storage pause fences admission, wakes waiters and drains physical work. Cursor/handle/worker cleanup failure retains budget debt and the storage fence across generations; no reset counter or post-submission fallback.

## ERS06. Next implementation sequence and gates

1. **P0-A attribution:** freeze paired specs/tasks; add the missing sharing reason/timeline and lifetime/native-allocation probes. Reproduce valid large input, equal/changed snapshots and mixed reads. Keep proof, conversion, comparison, SQL, wait and queue costs separate. No optimization claim from the single SQL probe.
2. **P0-B representation:** trial byte capture and explicit reference release with the original validator. Test supported near-16 MiB rows, Unicode, NUL, malformed types/UTF-8, large non-JSON columns, previous selected rows and exception retention. If valid input cannot fit, stop integration and assess the separate large-row design.
3. **P0-C funded sharing:** use the minimal proven representation change; verify the closed funded cohort with fast proof/slow comparison, late arrival, large workspace, changed snapshot, cancellation and failed cleanup. Compare independently with eager validation. Deterministic overlapping equal-input fixtures must recover 1 proof and 7 joins without delaying physical completion for unadmitted work or accepting completed proofs.
4. **P0-D ordered scan:** compare the single-cursor candidate independently and combined with representation/sharing. Record SQL/VM counts, native lookahead, complete outputs, byte high water, transaction duration and WAL pressure. Keep a reference path and all failed attempts. Reintroduce process transport only after thread availability/correctness gates pass.
5. **P1 decision:** keep the frozen 64 MiB input limit, 768 MiB working-set / 2560 MiB private-commit experimental ceilings, and native/ownership proof gates. Sampled peaks alone do not prove enforceable bounds. Preserve full-validator results, independent authority, cancellation drain and valid-input availability. If any hard gate fails, stop fixed performance acceptance and publish the failed gate.

For candidates passing hard gates, retain 10 A/A pairs and 20 ABBA/BAAB blocks, same/changed 1/2/8-reader inputs, mixed result reads, late arrivals and fallback. Require at least 20% mixed-result improvement for process integration, at most 5% isolated-result regression and 10% monitor/total CPU regression, with no worse rejection/timeout rate. Report all failures and equivalent completed work. Real-owner/browser acceptance follows only an approved integration candidate; retain 100 attempts per variant and no p95 claim below 100 successes.

## ERS07. Sources and limits

SQLite documents metadata-based column byte length and encoding dependence in [core functions](https://sqlite.org/lang_corefunc.html#octet_length), storage restrictions for [incremental read handles](https://sqlite.org/c3ref/blob_open.html), and the diagnostic nature of [query plans](https://sqlite.org/eqp.html). Python documents [read-only blob access and connection text conversion](https://docs.python.org/3.14/library/sqlite3.html). These establish candidate API semantics, not memory bounds or equivalence for this application.

This analysis adds a bilingual proposal and sanitized read-only probe evidence only. It changes no runtime/test code or service state, performs no browser acceptance, and makes no new end-to-end performance or native-memory guarantee. Frozen input bytes remain unchanged. Full reason-specific concurrency traces and large-row lifetime measurements are the next experiment, not completed work.

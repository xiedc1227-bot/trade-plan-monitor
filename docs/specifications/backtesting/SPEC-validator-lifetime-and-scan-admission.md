# Validator lifetime and scan admission P0 specification

## VLS-S01. Scope

Isolated experiment following 72bd925 and the paired proposal. Preserve existing file fingerprints, authority/activation/transaction/clock boundaries and all historical integrity checks. No production registration, service restart, commit or push. No AI extraction or daily-inventory edits.

## VLS-S02. Variants

A: instrument parse, normalize, encode/hash, literal comparison, scan waits and CPU. B: direct byte JSON parsing, original model and normalized-tree policies, incremental domain hashes and canonical literal comparison; retain original public APIs. Encoder pieces may be large: slice consumption is not a bounded-producer proof. Keep conservative scan sizing and report this failed gate. C: shared FIFO scan permits for metadata/payload cursor lifetimes, compare 8/2/1 slots with 8 readers. Reserve bytes before permit; acquire no additional bytes while holding it. Close cursor before releasing permit; release before funded-cohort waits. Preserve original deadline, cancellation and stop signals. Cleanup failure keeps ledger debt and storage fence even after the CPU slot releases.

## VLS-S03. Correctness

Each follower owns its independent complete preflight and ordered literal comparison in its original transaction. Verify all 19 selected fields, storage types, canonical UTF-8, complete historical models, head identity, formula/bar/request/snapshot hashes, missing dependencies and ranking. No completed cache, trusted stored hash or latest-only shortcut. Preserve 2 attempts, 15-second waits, 90-second validity, 1 physical proof and 1 queued owner. Cancellation never refunds live physical work. Drain and failure debt remain authoritative.

## VLS-S04. Acceptance

Test supported near-16 MiB input, Unicode/escapes/types, all hash/scalar tampering, old rows, missing payload, time boundaries, 8-reader sharing/deadlocks, cancellation and cursor/worker cleanup failure. Run original lifecycle/authority regression suites. Capture frozen input hashes, complete output equivalence, wall/thread/process CPU, traced and process memory and byte peaks. Retain 64 MiB input, 768 MiB working-set and 2560 MiB private-commit ceilings; sampled peaks do not prove native bounds. Any availability/native-bound failure blocks P1 and fixed performance acceptance. Then run 3 diagnostic rounds at 1/2/8 readers and mixed reads. If hard gates pass, use 10 A/A pairs and 20 ABBA/BAAB blocks; require process mixed gain 20%, isolated result regression <=5%, monitor/total CPU regression <=10%, no worse rejection/timeout. Real-owner/browser acceptance only for an integration candidate: 100 attempts per variant; p95 requires 100 successes. A blocked candidate is reported without production integration.

# Bounded encoding and byte parsing P0 specification

## BEP-S01. Scope

Implement isolated experiments following the paired proposal. Preserve all existing files, authority and integrity policies. No production registration, restart, AI extraction or daily-inventory changes. P1 is conditional; no commit or push in this implementation.

## BEP-S02. Producer

Normalize using the original model_dump, Decimal, enum and datetime policy. Accumulate conservative encoded sizes once in row-local containers. Admit each C encoding call before producing output; trial 64 KiB and 256 KiB logical targets. Charge producer buffers through a separate experimental lease inside the unchanged 64 MiB ledger. Logical output bounds do not prove native writer bounds. Include sorted vectors, descriptors, previous chunks and UTF-8 conversion. Retain every domain hash and complete literal comparison including EOF. No completed cache or permissive parser.

## BEP-S03. Parsing and admission

Measure success/error lifetimes for long Decimal and dense-object rows, excluding prebuilt input explicitly. Model/native allocations remain in the process gate; no reclassification of charged input copies. Test the full SQL preflight route for supported near-16 MiB input. Do not reduce conservative scan reservations until native/driver lifetimes are proven. A safe rejection is still failed availability. Keep 64 MiB input, 768 MiB working set, 2560 MiB private commit, 8 readers, 1 physical proof, 1 queued owner, 15-second waits, 90-second eligibility and 2 attempts.

## BEP-S04. Verification and decision

Verify all historical records, all 19 fields/types, head identity, missing payload, canonical bytes and bar/request/snapshot/formula hashes. Differential-test tampering, large/dense rows, chunk boundaries, cancellation, physical drain, concurrent isolation, deadlines and cleanup failure. Run original authority/retention/lifecycle regression suites. Record source/input fingerprints and before/after measurements. Any native-bound or availability failure blocks P1 and fixed performance acceptance; use 3 diagnostic rounds only. Otherwise require 10 A/A pairs, 20 ABBA/BAAB blocks, 20% mixed process gain, <=5% result and <=10% monitor/CPU regression, no worse rejection/timeout. Browser acceptance requires an integration candidate and 100 attempts per variant; no p95 below 100 successes.

# Bounded validation transport specification

[Chinese review copy](SPEC-bounded-validation-transport.zh-CN.md). [Proposal](PROPOSAL-bounded-validation-transport.md). Authorized implementation baseline: `f430c96`.

## BVT-S01. Scope

P0 is an isolated, reproducible Windows-spawn experiment under `scripts/experiments`, with focused tests and frozen read-only data. Production modules, databases, services and configuration stay unchanged. Preserve pre-existing proposal/evidence and parallel AI extraction/daily-inventory work. No commit/push in this phase. P1 is conditional on all gates, including a specified global production ownership/accounting contract.

## BVT-S02. Protocol and pure core

Use a private duplex pipe, one physical worker and one outstanding input frame, maximum 1 MiB. Use explicit scalar tags for null, bool, signed integer, UTF-8 text and bytes; unsupported scalars or overlarge rows select whole-proof thread fallback before submission. Preserve original JSON bytes, types, missing payload and order. No executable pickle protocol. Bind bounded messages to version, worker generation, job, sequence, count and length; final count and ordered digest must agree. Unexpected EOF, trailing bytes and crossed messages fail closed. Call the unchanged `_latest_index_records` once, maintaining global ranking and every `_market_index_from_row` check. Responses carry bounded JSON records; failures carry only fixed codes. Complete receipt and physical cleanup are distinct.

## BVT-S03. Budget

Keep aggregate input/copy admission <=64 MiB. Reserve 16 MiB before transport allocation and charge parent raw retention plus external simultaneous input leases; the prototype must report external leases explicitly, including zero for a single frozen caller. Maximum raw chunk is 2 MiB, encoded chunk 1 MiB. The reservation covers encoding/receive/kernel copies, overlapping child chunks, decoded source text, bounded output/control and planning overhead. If the conservative envelope cannot be proved, record a failed gate, not a claim of safety. Oversized rows, unsupported types, output bound or insufficient aggregate headroom cause pre-submission full thread fallback. Never serialize all input. Keep leases until actual cleanup; cancellation does not refund them.

Measure synchronized parent/child working set and private commit separately from input accounting. Parsed models, interpreter baseline and allocator retention need an absolute process-memory gate before P1. P0 must disclose any unproven allocation bound, including concurrent SQL/comparison batches, and cannot use a single-caller result to certify production concurrency.

Before fixed sampling, the smoke run selected thread fallback because its initial 0.5 MiB output reservation was too small. Keep that run. The final configuration permits 1 MiB output within the unchanged total, and splits chunks to satisfy `8 * wire + 2 * raw + 2 * text + 2 * OUTPUT + MiB <= RESERVE`; decoded source text per chunk is capped at 1 MiB. This is a conservative prototype accounting envelope requiring runtime corroboration, not proof of all Python/kernel allocation sizes. Freeze this configuration before the 300 observations.

## BVT-S04. Ownership

Keep independent before/after authority, transactions, clocks, activation checks, 2 attempts, full-history integrity, exact in-flight comparison, 8 readers, 1 validator and 1 queued owner. An observer cancels independently; physical input feeding, result consumption and cleanup continue under the owner. No post-submission fallback or duplicate validation. Failed protocol/child execution quarantines the generation. Retain the lease on cleanup failure. Normal stop joins the child; emergency teardown discards channels and confirms process exit before release. Use a 30-second prototype supervision bound separate from existing request deadlines; this is not a new production timeout. Deterministic test gates are excluded from timed measurements.

## BVT-S05. Fixed experiments and gates

Use existing frozen monitor/result inputs with matching immutable result ownership. Freeze 10 A/A pairs plus 20 alternating ABBA/BAAB blocks for each of isolated monitor, isolated result and mixed workloads: 40 measured observations per variant plus 20 controls per workload, 300 total. Mixed result launch follows physical submission. Retain every attempt/fallback/failure and complete output hashes. Separate cold start and 3 fresh-process memory observations per variant. Record parent/child CPU, full completion, IPC, exact input count and physical drain. Fix 1 MiB frames before measuring; no favorable-sample replacement.

Require >=20% mixed result median improvement, <=5% isolated result regression, <=10% monitor median and total parent-plus-child CPU regression, full output equality, bounded input copies and safe lifecycle. Freeze an absolute process-memory limit and production global lease ownership before P1. A failed or unproven prerequisite means P1 no-go. If P1 proceeds, first add its bilingual contract, then perform the previously proposed 100-attempt-per-variant real-owner acceptance and browser checks; no p95 claim without >=100 successful observations per variant.

## BVT-S06. Verification

Write failing codec/admission tests before implementation. Cover empty/single/chunk-boundary/large/unsupported inputs, byte limits, exact round trips, truncated/duplicate/reordered/crossed frames, wrong final count/digest, stale result, old/unselected tamper and canonical/head/provider binding. Exercise cancellation before/during/after work, follower survival, repeated cancellation, crash/hang, blocked communication, child cleanup failure and storage-fence regression. Check mutations of integrity, authority, stream completion and early release. Run relevant existing ownership/integrity suites and scoped lint. Publish bilingual reports with all limits and measured comparisons; a P0-only experiment does not change browser behavior or claim a production speedup.

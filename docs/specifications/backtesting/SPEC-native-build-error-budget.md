# Native build and failure ownership P0 specification

## NBB-S01. Scope

Implement isolated experiments following [NBB01–NBB08](PROPOSAL-native-build-error-budget.md). Preserve existing work. No production registration or parallel AI extraction/daily-inventory changes. P1 is conditional, not required when gates fail.

## NBB-S02. Build and memory qualification

Record installed binary, official wheel/source identities, runtime build flags, dependency lock/SBOM, available compiler and artifact evidence. Missing build/allocator provenance means NOT_PROVEN. A rebuilt binary is a different qualification target. Do not install or replace runtime dependencies implicitly. Record native/process observations separately from Python traces; sampled peaks cannot certify transient upper bounds. Preserve `64 MiB` input, `768 MiB` aggregate working set and `2560 MiB` private commit.

## NBB-S03. Failure boundary

Run the unchanged complete validator to return or failure, including iterator cleanup. Capture only known exact projection failure classes into immutable bounded descriptions, outside the exception handler's lifetime. Do not retain source exceptions, input, model or traceback in failure outcomes. Deliver fresh exceptions per caller. Unexpected cleanup errors propagate; never convert cleanup failure into a valid proof. Explicitly account for cyclic garbage collection after failure; no observer cancellation or logical completion can refund physical ownership early.

## NBB-S04. Admission and invariants

Measure legal long-Decimal and dense fixtures through the actual SQL preflight. Retain conservative reservations until native qualification passes. Arithmetic-only smaller bundles are diagnostics, not executable admission policy. Record metadata/payload counts, refusal and final debt. No partial lease followed by a blocking unfunded encoder upgrade.

Retain independent authority before/after, activation reread, all historical rows, all `19` fields/types, strict model checks, canonical UTF-8/EOF, bar/request/root/formula/per-fact checks, original clocks and attempts. Preserve `1` physical proof, `1` queued owner, `15-second` waits, `90-second` eligibility and `2` attempts. Cancellation and cleanup failure retain ownership until actual drain; cleanup failure fences subsequent generations.

## NBB-S05. Acceptance

Verify success equality, dense failure lifetime, fresh exceptions, missing dependency, all raw fields, rehashed tampering, cleanup failure, concurrent isolation, cancellation, deadlock and time-boundary regressions. Run three alternating frozen CPU rounds and isolated traced memory comparisons; label them diagnostic. Only after native and availability gates pass run `10` A/A pairs, `20` ABBA/BAAB blocks, `20%` mixed gain, at most `5%` result and `10%` monitor/total-CPU regression, and no worse rejection/timeout. Browser acceptance requires integration, `100` attempts per variant and `100` successes before p95 claims. Report unperformed gates explicitly.

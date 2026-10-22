# Global byte admission P0 verification

[Specification](../specifications/backtesting/SPEC-global-evidence-byte-admission.md) · [Tasks](../specifications/backtesting/TASKS-global-evidence-byte-admission.md) · [Measurements](evidence/2026-10-22-global-byte-admission/measurements.json)

## GBA-V01. Decision

P0 is complete as a feasibility experiment; P1 is no-go. The prototype admits SQL payload allocation through a shared ledger and preserves the original validator, but it fails supported-large-input availability and concurrent performance gates. Production remains unchanged. This is not a performance optimization ready for deployment.

The declared early-stop rule was used: after a valid large row failed admission, fixed performance acceptance was not run. Instead, all 5 diagnostic rounds of the 1/2/8-reader workloads and 5 alternating mixed rounds were retained: 60 batches, 195 request attempts. There were 170 successes and 25 failures. All failures occurred in the budgeted-thread 8-reader workload. No failed sample was replaced. These small diagnostic groups cannot establish p95 gains.

## GBA-V02. What was implemented

Experiment modules under `scripts/experiments` provide a shared `Budget`, explicit leases, snapshot-local `Scan`, progress-safe `Flights`, a temporary projection adapter, valid-large-row construction, diagnostic runner and process-local mutations. No production registration or configuration switch was added. The adapter invokes original projection normalization/scope construction and uses each repository's existing transaction. One injected coordinator/ledger spans the experimental reader instances, including temporary stopped-health readers.

Metadata uses `typeof` and `octet_length` for every selected field with UTF-8 capability checks, 32-row pages and 128 KiB per scanner. Payload queries select only admitted locators and preserve the original ordering. Initial workspace is 1 MiB, enlarged only when a conservative row bound requires it. The default global limit remains 64 MiB. Raw/transport reservation is atomic; comparisons obtain workspace before pinning a proof. Readers waiting for input collection hold metadata only. Mismatching comparisons close before entering the single queued-owner slot. No completed proof is cached and no post-submission fallback occurs.

The large-workspace progress test holds the leader during collection while 7 followers request 16 MiB each. Pending followers cannot occupy those workspaces while waiting for the leader; after collection, admitted comparisons finish and all 8 readers receive the proof. Cleanup failure in a cursor or child retains the corresponding global lease and fences new admission. The normal fallback uses the complete original validator on a budgeted source; the transport fallback happens before submission and validates the same retained literal input.

## GBA-V03. Memory and large-input gate

A canonical, fully validated candidate with 480 daily bars and supported decimal precision has 16,472,833 JSON bytes, below the 16 MiB persistence limit. The original complete validator accepts it. The new conservative work bound is 296,534,034 bytes (282.80 MiB), so the scanner rejects it before any payload query. A separate medium valid row successfully takes thread fallback before child submission. The near-limit rejection is a failed availability gate, not a passing optimization merely because allocation stayed bounded.

For the ordinary frozen 2008-candidate fixture, preflight raw reservation is 39,184,065 bytes versus earlier measured retention of 30,826,621 bytes. The process input ledger reaches 65,398,465 bytes (62.37 MiB) with 8 readers and drains to zero. The original production ledger does not cover these same categories; a zero in the new diagnostic ledger for original-thread samples means it is unused, not that original memory use is zero.

Fresh-process memory observations used 3 runs per variant with 8 monitors plus a result read and paired parent/child counters every 20 ms. Values below are medians of maxima of contemporaneous sums, not sums of independent peaks. The maxima across all runs remain below the predeclared 768 MiB working-set / 2560 MiB private-commit experimental ceilings. Sampling can miss shorter peaks. Private commit is different from resident working set. The budgeted-thread runs have 15 failed requests among 27 attempts, so their lower memory cannot be claimed as an equivalent-work improvement.

The ledger bounds charged Python input work under its sizing assumptions; native SQLite/driver/allocator bounds remain unproven. Metadata query execution, page caches, conversion internals, parsed models and the interpreter are not certified by the lease high water. Passing sampled process ceilings is not a proof of a deployment memory cap.

| Variant | Working set (MiB) | Private commit (MiB) | Successful requests |
|---|---:|---:|---:|
| Original thread | 372.89 | 1088.68 | 27/27 |
| Budgeted thread | 295.25 | 1010.19 | 12/27 |
| Budgeted process | 522.19 | 1953.29 | 27/27 |

## GBA-V04. Before/after diagnostic comparison

These are frozen read-only full reads with synthetic absent-owner authority, using the same host/runtime. Variants alternate order across rounds. Each group has 5 observations; diagnostic timing includes counter sampling. Complete output hashes match for every successful request. Failed reads are retained in counts and batch durations. Original-thread measurements are from this run, not the earlier transport experiment.

The budgeted thread loses all sharing in the measured concurrent groups. In the 8-reader group, the original and budgeted process each perform 5 physical proofs and 35 joins across rounds; the budgeted thread performs 15 physical proofs, no joins, and rejects 25 requests. The original leader's comparison coordination is absent from the experiment's eager-validation policy: followers can finish comparison after the proof completion fence. They then compete for the unchanged single queue slot. This policy is progress-safe in deterministic tests but fails equivalent availability and latency in this workload.

Each budgeted scan of the fixture performs 2 metadata queries and 666 payload queries. Original scanning uses one ordered payload query with row-count buffering. Per-column preflight, smaller groups and repeated independent queries add CPU work. At 8 readers the budgeted process uses approximately 3.01 times original total CPU despite sharing the same number of physical proofs. Do not present the lower mixed result duration as isolated-process improvement: the budgeted thread also returns the result earlier while monitor completion moves later. The new collection work changes CPU overlap/scheduling; full batch and monitor behavior do not improve.

| Diagnostic median | Original thread | Budgeted thread | Budgeted process |
|---|---:|---:|---:|
| 1-reader batch (s) | 1.933 | 2.026 | 2.110 |
| 2-reader batch (s) | 2.002 | 4.278 | 2.145 |
| 8-reader batch (s) | 2.530 | 8.398 | 2.836 |
| 8-reader successes | 40/40 | 15/40 | 40/40 |
| 8-reader total CPU (s) | 3.797 | 15.391 | 11.438 |
| Mixed result duration (s) | 4.087 | 2.149 | 2.217 |
| Mixed monitor completion (s) | 3.075 | 4.133 | 4.260 |
| Mixed batch completion (s) | 4.088 | 4.133 | 4.261 |

## GBA-V05. Correctness, cancellation and review

Final focused suite: 23 passed in 5.30 s. Relevant regression before the last literal-input additions: 116 passed in 67.11 s, with the existing Starlette warning. A separate run with the experimental adapter injected passed 5 authority/time/disconnect tests in 5.06 s, including temporary stopped-health ownership; it executed 25 physical proofs and 27 scans against one injected ledger and drained to zero. These counts describe separate runs, not a summed unique test total.

Coverage includes exact byte admission, cancellation while waiting, stop/drain, independent allocations, pre-query leases, UTF-8/NUL/BLOB preservation, old/missing/head/canonical tamper, literal mismatches across real committed SQLite snapshots, full budgeted fallback, near-limit valid rejection, medium-row transport fallback, same-input sharing, large-workspace progress, repeated observer cancellation with storage pause, cursor cleanup failure and child cleanup debt. Existing complete-validator and transport tests cover physical crash/hang, framing and post-submission failures. No authority or integrity check was removed.

All 3 process-local mutations were detected: early release, missing SQL workspace accounting and skipped literal comparison. Mutations did not edit files. Scoped Ruff passes. All 1802 initially tracked files and frozen input hashes remain unchanged; measured experiment source fingerprints matched implementation-complete source; the later diagnostic cleanup fix is recorded separately in GBA-V07. No production service was restarted or history cleaned. Tests use local temporary fixtures, and diagnostic data contains no raw evidence payload.

During implementation review, a potential wait cycle was removed before measurement: collecting followers initially could acquire large workspaces before waiting for publication. They now wait without that workspace. Cursor/child cleanup debt was also connected to the outer ledger before measurement. These refinements are part of the measured source. The successful frozen schedule has no admitted-byte overrun and every non-injected run ends with zero leases and joined child processes. This does not resolve the failed availability/performance or unproven native-memory gates.

## GBA-V06. Next step and reproduction

Do not enable P1 or add a production switch. The next design must first reduce large-row representation overlap without weakening literal/canonical checks, and recover admitted-follower coordination without making physical progress depend on unadmitted work. Reduce metadata/payload query amplification only after the byte bound remains defensible. Keep the 64 MiB limit, independent snapshots/authority, single physical validator/queue and cancellation drain. Revisit native allocation and an enforceable deployment memory contract separately.

Use `.venv/Scripts/python.exe -m scripts.experiments.global_evidence_benchmark --help`; supply `--monitor`, `--results`, `--run`, `--output` for the declared diagnostics. `--smoke` is excluded from diagnostics and `--memory` selects a fresh-process memory run. Inputs must be frozen copies with the matching immutable-result ownership directory. The valid large-row probe is `.venv/Scripts/python.exe -m scripts.experiments.global_evidence_large`. Portable evidence retains all attempts, memory samples with declared column order, sanitized failure logs, source/input hashes and the gate decision.

Changed-snapshot correctness was tested deterministically; changed-snapshot 8-reader performance, fixed acceptance, production composition and real-owner/browser acceptance were not run after the hard gate failed. No production path was enabled. Existing AI extraction and daily-inventory work is preserved. The implementation phase did not commit or push; subsequent submission review is separately authorized.

## GBA-V07. Submission review

Review reproduced a diagnostic-runner cleanup bug: failure in reader stop or proof drain left the non-daemon memory sampler alive. The sampler now stops and joins in an outer finally block while preserving the original failure. Both injected failures were observed before the fix and pass afterward. No admission, authority or validator behavior changed.

The submission regression run passed 120 tests in 68.62 s with 1 existing Starlette warning. Scoped Ruff passed and the early-release mutation was detected again. The corrected runner completed 3 smoke batches and all 6 requests successfully, with matching full output hashes, zero remaining budget and an exited child. This smoke run overlapped the regression run and is excluded from performance comparisons.

The original 60-batch diagnostic data and measured source hashes remain unchanged. Evidence separately records current source hashes, the original measured runner source, regression logs and review smoke output. All 1802 previously tracked files and frozen database fingerprints remain unchanged. Submission is restricted to 20 P0 files; AI extraction and daily-inventory changes are excluded. P1 remains no-go and no production path is enabled.

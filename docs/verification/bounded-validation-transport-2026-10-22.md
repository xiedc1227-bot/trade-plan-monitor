# Bounded validation transport P0 verification

[Chinese review copy](bounded-validation-transport-2026-10-22.zh-CN.md). [Specification](../specifications/backtesting/SPEC-bounded-validation-transport.md). [Tasks](../specifications/backtesting/TASKS-bounded-validation-transport.md). [Portable evidence](evidence/2026-10-22-bounded-validation-transport/measurements.json).

## BVT-V01. Decision and scope

P0 is complete; **P1 is no-go**. A single-caller chunked process substantially reduces controlled mixed result latency and fits the proposed input-copy envelope. The current concurrent SQL/comparison buffers cannot yet participate in that global lease: their conservative envelope with 7 followers reaches 99,784,903 bytes (95.16 MiB), exceeding 67,108,864 bytes (64 MiB). Production integration would need a separate byte-admission design before SQL batch allocation. An absolute production process-memory allowance also remains unspecified; input-copy admission is not an RSS limit.

All work is isolated under `scripts/experiments` and new tests/documents. Production code, authority/integrity logic, SQL behavior, runtime service, configuration and historical data are unchanged. Fingerprints of 1024 pre-existing tracked source/test/web/configuration/README files match the baseline. Existing proposal/evidence are preserved; no parallel AI extraction or daily-inventory patch is included. No commit or push was performed.

## BVT-V02. Implemented experiment

The experimental worker uses a private Windows-spawn pipe, version/job/generation/sequence binding, bounded control messages, explicit scalar tags and one outstanding chunk. No pickle input, executable exception payload, ORM/session/authority transfer, full child input tuple or completed-proof cache is introduced. It calls the unchanged `_latest_index_records` once over the ordered stream; `_market_index_from_row` still validates every historical candidate before ranking. Final count/digest validation is additional transport checking, never a replacement for canonical or domain checks.

Maximum wire frame is 1 MiB, raw chunk 2 MiB and decoded source text 1 MiB. The parent reserves 16 MiB for the conservative transport envelope before transfer. The actual frozen input produces 110 chunks rather than the proposal's exploratory 28: decoded-text and copy-overlap bounds, not wire length alone, constrain grouping. Each physical proof consumes 2008 candidates, transfers 28,923,969 input bytes and returns 110,797 output bytes. Total transferred bytes are not simultaneously retained bytes.

Admission includes parent raw retention plus an explicit external-lease amount. Unsupported/oversized inputs or inadequate budget select complete thread verification before submission. A post-submission failure cannot request fallback. The existing physical owner outlives detached observers; input/worker leases remain until the child outcome and `DRAINED` have been consumed. Worker crash/protocol failure quarantines its generation and confirms exit; cleanup failure retains the reservation. No production timeout, concurrency limit or storage fence was changed.

The installed Python 3.14.7 pipe implementation checks oversized messages after its initial small read and before reading the remaining payload. An actual pipe oversize test confirms rejection and sender completion. This is specific to the inspected runtime, not a cross-platform allocation guarantee. The accounting formula intentionally reserves overlapping input/receive/encode/output space; Python allocation profiling corroborates this fixture but does not prove all possible kernel/runtime allocations.

## BVT-V03. Fixed performance comparison

The schedule completed all 300 attempts: isolated monitor, isolated result and mixed workloads each have 10 A/A pairs and 20 alternating ABBA/BAAB blocks, giving 20 controls plus 40 thread and 40 process observations. Every attempt succeeded, with no fallback and identical complete output hashes. Each monitor attempt retained 2 independent parent authority calls and drained its proof; isolated-result attempts do not read monitor authority. Cold startup is excluded from warm timings and recorded separately.

These are full reads on frozen read-only databases with synthetic absent-owner authority, not real-owner/browser production measurements. The process variant for isolated-result samples has the child idle. Parent-plus-child CPU is measured using process counters, including the bridge/transport. No samples were replaced to pass a gate.

| Median measure | Thread | Chunked process | Change |
|---|---:|---:|---:|
| Isolated monitor completion | 1.9218 s | 1.9848 s | +3.28% |
| Isolated monitor total CPU | 1.9063 s | 1.9844 s | +4.10% |
| Isolated result completion | 1.9565 s | 1.9475 s | -0.46% |
| Mixed result duration | 3.8590 s | 2.0064 s | -48.01% |
| Mixed monitor completion | 2.2043 s | 2.3359 s | +5.97% |
| Mixed batch completion | 3.9554 s | 2.3361 s | -40.94% |
| Mixed total CPU | 3.9609 s | 4.0156 s | +1.38% |

Latency/CPU feasibility thresholds pass. The near-zero isolated-result difference is not an intrinsic speedup claim. Do not compare these timings directly with earlier experiments run under different host load, or present them as a production p95 gain. No production worker or new browser path was enabled; conditional P1 real-owner/browser acceptance was therefore not run.

## BVT-V04. Memory result and blocking gate

| Conservative input accounting | Bytes | MiB |
|---|---:|---:|
| Earlier full-buffer process input copies | 119,382,234 | 113.85 |
| Parent raw evidence | 30,826,621 | 29.40 |
| Proposed chunk transport reservation | 16,777,216 | 16.00 |
| Single caller: raw plus reservation | 47,603,837 | 45.40 |
| Largest observed SQL prefetch batch | 7,454,438 | 7.11 |
| Single caller plus 7 follower batch envelopes | 99,784,903 | 95.16 |
| Unchanged total limit | 67,108,864 | 64.00 |

The single-caller planned charge is approximately 60.13% below the previous full-buffer accounting. These are conservative admission figures, not unique heap size or RSS. The external charge is explicitly zero in the fixed single-caller experiment. The concurrency probe inspects actual SQLAlchemy/DBAPI prefetch buffers with the existing 128-row setting. It conservatively counts repeated scalar references, then evaluates simultaneous follower envelopes arithmetically; it does not claim that 7 peak buffers were observed simultaneously. The adapter admits the single-caller and single-follower envelopes, and rejects the 7-follower envelope. Current production comparison scans do not acquire this new global byte lease before allocating a SQL batch. That missing enforceable boundary blocks P1 even though isolated transport succeeds.

Separate fresh-process measurements use 3 runs per variant and paired parent/child samples every 20 ms. Median maxima of the sampled combined working set are 283.27 MiB for threads and 506.63 MiB for the process variant. Median maxima of sampled combined private commit are 999.20 MiB and 1938.95 MiB. These are maxima of contemporaneously sampled sums, not sums of independently observed peaks; sampling can miss shorter transients. The child interpreter and imported stack remain expensive after eliminating full input duplication. Private commit and resident working set are different measures.

Separate allocation profiling with the full always-on output set runs 3 repeated proofs. Parent Python peak allocation ranges from 1,240,760 to 1,245,278 bytes; child peaks range from 2,147,310 to 2,153,063 bytes. Child traced current allocation after job return is 75,990 / 70,304 / 70,204 bytes. Every proof reaches zero retained lease. These short runs show no growing retained Python input collection; they are not a long-duration leak guarantee. Existing parent raw input, interpreter baseline, native allocations and kernel buffers are outside these incremental Python peaks. Profiled durations are excluded from the fixed performance comparison.

## BVT-V05. Correctness and failure evidence

- Relevant regression: 150 passed with the existing Starlette deprecation warning, including 33 new codec/transport cases and existing authority, historical integrity, time-boundary, retention, disconnect and drain tests. After strengthening the fixed-budget assertion, all 16 codec tests pass again.
- New coverage includes exact scalar types/JSON bytes, empty/single/repeated proofs, truncated/trailing/invalid-tag frames, byte-boundary admission, unsupported/large input, old unselected JSON/missing payload/head/canonical corruption, wrong final count/digest, crossed sequence/generation, child crash/hang, repeated observer cancellation, follower survival, storage-pause retention, actual oversized pipe receive, cleanup failure and post-submission encoding failure.
- All 6 process-local mutation modes are detected: stream completion, canonical equality, early release, fixed budget, budget condition and independent authority token. Mutations never modify repository source.
- Scoped Ruff passes. Frozen database hashes and all protected tracked-file fingerprints remain unchanged. All experiment children are joined; services were not restarted and no historical-data cleanup occurred.

Initial failures remain disclosed. The first codec invocation produced excessively long large-value test IDs and setup errors; bounded IDs and the permitted test workspace resolve the harness issue. Mid-chunk evidence rejection originally used a consumed-chunk sequence and was misclassified as transport failure; the error sequence contract was corrected without accepting bad evidence. The first smoke run took full thread fallback because its output allowance was too small; it remains separate from the fixed comparison. The initial fixed-budget mutation survived because the test imported the mutated threshold; an explicit unchanged-budget assertion now detects it, and a separate mutation also removes the budget condition.

After fixed sampling, an injected encoder failure exposed possible misclassification as pre-submission fallback. The handler now converts that exception to physical transport failure and drains/quarantines the child. Exact measured-source reconstruction confirms the only worker change is that exception-handler type/import; the successful branch is unchanged. Final fault regression and allocation/memory runs use the corrected worker. Both source fingerprints are retained. The first allocation probe returned only dashboard indexes; all historical inputs were validated, but its output set was incomplete for this comparison. It is retained separately, followed by the declared repeated probe with the full always-on set. Neither allocation run is counted as latency evidence.

## BVT-V06. Reproduction and next step

The checked-in experiment modules accept explicit frozen paths and never start the application. Use `.venv/Scripts/python.exe -m scripts.experiments.bounded_benchmark --help` for the fixed comparison interface. Supply `--monitor`, `--results`, `--run`, and `--output`; the frozen result database must have its matching immutable-input ownership directory. `--memory` selects the separate memory run; `--smoke` is excluded from acceptance. Run `.venv/Scripts/python.exe -m scripts.experiments.bounded_allocation_probe --help` and `.venv/Scripts/python.exe -m scripts.experiments.bounded_concurrency_probe --help` for the independent probes. Portable evidence includes all fixed rows, memory samples, allocation observations, prior smoke/probe outcomes, fingerprints and log tails, but no database or private evidence payload.

The next design must reserve bytes before each follower SQL allocation, include changed/mismatching snapshots and still-draining proofs, and preserve independent transactions and exact comparison. Simply multiplying the allowance, reducing integrity checks, caching authority, or shortening drain is excluded. Also specify an absolute parent-plus-child memory budget using the new working-set/private-commit evidence. Only after those gates can be enforced should a new production integration proposal and fixed real-owner/browser acceptance proceed. The current fully validating production thread path remains in place.

## BVT-V07. Submission review

The subsequent user request authorizes committing and pushing this P0 experiment; the specification's implementation-phase submission restriction is historical. Review found no blocking issue within the isolated experiment scope. The submission review reran all 33 new tests (33 passed in 16.54 s), scoped Ruff, and the early-release mutation, which the cancellation/ownership test detected. The earlier 150-test regression remains the implementation validation record; it was not rerun during submission review.

All 300 recorded attempts, complete output hashes, independent authority-call counts, recomputed medians and frozen database fingerprints were verified. All 9 final source fingerprints match the portable evidence, and all 1024 protected tracked files remain unchanged. English/Chinese identifiers, numeric criteria and inline contracts match. Submission uses an explicit file list covering only this experiment, its tests and bilingual documentation/evidence, excluding parallel AI extraction and daily-inventory work. The P1 no-go decision and production behavior remain unchanged.

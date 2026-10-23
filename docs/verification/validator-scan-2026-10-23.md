# Validator lifetime and scan admission P0 verification

## VLS-V01. Decision and scope

P0 attribution, representation and independent scan-admission experiments are complete. P1 is NO-GO. Implementation did not register production code, restart services, commit or push; the subsequently authorized submission review is recorded in VLS-V06. All 1841 initially present file fingerprints are preserved, including the previous proposal and parallel work. Only experiment modules, tests, paired specifications/tasks/report and sanitized evidence are added.

[Measurements](evidence/2026-10-23-validator-scan/measurements.json) include all 72 batches, 234 requests, pure-validator probes, phase costs and process samples. This is a 3-round diagnostic after a failed hard gate, not fixed performance acceptance, real-owner/browser acceptance or p95 evidence. Frozen monitor/result bytes are unchanged. Authority is synthetic in the benchmark but uses the existing event-loop/read-service checks; each monitor request retains 2 independent authority calls. Original authority/activation/time/lifecycle regressions also pass.

## VLS-V02. Representation and attribution

The unchanged model/parser constraints and canonical normalization remain. The experimental proof accepts original TEXT captured as UTF-8 bytes, preserves every model/domain/scalar/head check, streams domain hashes and compares the complete canonical literal including EOF. Public canonical APIs are untouched. A row-local helper releases preceding transient models; selected outputs and shared raw inputs remain owned.

For the valid 16,472,833-byte fixture, median traced peak falls from 156,429,042 bytes (149.18 MiB) to 24,866,343 bytes (23.71 MiB), approximately 84.10% lower. Raw input and expected output are prebuilt and excluded; Python/native allocator retention and process sampling are separate. This does not prove an enforceable memory bound.

On the 2008-row fixture, pure-validator median wall/CPU changes from 2.1487/2.015625 seconds to 4.7526/4.71875 seconds. Experimental phase thread-CPU medians are parse 0.71875, normalize 1.0, encode/hash 1.75 and literal comparison 1.125 seconds. These include phase instrumentation and Windows CPU quantization; independently aggregated medians need not sum to total. User/kernel counters are retained. The Python iterative encoding path materially regresses CPU. Retaining the normalized tree alone is not the main remaining memory cost; removing whole-document strings saves memory but Python-level iteration pays for it.

`iterencode()` still creates complete tokens, and request sort keys still use the original string encoder. Splitting emitted tokens into 8192-character slices does not bound producer allocation. Conservative two-generation scan admission is intentionally unchanged: the large-row workspace remains 197,697,036 bytes and fails the 64 MiB limit before payload execution. The full new and original pure validators accept the same large input. Availability and native-bound gates therefore still fail, despite the measured memory saving.

## VLS-V03. Concurrent comparison

The reference below is the previous ordered-scan/funded-cohort P0, not original production. All variants run in the same new diagnostic schedule without a child worker. Rows report 3 eight-reader batch medians and 3 mixed-batch medians. Every variant succeeds 39/39; all successful complete monitor/result output hashes match. Each variant preserves 3 proofs and 21 joins across its eight-reader batches. All ordinary end states have zero byte debt and zero outstanding owner work.

| Variant | Eight-reader wall seconds | Process CPU seconds | Mixed batch wall seconds |
|---|---:|---:|---:|
| ordered | 3.9364 | 9.328125 | 4.3929 |
| validator | 6.4774 | 11.84375 | 6.9458 |
| slots2 | 2.8312 | 3.140625 | 4.3747 |
| slots1 | 2.9258 | 2.828125 | 4.8129 |
| combined2 | 5.2416 | 5.53125 | 7.3284 |
| combined1 | 5.4872 | 5.46875 | 7.2500 |

`slots2` reduces eight-reader wall by approximately 28.08% and CPU by 66.33% versus `ordered`; mixed-batch wall is effectively flat in this small sample. `slots1` saves more CPU but has less favorable mixed-batch timing. Combined variants retain the encoder regression. These results support further scan-admission work, not integrating the combined candidate. All variants peak at 48,621,249 charged input bytes on the ordinary fixture. Sampled working set/private commit remain below 768 MiB/2560 MiB, but samples do not prove native bounds or near-limit availability. Exact GIL/SQLite/native mutex attribution remains unresolved; cursor wall/CPU and permit waits are recorded.

## VLS-V04. Correctness and lifecycle validation

The regression selection passes 170 tests, with 1 existing dependency warning. After adding the final 3 rehashed-domain cases, all 52 experiment tests pass; these overlap the regression selection and are not an additional 52 distinct regressions. Ruff and formatting checks pass.

Coverage includes all 19 raw fields against reference acceptance, canonical UTF-8/escaping/supplementary Unicode/EOF, missing payload and invalid storage, every domain hash, rich requests and rehashed per-fact formula tampering. Newly rehashed bar/request/formula damage is rejected even when the root hash is recomputed. Changing a field intentionally outside the original model identity contract preserves reference acceptance; independent follower equality still compares it.

Memory admission tests preserve rejection before payload allocation. Deterministic 8-reader funded-cohort tests pass with 1 and 2 shared scan slots, retaining 1 proof and 7 joins. Physical permit release, queued cancellation/deadline/stop, prepaid follower revocation, changed snapshots and no-leak normal drain are checked. Existing authority-after, activation, validity and observer-ownership regressions pass. Cursor cleanup failure retains global byte debt and storage closure; failed child cleanup is exercised through the existing injected-worker contract. Cancellation preserves submitted physical work and storage fences until drain. No claim is made that the experimental gate is integrated with a production worker.

The CPU permit surrounds cursor execute/fetch/closure, after existing byte leases. It is released before funded-cohort barriers; no permit is held while waiting for a physical proof. Cleanup errors may release a CPU slot while retaining byte debt and the closed-storage fence. These are distinct ownership obligations.

## VLS-V05. Reproduction and next step

Run the new `scripts.experiments.validator_benchmark` with `--monitor`, `--results`, `--run` and `--output` pointing at the existing frozen fixture. The module declares all 3 diagnostic rounds and variants. `scripts.experiments.validator_probe --memory --output ...` regenerates the large fixture; omit `--memory` and provide `--monitor` for pure-validator CPU attribution. Run timing probes sequentially. The evidence records source hashes and fixture hashes, never raw payloads. Final benchmark cleanup removes unreachable child-worker bookkeeping; the same variants receive an additional smoke check, recorded separately.

Next: keep scan admission as the strongest candidate; specify bounded producer/parser lifetimes and a faster byte-equivalent encoding strategy before reducing conservative input reservations. Avoid a large schema-walker rewrite until evidence justifies it. Preserve 64 MiB, independent authority and physical drain. Restore process experiments and fixed 10 A/A / 20 ABBA/BAAB acceptance only after hard gates pass; retain 20% mixed gain, <=5% isolated-result and <=10% monitor/CPU regression and no worse rejection/timeout. No integration candidate passed, so production/browser rollout is intentionally not entered.

## VLS-V06. Submission review

The user subsequently authorized review, commit and push of this P0 only. Scoped review found no blocking issue. The complete final regression selection passes 173 tests with 1 existing dependency warning; Ruff, formatting, paired document IDs/numbers/code and local links pass. Two mutations that make bar/request digest comparison trust corrupted input are both killed by the rehashed-domain tests. These process-local mutations do not modify source files or the recorded timing evidence.

The submission whitelist contains 15 files: paired proposal/specification/tasks/report, analysis/measurement evidence, experimental validator/permit/adapter/benchmark/probe and its tests. No production source or parallel AI extraction/daily-inventory file is included. Source hashes, frozen database hashes, all 234 successful diagnostic requests and 1841 original file fingerprints were rechecked. P1 remains blocked; committing this experiment does not enable it.

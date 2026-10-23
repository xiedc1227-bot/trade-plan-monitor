# Native build and failure ownership P0 report

## NBB-V01. Outcome

P1 remains NO-GO. The isolated failure boundary reduces retained failure graphs but does not reduce their construction peak. Actual-build/native allocation qualification remains NOT_PROVEN; both legal-large-row SQL admissions still fail. Production integration, reduced reservations, native allocator fault injection and browser acceptance are deferred, not passed. Existing analysis and parallel AI extraction/daily-inventory work are preserved.

## NBB-V02. Build and native qualification

The current binary still matches the previously downloaded official wheel: SHA256 `5ba0685a9153952ce1b5e1e8e5939685a675c0ca5786e720cfef255cb1b62a3e`. Runtime reports `profile=release pgo=false`. The [source/build investigation](../specifications/backtesting/PROPOSAL-native-build-error-budget.md) already records matching release source, lock/SBOM, the workflow discrepancy and unavailable job logs/artifacts. This run rechecks the installed identity, rather than claiming those missing artifacts were recovered.

Neither `rustc`, `cargo` nor `cl` resolves on PATH; the usual user Rust compiler and Visual Studio Installer discovery paths are absent. This limits local rebuild feasibility, not proof that no compiler exists anywhere. No toolchain or dependency was installed. A reproducible instrumented build requires provisioned, pinned tools and a separately qualified binary; this stage did not build one.

| Ownership area | Evidence | Qualification |
|---|---|---|
| Failure graph after validation | Trace and differential release measurements | Improved retained Python memory |
| Parser tree/scratch/error conversion and inner exceptions | Release source ownership analysis; process snapshots | Native allocation sizes/reallocation peaks unproven |
| SQLite/driver/cast buffers and raw generations | Existing conservative admission; unchanged SQL path | Reduced alias/generation accounting not qualified |
| C writer/UTF-8/model/normalized overlap | Existing full-validator traces | Native transient envelope unproven |
| Concurrent process aggregate | Point-in-time working set/private counters | No concurrent absolute upper-bound certification |

The recorded Windows process counters include instrumentation and prebuilt expected models; they are neither native-only figures nor peak guarantees. All original memory limits remain. No allocation coefficient was reduced. Native allocation failure injection remains deferred because the required qualified interception/build target is absent.

## NBB-V03. Failure lifecycle implementation

`failure_boundary.py` calls the existing fused full validator unchanged. Known exact projection failures become a frozen boolean description after the exception handler exits; source errors are not stored in it. Underlying iterator cleanup runs first. Unknown failures and subclasses propagate. A failure-only synchronous collection releases cyclic model-validator exception graphs before a new local exception is raised. It does not cancel workers, change authority checks, refund leases or modify storage cleanup.

This is an isolated experiment. Explicit collection is process-wide and may pause unrelated work; it is not approved for production or claimed to be free. A fresh raised exception can still contain caller/input frames; the bounded description does not imply all caller-owned raw data is gone. Any future integration must retain ownership for those objects through actual drain and account for failure collection before releasing budgets. The experiment does not solve peak error construction.

## NBB-V04. Measured comparison

Three alternating frozen pure-validator CPU rounds, complete output equality. SQL and authority are outside timing. The baseline dataset and both synthetic databases have unchanged before/after SHA256. [Measurements](evidence/2026-10-23-native-build-error-budget-p0/measurements.json) preserve attempts and code fingerprints.

| Variant | Median wall seconds | Median thread CPU seconds |
|---|---:|---:|
| Original | 2.086379 | 2.078125 |
| Fused before this change | 2.215568 | 2.203125 |
| Failure boundary | 2.224581 | 2.171875 |

Candidate CPU is `4.51%` above original and `1.42%` below fused in this diagnostic. Small differences are not a fixed performance pass or established speedup.

| Shape/path | Fused live/peak MiB | Boundary live/peak MiB |
|---|---:|---:|
| Long Decimal / success | 7.537 / 23.881 | 7.531 / 23.874 |
| Dense / success | 73.402 / 136.859 | 73.402 / 136.859 |
| Long Decimal / invalid | 23.947 / 23.947 | 0.020 / 23.947 |
| Dense / invalid | 149.531 / 149.531 | 0.025 / 149.531 |

One traced pass per cell; prebuilt raw and expected outputs excluded. Native allocations are not fully traced. Invalid long-Decimal thread CPU increases from `0.203125 s` to `0.296875 s`; dense-invalid CPU increases from `1.828125 s` to `2.218750 s`. Collection cost is included in the candidate but the baseline retains its error graph until after the live measurement. These are different release boundaries; they demonstrate the cost of earlier physical cleanup, not equal-lifecycle throughput. Supplemental tests were dispatched near the end of the diagnostic session; memory-stage wall times are not acceptance evidence. No mixed-load improvement is claimed.

## NBB-V05. Actual legal-row admission

Both valid fixtures pass the complete pure validator with equal outputs. In isolated SQLite, the unchanged scanner still requests `197697036 B` for long Decimal and `145472808 B` for dense objects against `67108864 B`. Each executes one metadata query, zero payload queries and ends with zero charged bytes. This is safe rejection and failed availability, not a functioning large-row fallback.

The [proposal arithmetic](../specifications/backtesting/PROPOSAL-native-build-error-budget.md) still applies: removing decoded-text reservations alone leaves the long-Decimal progress bundle over budget. Since native/generation ownership is unqualified, implementing a lower funded bundle would violate the gate. New reduced-bundle SQL integration and its concurrency experiment are explicitly deferred. Existing funded-cohort/deadlock tests are regression coverage, not evidence that a new large-row path works.

## NBB-V06. Verification and reproduction

New failure-boundary tests initially fail on the missing module, then pass. One regression selection passes `211` tests; a supplemental selection passes `30`. The final candidate-specific selection passes `32`, including eight concurrent failure deliveries; selections overlap and must not be summed. Coverage includes raw-field and coherent rehashed-domain tampering, success equality, missing dependency, independent concurrent contexts, failure graph release, distinct exceptions, unexpected cleanup propagation, cancellation, funded-cohort deadlock, authority/reactivation, time boundaries and storage cleanup debt. One existing dependency deprecation warning remains. An initial default-environment run had fixture setup errors; the successful runs use fresh project-local temporary directories and full local execution permissions.

Ruff check/format passes. Only new files are added; no previously tracked production or experimental implementation is edited. Parallel changes to README.md and README.zh-CN.md appeared during final review; they concern extraction prompt inputs and are preserved outside this P0 scope. No service restart, live-data mutation, commit or push. Browser validation is deferred because integration is blocked.

Run `python -m scripts.experiments.failure_boundary_benchmark --monitor PATH --fixtures FIXTURES --output FRESH_DIRECTORY`. FIXTURES contains the frozen `decimal.sqlite3` and `dense.sqlite3`; output must be new. Measurements include process observations, failure GC costs, SQL refusal and debt. Final source changes only wrap two report strings; evidence retains both measured and final source fingerprints. The next step is provisioned native qualification and closure of allocation envelopes, not a production rollout of this failure experiment.

## NBB-V07. Submission review

The user subsequently authorized review, commit and push of this P0. The combined regression selection passes `242` tests with one existing warning. Review removed test-side garbage collection that could hide omitted candidate cleanup and added unknown projection-subclass propagation coverage; the revised candidate selection passes `33` tests. A process-local mutation removing failure collection is killed by the new assertion without rewriting source. These selections overlap and must not be summed.

Ruff check/format, paired IDs/literals/links, implementation and frozen-input fingerprints pass. Prior measurements are preserved; the expensive benchmark was not rerun. Submission includes only this proposal, specification, tasks, isolated experiment, tests and evidence; README, AI extraction and daily-inventory work are excluded. Native bounds and legal-row admission remain unqualified; P1 stays disabled.

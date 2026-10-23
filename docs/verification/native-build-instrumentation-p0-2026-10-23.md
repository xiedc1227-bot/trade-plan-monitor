# Native qualification and failure recovery P0 report

## BIR-V01. Status

P1 remains disabled. Native interception, a native upper bound and reduced legal-row admission are not qualified. See the paired [specification](../specifications/backtesting/SPEC-native-build-instrumentation.md) and [tasks](../specifications/backtesting/TASKS-native-build-instrumentation.md). Production validators, authority checks, leases and cancellation/drain behavior are unchanged. Parallel README, AI extraction and daily-inventory changes are excluded.

## BIR-V02. Failure recovery experiment

The new `failure_recovery_probe.py` runs fresh child processes with automatic GC enabled. Both variants deliver fresh exceptions through the same caller catch. Each child performs three full failed validations; final physical collection is timed for both variants. The scope candidate postpones its cleanup obligation until that endpoint and is never used to authorize a budget refund. The older `failure_boundary.latest` remains unchanged.

Three alternating diagnostic rounds per fixture/variant give these median total thread CPU seconds:

| Fixture | Full collection per failure | Scope plus final collection | Difference |
|---|---:|---:|---:|
| Long Decimal | 0.937500 | 0.687500 | -26.67% |
| Dense errors | 2.515625 | 2.375000 | -5.59% |

These are totals for three calls, not per-request latency. Toolchain installation ran concurrently, so this is not a quiet-machine or mixed-load performance gate. Earlier capture-only diagnostics are retained separately and superseded for delivery comparisons. The [final measurements](evidence/2026-10-23-native-build-instrumentation-p0/equal-delivery.json) retain all attempts, automatic GC state, input hashes and source identity. No new native-memory ceiling is claimed.

The cycle counterexample proves scope exit alone can leave objects alive. A test mutation that omits final physical collection is rejected. Thus this result does not authorize deleting collection from the existing validator, releasing cleanup debt early, or skipping error/model work. Native coverage and complete failure-path ownership remain required.

## BIR-V03. Legal-row result

Both frozen valid large rows pass complete pure validation. Actual isolated SQL admission still requests `197697036 B` / `145472808 B` against `67108864 B`, performs one metadata query and zero payload queries, and ends with zero charged bytes. Before/after admission is unchanged: availability fails safely. No coefficient or memory category was changed to manufacture a pass.

## BIR-V04. Verification

The existing focused regression selection passes `174` tests, covering all raw fields, rehashed domain tampering, concurrent funded scans/deadlock, independent authority and eligibility/time boundaries, cancellation, physical ownership and cleanup failure. The new build/failure diagnostic selection passes `6` tests; these selections are disjoint. One existing FastAPI dependency deprecation warning remains. Ruff and bilingual IDs/literals checks pass. No browser acceptance is claimed because no integrated candidate is enabled.

Reproduce the diagnostic with `python -m scripts.experiments.failure_recovery_probe --fixtures FIXTURES --output FRESH_DIRECTORY`. FIXTURES contains frozen `decimal.sqlite3` and `dense.sqlite3`. The output directory must be new. No live database is written.

## BIR-V05. Build qualification

Windows Build Tools `17.14.42`, Rustup `1.29.1` / Rust `1.94.0`, and isolated maturin `1.13.1` were actually installed. MSVC is `19.44.35229.0`, SDK `10.0.26100.0`. Rust initially waited in winget's installer queue; that unstarted request was cancelled and the same hash-verified installer run directly. No reboot was performed. [Provisioning evidence](evidence/2026-10-23-native-build-instrumentation-p0/provision.json) records actual identities. This is a newly prepared target, not reconstruction of the historical official compiler.

The native build-script canary confirms `RUSTFLAGS=Err(NotPresent)` and `CARGO_ENCODED_RUSTFLAGS=Ok("-Copt-level=2")`. The earlier flag-reporting hypothesis now has a real build observation; it still does not determine historical PGO flags.

Both clean release builds completed, but their wheel members differ. Each native binary is `5805056 B`; exactly `19` bytes differ, all within the COFF/debug timestamps and CodeView GUID. SBOM differences include timestamp, UUID and source-directory references, with consequent RECORD changes. [Full build logs](evidence/2026-10-23-native-build-instrumentation-p0/build.json) and [difference classification](evidence/2026-10-23-native-build-instrumentation-p0/reproducibility.json) are retained. No binary/header/SBOM bytes were stripped or ignored to claim a pass. Byte reproducibility fails.

Consequently BIR-T02 remains unqualified and dependent BIR-T03 native interception/failure injection is **not implemented or executed**. P0 is not fully complete. This is the dependency stop in BIR08/BIR-S02, not a successful allocator experiment. The next required build work is deterministic linker/debug metadata and SBOM generation while preserving dependency provenance; then repeat clean builds before hooks. Scope diagnostics and conservative SQL regressions were independently executable and completed. No reduced-budget implementation or P1 is enabled.

The Windows provisioning/build outcome is recorded separately with installer identities and actual tool versions. `native_build_probe.py` verifies the frozen source archive, isolates Cargo cache and target directories, disables compiler wrappers/incremental compilation, performs locked dependency acquisition followed by offline release builds, and compares wheel member hashes from two clean directories. It records failures without asserting native qualification. It must run in an x64 MSVC developer environment with the isolated maturin and Python executables.

The measured runner reported empty compiler-environment fields because Windows uppercased dictionary keys; the independent provisioning manifest supplies the actual versions. Final review fixes that reporting, records runner identity, and makes a differing-build CLI return a failure exit code. Measured logs remain unchanged in substance; no native recompilation is claimed for these reporting changes.

No production wheel replacement, service restart, commit or push is part of this implementation turn. Three-domain interception and reduced admission remain dependent on a qualified build; a build or diagnostic pass alone cannot enable P1.

## BIR-V06. Submission review

The user subsequently authorized review, commit and push of this P0. Review found that an interrupted failure diagnostic could lose completed attempts. The probe now atomically checkpoints each attempt and records failure details before propagating errors. Timeout and nonzero-child tests first reproduced the missing evidence, then passed; an in-memory mutation omitting the final failure checkpoint is rejected by both cases. No measured validation/GC code changed. Prior CPU/build measurements and their original source fingerprints remain historical evidence; the expensive experiments were not rerun.

The combined submission regression selection passes `182` tests with one existing dependency warning. Ruff check/format, bilingual parity, evidence consistency and scoped-file review pass. This approval is for the isolated experiments and accurate failure reporting: byte reproducibility, native allocation qualification and legal-large-row availability remain failed/unproven, and P1 stays disabled. Only the P0 specifications, experiments, tests and evidence are submitted; AI extraction, daily inventory and README changes are excluded.

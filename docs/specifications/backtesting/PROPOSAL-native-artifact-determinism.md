# Deterministic native artifacts before allocator qualification

## NAD01. Decision and scope

Close native-binary, SBOM and whole-wheel reproducibility in that order, using the installed toolchain before considering upgrades. The current failure has identifiable metadata causes, and small builds now demonstrate a viable linker/clock configuration. Full pydantic-core qualification still fails; allocator interception, reduced admission and P1 remain blocked by the existing gates.

This proposal follows `e74605d` and the [previous P0 report](../../verification/native-build-instrumentation-p0-2026-10-23.md). This turn adds paired proposals and [analysis evidence](../../verification/evidence/2026-10-23-native-artifact-determinism-next/analysis.json), including a [self-contained canary recipe and results](../../verification/evidence/2026-10-23-native-artifact-determinism-next/canary.json). It performs isolated, dependency-free diagnostic builds only. No production change, dependency replacement, full-core rebuild, hook implementation, budget reduction, commit or push. Existing AI extraction, daily-inventory and README work is preserved. Complete paired specifications/tasks before implementing this proposal.

## NAD02. What actually failed

The previous R1/R2 native binaries are both `5805056 B`, with exactly `19` different bytes. Every difference is in a COFF timestamp, debug-directory timestamp or CodeView GUID. Both embedded PDB paths are already `_pydantic_core.pdb`; there is no observed absolute PDB-path difference in these binaries. This classifies this pair's differences, but does not establish runtime equivalence or future builds' determinism.

The SBOM differs at `serialNumber`, `metadata.timestamp`, `metadata.component.bom-ref`, `metadata.component.components[0].bom-ref` and `dependencies[0].ref`. The last three contain the different absolute source directories. Changes to the native binary and SBOM propagate into `RECORD`.

There is also a verification gap: `native_build_probe.members()` compares a dictionary of uncompressed member hashes. It does not prove identical ZIP bytes, and a dictionary hides duplicate filenames. Inspection now shows the original wheels have identical member order, dates, permissions, compression methods, extra fields and comments; their ZIP dates are already `1980-01-01`. Thus ZIP timestamps are not an additional observed cause in this pair, but the whole-wheel gate must still be added.

## NAD03. New controlled observations

Six dependency-free Rust binary-wheel builds used Rust `1.94.0`, the installed MSVC toolchain, maturin `1.13.1`, independent source/target directories, offline builds, fat LTO, one codegen unit and the existing release strip policy. All variants use the same compiler path-remapping rule. Each row below compares two fresh directories. These are executable canaries, not pydantic-core/Python extension or allocator tests.

| Variant | Native SHA-256 equal | SBOM differences | Whole wheel equal |
|---|---|---|---|
| No fixed epoch or reproducible-linker option | No | Time, random serial and path references | No |
| Fixed `SOURCE_DATE_EPOCH` | No | Path references only | No |
| Fixed `SOURCE_DATE_EPOCH` plus `-Clink-arg=/Brepro` | Yes | Path references only | No |

The last pair has SHA-256 `2096ce4914f9bd97fb495014524a3187df19ded190a991db4d4d6b2e0aa9b0da`, identical CodeView GUIDs and debug type `16`. Native size changes from `116224 B` to `116736 B`, including reproducibility metadata. These are observed diagnostic sizes, not memory-envelope changes. The fixed epoch `1700000000` is a synthetic test input, not a claimed release date. The first launcher attempt failed to resolve `rustc.exe` before any build; absolute executable paths fixed that diagnostic setup, and all six subsequent builds completed.

The installed linker reports `14.44.35229.0`; its normal help does not list `/Brepro`. Treat this as an option experimentally supported by this exact toolchain, not a portable guarantee. Microsoft's [PE specification](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format#debug-type) explains that reproducibility debug entries use content-derived date fields. Do not interpret those fields as actual build time or zero them after linking. A type marker alone is insufficient: the complete binary must match.

## NAD04. Use existing SBOM support correctly

The [maturin `v1.13.1` lockfile](https://github.com/PyO3/maturin/blob/v1.13.1/Cargo.lock) pins `cargo-cyclonedx 0.5.9`; the original SBOM itself reports that version. Its [matching generator source](https://github.com/CycloneDX/cyclonedx-rust-cargo/blob/e58bd5590212f82c5b7e16dd3e2e819b0dbea5b1/cargo-cyclonedx/src/generator.rs) already honors `SOURCE_DATE_EPOCH`: it fixes the timestamp and omits the optional random serial number. The canary confirms both behaviors in the installed tool. Upgrading or disabling SBOM generation is unnecessary for these two fields. [CycloneDX 1.5](https://cyclonedx.org/docs/1.5/json/) recommends a serial number but does not require it; retain the upstream reproducible mode and identify each artifact by its full digest in the external build ledger.

The generator uses Cargo package IDs as component references. Rust path remapping cannot change that metadata graph; the canary still differs at exactly the three path-reference locations with remapping enabled. [Rust `1.94.0` documents](https://github.com/rust-lang/rust/blob/1.94.0/src/doc/rustc/src/remap-source-paths.md) that remapping is textual and does not cover all linker/external-tool paths. Do not expect one compiler flag to solve SBOM identity or future PDB paths.

## NAD05. P0-A: pin clocks, inputs and native generation

Freeze the verified source archive, `Cargo.lock`, dependency hashes/features, Python ABI/import-library/DLL, compiler/linker/SDK/CRT, Rust and maturin executable identities. Include the runner, any build-only patch and explicit non-PGO policy. Use a validated source-derived epoch recorded in the recipe, never the current time or an arbitrary copied canary date. Keep actual start/end times and real physical paths in a separate build ledger bound to artifact hashes; explain the reproducible timestamp policy there.

Allowlist the build environment and inspect Cargo configuration ancestry. Explicitly control linker selection, wrappers, `LINK`, `_LINK_`, compiler overrides, target-specific Cargo options, profile settings and flag precedence. Capture effective compiler/linker arguments and response files, not just desired environment strings. Use `CARGO_ENCODED_RUSTFLAGS` consistently for arguments containing spaces, including path remapping and `/Brepro`; fail on unknown/ignored-option warnings even if the linker exits successfully. Keep incremental compilation/linking disabled. No environment secrets belong in the evidence.

Build the complete uninstrumented target R twice from separate clean roots and compare every `.pyd` byte without masking timestamps, GUIDs or any section. If different, classify the new differences and stop this gate. Do not change compiler, linker and optimization profile simultaneously. Add a third clean build with a different-length path containing spaces/non-ASCII characters, different source mtimes and recorded time-zone settings. Keep release debug policy unchanged; if a future I target requires PDBs, qualify PDB identity and PE/PDB association separately rather than deleting debug information to pass.

## NAD06. P0-B: deterministic SBOM without losing provenance

Prefer a small, reviewed build-only patch at maturin's [SBOM generation boundary](https://github.com/PyO3/maturin/blob/v1.13.1/src/sbom.rs), after the dependency graph exists and before JSON serialization/wheel writing. Preserve the core source and all dependency checks. Pin the patched backend's source, lockfile, patch and executable hashes in an isolated build environment; do not modify the service environment or silently use a floating replacement.

Construct an explicit mapping from known local package IDs to stable, collision-checked references using the verified source/patch digest, package-relative manifest path, name and version. Target subcomponent identities must retain their distinct suffix/identity. Registry and git dependency identities stay intact. Paths outside the verified source closure require their own pinned source manifest or must fail. Handle Windows separators and URI encoding deliberately; do not globally replace arbitrary path-looking text or merge same-name packages from different sources.

Apply the mapping to every schema-defined component/dependency reference, including nested components and graph edges. Reject duplicate identities, unresolved references and unhandled local-reference forms. Verify graph equivalence under the mapping and preserve all package versions, checksums, licenses, dependency edges, scopes, properties and target information. Keep the raw SBOM and mapping manifest as external audit evidence. Only known identity fields and the documented upstream epoch/serial behavior may differ; no component or integrity-bearing field is discarded.

A fixed logical root inside independently recreated Windows environments is a possible alternative if patch maintenance is unacceptable. Reusing one dirty directory or hiding path differences during comparison is not equivalent. Prefer the explicit mapping because it supports independent local build roots and makes the provenance transformation reviewable. This mapping has not been implemented or validated in this analysis.

## NAD07. P0-C: final artifact gates and negative controls

Let the existing [wheel writer](https://github.com/PyO3/maturin/blob/v1.13.1/src/module_writer/wheel_writer.rs) write the generated SBOM and calculate `RECORD` from actual bytes. Compare full `.pyd`, SBOM, every wheel member and the entire wheel SHA-256. Independently validate `RECORD` hashes/sizes, unique member names, safe member paths, deterministic order/permissions/compression, complete SBOM graph and schema validity. Signing/attestation timestamps, if later introduced, belong to an explicitly separate envelope with a binding to the unsigned artifact; they must not be silently excluded from a signed-artifact equality claim.

Required controls: removing `/Brepro` or the fixed epoch must expose the corresponding nondeterminism; altering compiled source must change native bytes; changing a dependency/version/checksum or local source identity must change its provenance; moving unchanged source must not. Corrupt a binary byte, remove an SBOM edge, duplicate a component/member, break a reference, alter `RECORD`, and supply invalid/out-of-range epochs. Each must be rejected by its relevant independent gate. Reject unsupported formats, missing artifacts, unexpected extra wheels and incomplete attempts. Preserve failures and all completed measurements before propagating build errors/timeouts.

Acceptance is complete equality across the clean R builds plus passing negative controls. No normalized comparison, deleted SBOM, forced constant GUID, copied output artifact or semantic-only equality may substitute. Same-source reproducibility establishes repeatable target identity, not source correctness or production equivalence to the currently installed official wheel.

## NAD08. P0-D and P1: qualify ownership before admitting large rows

After R passes, build I with a separate, minimal allocation-observer patch; R and I are intentionally different artifacts. Qualify repeatability within each configuration, strict successful/failing behavior and canonical-byte equivalence, and account for instrumentation's allocation effects. Continue the existing Rust/Python/actual-SQLite coverage plan: bounded nonallocating telemetry, cross-thread ownership, reallocation overlap, overflow detection, dense errors and supervised failure injection. Observed peaks without complete coverage and source-derived bounds still cannot authorize a reservation reduction.

Then derive phase/owner bounds for the real uninstrumented candidate. The unchanged SQL reservations remain `197697036 B` and `145472808 B` against `67108864 B`; these are pre-payload refusals, not measured OOMs. The installed runtime hash remains `5ba0685a9153952ce1b5e1e8e5939685a675c0ca5786e720cfef255cb1b62a3e`. A new R/I proof cannot lower budgets for that different runtime. Any candidate replacement needs its own isolated service comparison before integration.

Keep equal-lifetime failure CPU measurements separate from reproducibility work. Preserve physical collection/debt for cyclic or unqualified failures; build success does not authorize removing GC. Revisit the fully funded progress bundle only after native bounds close. P1 requires all existing admission, CPU, concurrency and browser gates, not merely matching wheels.

## NAD09. Unchanged safety and acceptance contract

The [BIR08 contract](PROPOSAL-native-build-instrumentation.md#bir08-stages-and-unchanged-gates) remains normative: every request performs independent authority checks before/after and an activation reread. Retain all history, `19` raw fields and SQL types, missing-dependency checks, strict models, canonical UTF-8/EOF, bar/request/root/formula and per-fact validation. No completed-proof cache or trust in stored hashes. Cancellation detaches observers or prevents unstarted work; physical work, transport and retained outputs remain owned through actual release. Cleanup failures retain debt and fence later generations.

Keep `64 MiB` input, `768 MiB` aggregate working set, `2560 MiB` private commit, `1` physical proof, `1` queued owner, `15-second` waits, `90-second` eligibility and `2` attempts. Retest `1/2/8` readers, tampering with recomputed hashes, time boundaries, cancelled leaders/followers, final-observer departure, deadlock and cleanup/storage failure when an implementation candidate exists. Retain `3` diagnostic rounds for failed gates; qualified performance needs `10` A/A pairs, `20` ABBA/BAAB blocks, `20%` mixed-process gain, at most `5%` result and `10%` monitor/total-CPU regression, and no worse refusals/timeouts. Browser qualification still needs `100` attempts per variant and `100` successes before p95 claims, with `20%` mixed-p95 improvement.

This analysis verifies the six canary outcomes, evidence consistency, bilingual parity and unchanged installed runtime. It does not rerun service/browser acceptance or claim that allocator bounds or legal-large-row availability now pass.

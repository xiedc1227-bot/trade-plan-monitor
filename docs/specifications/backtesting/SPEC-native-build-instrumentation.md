# Native build and instrumentation P0

## BIR-S01. Contract

Implement [BIR01–BIR08](PROPOSAL-native-build-instrumentation.md) in isolated experiments. Its numeric gates and complete authority/integrity/drain requirements are normative and unchanged. Production integration is disabled until every gate passes. Preserve parallel AI extraction, daily inventory and README work.

## BIR-S02. Build

Provision Windows x64 tools; pin Rust `1.94.0` (source minimum `1.88`), Rustup `1.29.1`, Build Tools installer `17.14.42`, and maturin `1.13.1`. Record actual compiler/SDK versions separately: installer version does not pin component payloads. Verify source archive, lockfile and binaries. Two clean unmodified release builds must match; explicitly non-PGO. Instrumented builds cannot certify a different runtime. Missing tools/downloads/build failures are failed prerequisites, not passes.

## BIR-S03. Allocation

Qualify Rust, Python and actual SQLite domains with bounded native telemetry, cross-thread ownership and conservative reallocation overlap. No lower budget before native coverage and source bounds close. Do not substitute a Python accounting simulation for native interception. Fault injection runs only in disposable supervised children.

## BIR-S04. Failure experiment

Compare full collection with scope-only capture in isolated children with automatic GC enabled. Measure equal validation/release endpoints and separately charge final collection/debt. Include dense/Decimal invalid fixtures, repeat calls and adversarial cycles. Scope-only capture is diagnostic: it must not become a production validator or refund budget. Preserve original cycle-cleaning behavior until every supported failure branch is qualified.

## BIR-S05. Admission and acceptance

Re-run full valid large-row verification and real isolated SQL admission. If qualification fails, retain existing reservations and explicitly report availability failure. Run tamper, concurrency/deadlock, independent authority, time-boundary, cancellation and cleanup-failure regression tests. Browser acceptance only applies to an integrated qualified candidate; no browser/performance pass from unit tests. Record attempts, source/input hashes, failures and before/after comparisons in paired reports.
